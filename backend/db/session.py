"""Database session and engine management.

Provides async SQLAlchemy engine, session maker, and FastAPI dependency.
Seamlessly supports both PostgreSQL (production) and SQLite (testing/local fallback).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from db.models import Base

logger = logging.getLogger(__name__)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine(db_url: Optional[str] = None) -> AsyncEngine:
    """Return process-wide AsyncEngine singleton or create a new one."""
    global _engine
    if _engine is not None and db_url is None:
        return _engine

    url = db_url or settings.database_url

    engine_kwargs = {}
    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_async_engine(url, **engine_kwargs)

        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    else:
        # PostgreSQL / asyncpg configuration
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20
        engine = create_async_engine(url, **engine_kwargs)

    if db_url is None:
        _engine = engine

    return engine


def get_session_factory(engine: Optional[AsyncEngine] = None) -> async_sessionmaker[AsyncSession]:
    """Return process-wide sessionmaker singleton."""
    global _session_factory
    if _session_factory is not None and engine is None:
        return _session_factory

    eng = engine or get_engine()
    factory = async_sessionmaker(
        bind=eng,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    if engine is None:
        _session_factory = factory

    return factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async database session per request."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(engine: Optional[AsyncEngine] = None) -> None:
    """Create all tables in the database if they do not exist."""
    eng = engine or get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized successfully")


def reset_engine() -> None:
    """Reset the engine singleton (used in test teardown)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
