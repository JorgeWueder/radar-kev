"""laboratorio: modelos entrenados

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

J = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        'ml_models',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('dataset_id', sa.UUID(), nullable=False),
        sa.Column('algorithm', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('config', J, nullable=False),
        sa.Column('folds', J, nullable=False),
        sa.Column('aggregate', J, nullable=False),
        sa.Column('trials', J, nullable=False),
        sa.Column('best_params', J, nullable=False),
        sa.Column('final_metrics', J, nullable=False),
        sa.Column('reading', J, nullable=False),
        sa.Column('model_path', sa.String(length=300), nullable=True),
        sa.Column('preds_path', sa.String(length=300), nullable=True),
        sa.Column('seconds', sa.Float(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['ml_datasets.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ml_models_dataset_id', 'ml_models', ['dataset_id'])


def downgrade() -> None:
    op.drop_index('ix_ml_models_dataset_id', table_name='ml_models')
    op.drop_table('ml_models')
