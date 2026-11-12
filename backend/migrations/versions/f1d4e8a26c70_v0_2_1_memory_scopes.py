"""v0.2.1 knowledge scopes, ttl and feedback

Revision ID: f1d4e8a26c70
Revises: e7b2c9d41a60
Create Date: 2026-11-12 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1d4e8a26c70'
down_revision: Union[str, Sequence[str], None] = 'e7b2c9d41a60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'knowledge_item',
        sa.Column('scope', sa.String(length=32), nullable=False, server_default='product'),
    )
    op.add_column(
        'knowledge_item',
        sa.Column('owner_id', sa.UUID(), nullable=True),
    )
    op.create_index('ix_knowledge_item_scope', 'knowledge_item', ['scope'], unique=False)
    op.create_index('ix_knowledge_item_owner_id', 'knowledge_item', ['owner_id'], unique=False)
    op.execute(
        "UPDATE knowledge_item SET scope = 'global' WHERE product_id IS NULL"
    )

    op.create_table(
        'knowledge_feedback',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('helpful', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('reason', sa.String(length=500), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['item_id'], ['knowledge_item.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', 'task_id', 'user_id', name='uq_knowledge_feedback'),
    )
    op.create_index('ix_knowledge_feedback_item_id', 'knowledge_feedback', ['item_id'], unique=False)
    op.create_index('ix_knowledge_feedback_task_id', 'knowledge_feedback', ['task_id'], unique=False)
    op.create_index('ix_knowledge_feedback_user_id', 'knowledge_feedback', ['user_id'], unique=False)
    op.create_index('ix_knowledge_feedback_created_at', 'knowledge_feedback', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_knowledge_feedback_created_at', table_name='knowledge_feedback')
    op.drop_index('ix_knowledge_feedback_user_id', table_name='knowledge_feedback')
    op.drop_index('ix_knowledge_feedback_task_id', table_name='knowledge_feedback')
    op.drop_index('ix_knowledge_feedback_item_id', table_name='knowledge_feedback')
    op.drop_table('knowledge_feedback')
    op.drop_index('ix_knowledge_item_owner_id', table_name='knowledge_item')
    op.drop_index('ix_knowledge_item_scope', table_name='knowledge_item')
    op.drop_column('knowledge_item', 'owner_id')
    op.drop_column('knowledge_item', 'scope')
