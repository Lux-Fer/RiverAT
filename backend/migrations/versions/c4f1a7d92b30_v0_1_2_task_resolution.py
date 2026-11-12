"""v0.1.2 task resolution link

Revision ID: c4f1a7d92b30
Revises: 7425dedb7815
Create Date: 2026-11-12 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f1a7d92b30'
down_revision: Union[str, Sequence[str], None] = '7425dedb7815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'task',
        sa.Column('resolved_by_task_id', sa.UUID(), nullable=True),
    )
    op.add_column(
        'task',
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_task_resolved_by_task',
        'task',
        'task',
        ['resolved_by_task_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_task_resolved_by_task_id',
        'task',
        ['resolved_by_task_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_task_resolved_by_task_id', table_name='task')
    op.drop_constraint(
        'fk_task_resolved_by_task', 'task', type_='foreignkey'
    )
    op.drop_column('task', 'resolved_at')
    op.drop_column('task', 'resolved_by_task_id')
