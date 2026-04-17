"""
api/database/engine.py
──────────────────────
PostgreSQL database connection, pooling, and session management.
Uses psycopg2 driver with QueuePool for production workloads.
"""

import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

logger = logging.getLogger("eagleeye.database")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://eagleeye_user:password@localhost:5432/eagleeye_db",
)

# ── Validate ──────────────────────────────────────────────────

if not DATABASE_URL.startswith("postgresql"):
    print(
        f"[DB] ⚠ DATABASE_URL does not start with 'postgresql': "
        f"{DATABASE_URL[:40]}..."
    )
    print(
        "[DB]   Expected: postgresql://user:password@host:port/dbname"
    )

# ── Engine ────────────────────────────────────────────────────

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=False,
    connect_args={
        "application_name": "eagleeye-nigeria",
        "options": "-c timezone=utc",
    },
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# ── Dependency ────────────────────────────────────────────────

def get_db():
    """FastAPI dependency — yields a DB session, auto-closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Initialization ────────────────────────────────────────────

def init_db():
    """
    Connect to PostgreSQL, enable extensions, and create all tables.
    Safe to call multiple times.
    """
    from api.database import models  # noqa: F401 — register all models

    try:
        with engine.connect() as conn:
            # Test connection
            result = conn.execute(text("SELECT version()"))
            pg_version = result.scalar()
            print(f"[DB] ✓ Connected to PostgreSQL")
            print(f"[DB]   Version: {pg_version}")

            # Enable extensions
            for ext in ["pg_trgm", "btree_gist", "uuid-ossp"]:
                try:
                    conn.execute(
                        text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
                    )
                except Exception as ext_err:
                    print(f"[DB]   ⚠ Extension '{ext}' failed: {ext_err}")

            conn.commit()
            print("[DB] ✓ PostgreSQL extensions verified")

        # Create tables
        Base.metadata.create_all(bind=engine)
        print("[DB] ✓ All database tables created/verified")

        # Report table list
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY tablename
            """))
            tables = [row[0] for row in result]
            print(f"[DB]   Tables: {', '.join(tables)}")

    except Exception as e:
        print(f"[DB] ✗ Database initialization failed: {e}")
        print(f"[DB]   URL: {_mask_url(DATABASE_URL)}")
        print(f"[DB]   Ensure PostgreSQL is running and database exists:")
        print(f"[DB]   CREATE DATABASE eagleeye_db;")
        raise


def check_db_health() -> dict:
    """Health check for the /health endpoint."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

            result = conn.execute(text("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public'
            """))
            tables = [row[0] for row in result]

            # Pool stats
            pool = engine.pool
            pool_info = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
            }

        return {
            "status": "healthy",
            "database": "postgresql",
            "tables": tables,
            "table_count": len(tables),
            "pool": pool_info,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "postgresql",
            "error": str(e),
        }


def _mask_url(url: str) -> str:
    """Mask password in connection URL for safe logging."""
    try:
        if "@" in url and "://" in url:
            prefix = url.split("://")[0]
            rest = url.split("://")[1]
            user_part = rest.split("@")[0]
            user = user_part.split(":")[0]
            host_part = rest.split("@")[1]
            return f"{prefix}://{user}:****@{host_part}"
    except Exception:
        pass
    return "****"