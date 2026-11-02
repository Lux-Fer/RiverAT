"""run plan revision

Revision ID: 1c5e1f443e07
Revises: 07067e46ac6b
Create Date: 2026-11-03 00:04:18.956936

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c5e1f443e07'
down_revision: Union[str, Sequence[str], None] = '07067e46ac6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 记录这次执行用的是计划的哪一版（D70）；老数据留空
    op.add_column('run', sa.Column('plan_revision', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('run', 'plan_revision')
