"""v1.1 llm products tools

Revision ID: 5c89c9c9dd62
Revises: 15661b7075b0
Create Date: 2026-11-03 23:47:10.918697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5c89c9c9dd62'
down_revision: Union[str, Sequence[str], None] = '15661b7075b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('llm_config',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('base_url', sa.String(length=500), nullable=False),
    sa.Column('api_key_enc', sa.Text(), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_config_is_active'), 'llm_config', ['is_active'], unique=False)
    op.create_table('tool',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('bundle_sha256', sa.String(length=64), nullable=False),
    sa.Column('bundle_path', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('uploaded_by', sa.UUID(), nullable=True),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', 'version', name='uq_tool_name_version')
    )
    op.create_index(op.f('ix_tool_status'), 'tool', ['status'], unique=False)
    op.create_table('work_product',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('base_url', sa.String(length=500), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('ci_provider', sa.String(length=64), nullable=False),
    sa.Column('ci_webhook_url', sa.String(length=500), nullable=False),
    sa.Column('ci_secret_enc', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_product_code'), 'work_product', ['code'], unique=True)
    op.create_index(op.f('ix_work_product_status'), 'work_product', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_work_product_status'), table_name='work_product')
    op.drop_index(op.f('ix_work_product_code'), table_name='work_product')
    op.drop_table('work_product')
    op.drop_index(op.f('ix_tool_status'), table_name='tool')
    op.drop_table('tool')
    op.drop_index(op.f('ix_llm_config_is_active'), table_name='llm_config')
    op.drop_table('llm_config')
