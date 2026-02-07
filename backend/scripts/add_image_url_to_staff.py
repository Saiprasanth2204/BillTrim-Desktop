"""
Add image_url column to staff table if it doesn't exist.
Run: python -m scripts.add_image_url_to_staff
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine
from sqlalchemy import text

def add_image_url_column():
    """Add image_url column to staff table if it doesn't exist."""
    with engine.connect() as conn:
        # Check if column exists
        result = conn.execute(text("PRAGMA table_info(staff)"))
        columns = [row[1] for row in result]
        
        if 'image_url' not in columns:
            print("Adding image_url column to staff table...")
            conn.execute(text("ALTER TABLE staff ADD COLUMN image_url VARCHAR(500)"))
            conn.commit()
            print("✓ Column added successfully")
        else:
            print("✓ Column image_url already exists")
    
    print("Migration complete!")

if __name__ == "__main__":
    add_image_url_column()
