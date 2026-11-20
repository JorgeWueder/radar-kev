"""laboratorio: estudios de Optuna

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

J = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        'ml_studies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('dataset_id', sa.UUID(), nullable=False),
        sa.Column('algorithm', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('config', J, nullable=False),
        sa.Column('space', J, nullable=False),
        sa.Column('trials', J, nullable=False),
        sa.Column('summary', J, nullable=False),
        sa.Column('best_params', J, nullable=False),
        sa.Column('best_value', sa.Float(), nullable=True),
        sa.Column('stop_requested', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('seconds', sa.Float(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['ml_datasets.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ml_studies_dataset_id', 'ml_studies', ['dataset_id'])


def downgrade() -> None:
    op.drop_index('ix_ml_studies_dataset_id', table_name='ml_studies')
    op.drop_table('ml_studies')
