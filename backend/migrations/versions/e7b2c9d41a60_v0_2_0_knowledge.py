"""v0.2.0 knowledge events and items

Revision ID: e7b2c9d41a60
Revises: c4f1a7d92b30
Create Date: 2026-11-12 15:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e7b2c9d41a60'
down_revision: Union[str, Sequence[str], None] = 'c4f1a7d92b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'knowledge_event',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('event_key', sa.String(length=240), nullable=False),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('task_id', sa.UUID(), nullable=True),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('source', sa.String(length=64), nullable=False, server_default='riverat'),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('sensitivity', sa.String(length=32), nullable=False, server_default='internal'),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['work_product.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_knowledge_event_event_key', 'knowledge_event', ['event_key'], unique=True)
    op.create_index('ix_knowledge_event_kind', 'knowledge_event', ['kind'], unique=False)
    op.create_index('ix_knowledge_event_product_id', 'knowledge_event', ['product_id'], unique=False)
    op.create_index('ix_knowledge_event_task_id', 'knowledge_event', ['task_id'], unique=False)
    op.create_index('ix_knowledge_event_occurred_at', 'knowledge_event', ['occurred_at'], unique=False)

    op.create_table(
        'knowledge_item',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('item_key', sa.String(length=240), nullable=False),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=True),
        sa.Column('tool_id', sa.UUID(), nullable=True),
        sa.Column('task_id', sa.UUID(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='tentative'),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['product_id'], ['work_product.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tool_id'], ['tool.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_knowledge_item_item_key', 'knowledge_item', ['item_key'], unique=True)
    op.create_index('ix_knowledge_item_kind', 'knowledge_item', ['kind'], unique=False)
    op.create_index('ix_knowledge_item_product_id', 'knowledge_item', ['product_id'], unique=False)
    op.create_index('ix_knowledge_item_tool_id', 'knowledge_item', ['tool_id'], unique=False)
    op.create_index('ix_knowledge_item_task_id', 'knowledge_item', ['task_id'], unique=False)
    op.create_index('ix_knowledge_item_status', 'knowledge_item', ['status'], unique=False)
    op.create_index('ix_knowledge_item_created_at', 'knowledge_item', ['created_at'], unique=False)
    op.execute(
        "CREATE INDEX ix_knowledge_item_trgm ON knowledge_item "
        "USING gin ((title || ' ' || body) gin_trgm_ops)"
    )

    op.create_table(
        'knowledge_item_source',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('event_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['knowledge_event.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['knowledge_item.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_id', 'event_id', name='uq_knowledge_item_source'),
    )
    op.create_index('ix_knowledge_item_source_item_id', 'knowledge_item_source', ['item_id'], unique=False)
    op.create_index('ix_knowledge_item_source_event_id', 'knowledge_item_source', ['event_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_knowledge_item_source_event_id', table_name='knowledge_item_source')
    op.drop_index('ix_knowledge_item_source_item_id', table_name='knowledge_item_source')
    op.drop_table('knowledge_item_source')
    op.drop_index('ix_knowledge_item_trgm', table_name='knowledge_item')
    op.drop_index('ix_knowledge_item_created_at', table_name='knowledge_item')
    op.drop_index('ix_knowledge_item_status', table_name='knowledge_item')
    op.drop_index('ix_knowledge_item_task_id', table_name='knowledge_item')
    op.drop_index('ix_knowledge_item_tool_id', table_name='knowledge_item')
    op.drop_index('ix_knowledge_item_product_id', table_name='knowledge_item')
    op.drop_index('ix_knowledge_item_kind', table_name='knowledge_item')
    op.drop_index('ix_knowledge_item_item_key', table_name='knowledge_item')
    op.drop_table('knowledge_item')
    op.drop_index('ix_knowledge_event_occurred_at', table_name='knowledge_event')
    op.drop_index('ix_knowledge_event_task_id', table_name='knowledge_event')
    op.drop_index('ix_knowledge_event_product_id', table_name='knowledge_event')
    op.drop_index('ix_knowledge_event_kind', table_name='knowledge_event')
    op.drop_index('ix_knowledge_event_event_key', table_name='knowledge_event')
    op.drop_table('knowledge_event')
