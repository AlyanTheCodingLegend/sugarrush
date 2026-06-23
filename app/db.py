from __future__ import annotations
import json
import logging
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    Text, ForeignKey, JSON,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.config import DATABASE_URL, COMPETITORS

logger = logging.getLogger(__name__)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    category = Column(String, nullable=True)
    instagram_handle = Column(String, nullable=True)
    website = Column(String, nullable=True)
    place_id = Column(String, nullable=True)
    source = Column(String, default="seed")   # seed | discovered
    created_at = Column(DateTime, default=datetime.utcnow)


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True)
    command = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")   # running | ok | partial | error
    sources_ok = Column(JSON, default=list)
    sources_failed = Column(JSON, default=list)
    finding_count = Column(Integer, default=0)


class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    competitor_name = Column(String, nullable=False)
    source_platform = Column(String, nullable=False)
    update_type = Column(String, nullable=False)
    content_text = Column(Text, nullable=False)
    rating = Column(Float, nullable=True)
    post_date = Column(DateTime, nullable=True)
    source_url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    engagement = Column(JSON, nullable=True)
    collected_at = Column(DateTime, default=datetime.utcnow)
    ai_summary = Column(Text, nullable=True)
    relevance_score = Column(Integer, nullable=True)
    content_hash = Column(String, nullable=False, index=True)


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    command = Column(String, nullable=False)
    report_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _seed_competitors()


def _seed_competitors() -> None:
    with SessionLocal() as db:
        if db.query(Competitor).count() > 0:
            return
        for c in COMPETITORS:
            db.add(Competitor(
                name=c["name"],
                category=c.get("category"),
                instagram_handle=c.get("instagram_handle"),
                website=c.get("website"),
                source="seed",
            ))
        db.commit()
        logger.info("Seeded %d competitors into DB", len(COMPETITORS))
