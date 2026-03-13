import logging
import os
from fastapi import FastAPI, BackgroundTasks
from contextlib import asynccontextmanager

from app.database import db
from app.scheduler.jobs import setup_scheduler, fetch_and_analyze_job

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/app.log"), logging.StreamHandler()],
)
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
