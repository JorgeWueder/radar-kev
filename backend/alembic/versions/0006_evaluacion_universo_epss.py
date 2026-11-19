"""evaluacion prospectiva de EPSS sobre el universo de CVE

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'universe_evaluations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('until', sa.Date(), nullable=False),
        sa.Column('horizon_days', sa.Integer(), nullable=False),
        sa.Column('model_version', sa.String(length=40), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_universe_evaluations_computed_at', 'universe_evaluations', ['computed_at'])


def downgrade() -> None:
    op.drop_index('ix_universe_evaluations_computed_at', table_name='universe_evaluations')
    op.drop_table('universe_evaluations')
