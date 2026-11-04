"""v1.1 task heartbeat

Revision ID: 7425dedb7815
Revises: d7c35e160500
Create Date: 2026-11-04 17:42:35.866011

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7425dedb7815'
down_revision: Union[str, Sequence[str], None] = 'd7c35e160500'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('task', sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('task', 'heartbeat_at')
