from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
import os
from app.core.logging_config import get_logger
logger = get_logger("auth")

# Ensure database path is absolute and directory exists
# Get the actual path from DATABASE_URL (which handles relative paths correctly)
db_url = settings.DATABASE_URL
# Extract path from sqlite:///path/to/db
db_path = db_url.replace("sqlite:///", "")
db_dir = os.path.dirname(db_path)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)
    # Ensure directory is writable
    if not os.access(db_dir, os.W_OK):
        raise PermissionError(f"Database directory is not writable: {db_dir}")

# Ensure database file is writable if it exists
if os.path.exists(db_path):
    if not os.access(db_path, os.W_OK):
        raise PermissionError(f"Database file is not writable: {db_path}")

engine_kw = {
    "connect_args": {
        "check_same_thread": False,
        "timeout": 20.0,  # Wait up to 20 seconds for locks
    },
    "pool_pre_ping": True,
    "echo": settings.DEBUG,
}
engine = create_engine(settings.DATABASE_URL, **engine_kw)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except:
        db.rollback()
        raise
    finally:
        db.close()
