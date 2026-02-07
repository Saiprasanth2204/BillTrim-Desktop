#!/usr/bin/env python3
"""
Delete all data from all application tables and the stored license file.
Uses the same database as the app (DATABASE_PATH / data/billtrim.db).
Also removes license.key from Electron userData if present.

Run from project root with backend venv active:
  cd backend && pip install -r requirements.txt   # if needed
  python scripts/clear_all_data.py

Or from repo root using the bundled venv (after build):
  build/bundled-venv/bin/python backend/scripts/clear_all_data.py
"""
import sys
import os

# Ensure backend root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine, Base
# Import all models so Base.metadata is populated
from app.models import (  # noqa: F401
    Company, Branch, User, UserSession, Customer, Staff,
    Service, Product, Appointment, AppointmentService,
    Invoice, InvoiceItem, Payment, BrandingSettings, Attendance, Membership,
)


def clear_license_file():
    """Remove license.key from known Electron userData locations (desktop app)."""
    # Same locations Electron uses: app.getPath('userData') + '/license.key'
    # productName is "BillTrim Desktop"
    home = os.path.expanduser("~")
    app_name = "BillTrim Desktop"
    candidates = [
        os.path.join(home, "Library", "Application Support", app_name, "license.key"),  # macOS
        os.path.join(os.environ.get("APPDATA", ""), app_name, "license.key"),            # Windows
        os.path.join(home, ".config", app_name, "license.key"),                          # Linux
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                os.remove(path)
                print(f"Deleted license file: {path}")
                return
            except OSError as e:
                print(f"Warning: Could not delete license file {path}: {e}", file=sys.stderr)
    # Optional: if BILLTRIM_LICENSE_PATH is set (e.g. by Electron), use it
    env_path = os.environ.get("BILLTRIM_LICENSE_PATH")
    if env_path and os.path.isfile(env_path):
        try:
            os.remove(env_path)
            print(f"Deleted license file: {env_path}")
        except OSError as e:
            print(f"Warning: Could not delete license file {env_path}: {e}", file=sys.stderr)


def clear_all_tables():
    db_url = str(engine.url)
    is_sqlite = "sqlite" in db_url

    with engine.begin() as conn:
        if is_sqlite:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
        try:
            for table in reversed(list(Base.metadata.tables.values())):
                name = table.name
                conn.execute(text(f"DELETE FROM {name}"))
                print(f"Cleared: {name}")
        finally:
            if is_sqlite:
                conn.execute(text("PRAGMA foreign_keys = ON"))
    print("All tables cleared.")


if __name__ == "__main__":
    clear_all_tables()
    clear_license_file()
