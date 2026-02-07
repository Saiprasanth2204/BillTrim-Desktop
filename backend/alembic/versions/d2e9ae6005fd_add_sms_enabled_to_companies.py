"""add_sms_enabled_to_companies

Revision ID: d2e9ae6005fd
Revises: 3f8a9b2c1d4e
Create Date: 2026-02-06 23:23:21.151450

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e9ae6005fd'
down_revision: Union[str, Sequence[str], None] = '3f8a9b2c1d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add sms_enabled column to companies table
    op.add_column('companies', sa.Column('sms_enabled', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove sms_enabled column from companies table
    op.drop_column('companies', 'sms_enabled')
