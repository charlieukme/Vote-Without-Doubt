"""phase16: candidate profile metadata, election registration_deadline, and support_tickets

Revision ID: a1e2d3c4b5a6
Revises: 9d3e4f5a6b7c
Create Date: 2026-10-07 14:30:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1e2d3c4b5a6'
down_revision = '9d3e4f5a6b7c'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Candidate metadata extensions (safe, nullable)
    op.add_column('candidates', sa.Column('year', sa.String(length=20), nullable=True))
    op.add_column('candidates', sa.Column('slogan', sa.String(length=255), nullable=True))
    op.add_column('candidates', sa.Column('manifesto', sa.Text(), nullable=True))
    op.add_column('candidates', sa.Column('photo_url', sa.String(length=255), nullable=True))

    # 2. Election registration deadline (safe, nullable)
    op.add_column('elections', sa.Column('registration_deadline', sa.DateTime(), nullable=True))

    # 3. Support Tickets table
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reference_id', sa.String(length=32), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('details', sa.Text(), nullable=False),
        sa.Column('contact_email', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='OPEN', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB'
    )
    op.create_index('ix_support_tickets_reference_id', 'support_tickets', ['reference_id'], unique=True)


def downgrade():
    op.drop_index('ix_support_tickets_reference_id', table_name='support_tickets')
    op.drop_table('support_tickets')
    op.drop_column('elections', 'registration_deadline')
    op.drop_column('candidates', 'photo_url')
    op.drop_column('candidates', 'manifesto')
    op.drop_column('candidates', 'slogan')
    op.drop_column('candidates', 'year')
