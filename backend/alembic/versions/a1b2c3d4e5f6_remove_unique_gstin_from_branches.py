"""remove unique gstin from branches

Revision ID: a1b2c3d4e5f6
Revises: d2e9ae6005fd
Create Date: 2026-02-07

Allow multiple branches to share the same GSTIN (e.g. same company).
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd2e9ae6005fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the unique index on branches.gstin
    op.drop_index(op.f('ix_branches_gstin'), table_name='branches')
    # Recreate as non-unique index
    op.create_index(op.f('ix_branches_gstin'), 'branches', ['gstin'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_branches_gstin'), table_name='branches')
    op.create_index(op.f('ix_branches_gstin'), 'branches', ['gstin'], unique=True)
