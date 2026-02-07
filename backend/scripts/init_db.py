"""
Initialize database and run migrations. Run from backend dir: python -m scripts.init_db
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from alembic.config import Config
from alembic import command

def init_db():
    """Initialize database and run all migrations."""
    # Ensure database directory exists
    os.makedirs(os.path.dirname(settings.DATABASE_PATH) or ".", exist_ok=True)
    
    # Run Alembic migrations
    alembic_cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
    
    print("Running database migrations...")
    command.upgrade(alembic_cfg, "head")
    print(f"✓ Database initialized and migrations applied at {settings.DATABASE_PATH}")


if __name__ == "__main__":
    init_db()
