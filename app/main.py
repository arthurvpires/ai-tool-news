import logging
import os
import sys
from fastapi import FastAPI, BackgroundTasks
from contextlib import asynccontextmanager

from app.database import db
from app.scheduler.jobs import setup_scheduler, fetch_and_analyze_job

os.makedirs("logs", exist_ok=True)


class ColorFormatter(logging.Formatter):
    GREY = "\033[90m"
    WHITE = "\033[37m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD_RED = "\033[1;31m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

    LEVEL_COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: CYAN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, self.WHITE)
        timestamp = self.formatTime(record, "%H:%M:%S")
        level = f"{record.levelname:<8}"
        return f"{self.GREY}{timestamp}{self.RESET} {color}{level}{self.RESET} {record.getMessage()}"


file_handler = logging.FileHandler("logs/app.log")
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(ColorFormatter())

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

for noisy in ["httpx", "httpcore", "hpack"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.ERROR)

for uv_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    uv_logger = logging.getLogger(uv_name)
    uv_logger.handlers.clear()
    uv_logger.propagate = True
    if uv_name == "uvicorn.access":
        uv_logger.setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

scheduler = setup_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup on startup
    scheduler.start()
    logger.info("Scheduler started.")

    # Run once immediately on startup alongside the interval
    try:
        import asyncio

        asyncio.create_task(fetch_and_analyze_job())
    except Exception as e:
        logger.error(f"Error running initial job: {e}")

    yield
    # Teardown on shutdown
    scheduler.shutdown()
    logger.info("Scheduler shutdown.")


app = FastAPI(title="AI News Bot API", lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok", "scheduler_running": scheduler.state == 1}


@app.post("/run-collector")
async def manual_run_collector(background_tasks: BackgroundTasks):
    """Manually trigger the collection and dispatch process in the background."""
    background_tasks.add_task(fetch_and_analyze_job)
    return {"message": "Collector job started in the background."}


@app.get("/stats")
def get_stats():
    """Return some basic system stats."""
    total_processed = db.get_total_count()
    return {"total_processed": total_processed}
