from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Text, Integer
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from app.config import settings
import logging
import json

logger = logging.getLogger(__name__)

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class ProcessedContent(Base):
    __tablename__ = "processed_content"

    content_id = Column(String, primary_key=True, index=True)
    source = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, default=None)

    # Metadata for pending items
    is_relevant = Column(Boolean, default=False)
    relevance_score = Column(Integer, default=0)
    text = Column(Text, nullable=True)
    company = Column(String, nullable=True)
    url = Column(String, nullable=True)
    images_json = Column(Text, nullable=True)  # JSON string of images list
    video = Column(String, nullable=True)
    analysis_summary = Column(Text, nullable=True)
    analysis_category = Column(String, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized.")


def is_content_processed(content_id: str) -> bool:
    with SessionLocal() as session:
        exists = session.query(ProcessedContent).filter(ProcessedContent.content_id == content_id).first()
        return exists is not None


def mark_content_processed(content_id: str, source: str, metadata: dict = None):
    with SessionLocal() as session:
        if not is_content_processed(content_id):
            sent_at = metadata.pop("sent_at", None) if metadata else None

            db_item = ProcessedContent(content_id=content_id, source=source, sent_at=sent_at)

            if metadata:
                db_item.is_relevant = metadata.get("relevant", False)
                db_item.relevance_score = metadata.get("relevance_score", 0)
                db_item.text = metadata.get("text")
                db_item.company = metadata.get("company")
                db_item.url = metadata.get("url")
                if metadata.get("images"):
                    db_item.images_json = json.dumps(metadata.get("images"))
                db_item.video = metadata.get("video")
                db_item.analysis_summary = metadata.get("summary")
                db_item.analysis_category = metadata.get("category")

            session.add(db_item)
            session.commit()
