# app/db.py
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    create_engine, event, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from .config import DB_PATH

Base = declarative_base()

class Book(Base):
    __tablename__ = "books"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    title_std   = Column(String, index=True, nullable=False, default="")
    authors_std = Column(String, index=True, nullable=True)

    publisher   = Column(String, nullable=True)   # 允许为 NULL
    pub_year    = Column(Integer, nullable=True)

    isbn        = Column(String, unique=True, index=True, nullable=True)  # 唯一
    edition     = Column(String, nullable=True)
    pages       = Column(Integer, nullable=True)

    summary     = Column(Text, nullable=True)
    author_bio  = Column(Text, nullable=True)
    language    = Column(String, nullable=True, default="中文")

    cover_path  = Column(String, nullable=True)

    cip         = Column(String, nullable=True)
    clc         = Column(String, nullable=True)

    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    sources     = relationship("Source", back_populates="book", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_books_title_authors", "title_std", "authors_std"),
    )


class Source(Base):
    __tablename__ = "sources"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    book_id    = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)

    site       = Column(String, index=True, nullable=False)  # douban / jd / ...
    url        = Column(String, nullable=True)               # 详情页 URL
    extracted  = Column(Text, nullable=True)                 # 原始字段 JSON

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    book       = relationship("Book", back_populates="sources")


# --- Engine & Session ---
engine = create_engine(f"sqlite:///{DB_PATH}", future=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

# SQLite 外键
@event.listens_for(engine, "connect")
def _fk_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
