"""add_sender_id_to_companies_remove_from_customers

Revision ID: 3f8a9b2c1d4e
Revises: 2ea77e65d5a4
Create Date: 2026-02-06 22:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f8a9b2c1d4e'
down_revision: Union[str, Sequence[str], None] = '2ea77e65d5a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add sender_id to companies table (each salon/company has its own sender ID)
    op.add_column('companies', sa.Column('sender_id', sa.String(length=10), nullable=True))
    
    # Remove sender_id from customers table (moved to companies)
    try:
        op.drop_column('customers', 'sender_id')
    except Exception:
        # Column might not exist, ignore error
        pass


def downgrade() -> None:
    """Downgrade schema."""
    # Remove sender_id from companies
    op.drop_column('companies', 'sender_id')
    
    # Add sender_id back to customers (for rollback)
    op.add_column('customers', sa.Column('sender_id', sa.String(length=10), nullable=True))
