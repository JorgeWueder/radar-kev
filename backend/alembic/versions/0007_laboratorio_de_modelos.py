"""laboratorio de modelos: datasets y trabajos

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ml_datasets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('file_path', sa.String(length=300), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'ml_jobs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('message', sa.String(length=300), nullable=False),
        sa.Column('log', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('target_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ml_jobs_started_at', 'ml_jobs', ['started_at'])


def downgrade() -> None:
    op.drop_index('ix_ml_jobs_started_at', table_name='ml_jobs')
    op.drop_table('ml_jobs')
    op.drop_table('ml_datasets')
