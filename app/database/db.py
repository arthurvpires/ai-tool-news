from sqlalchemy import create_engine, Column, String, DateTime, Integer
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from app.config import settings
import logging

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class ProcessedContent(Base):
    __tablename__ = "processed_content"

    content_id = Column(String, primary_key=True, index=True)
    source = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, default=None)

def init_db():
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized.")

def is_content_processed(content_id: str) -> bool:
    with SessionLocal() as session:
        exists = session.query(ProcessedContent).filter(ProcessedContent.content_id == content_id).first()
        return exists is not None

def mark_content_processed(content_id: str, source: str, sent_at: datetime = None):
    with SessionLocal() as session:
        if not is_content_processed(content_id):
            db_item = ProcessedContent(
                content_id=content_id, 
                source=source, 
                sent_at=sent_at or datetime.utcnow()
            )
            session.add(db_item)
            session.commit()
