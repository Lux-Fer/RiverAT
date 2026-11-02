"""release

Revision ID: 80f27aacf4fc
Revises: 1c5e1f443e07
Create Date: 2026-11-03 00:22:20.600370

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80f27aacf4fc'
down_revision: Union[str, Sequence[str], None] = '1c5e1f443e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('release',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('product_version_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('target_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['product_version_id'], ['product_version.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_release_product_version_id'), 'release', ['product_version_id'], unique=False)
    op.create_index(op.f('ix_release_status'), 'release', ['status'], unique=False)
    op.create_index(op.f('ix_release_target_date'), 'release', ['target_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_release_target_date'), table_name='release')
    op.drop_index(op.f('ix_release_status'), table_name='release')
    op.drop_index(op.f('ix_release_product_version_id'), table_name='release')
    op.drop_table('release')
