"""merkle_root, ballot commitments, and election archival

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-31 10:35:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ballot_queue', schema=None) as batch_op:
        batch_op.add_column(sa.Column('commitment', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('commitment_nonce', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_ballot_queue_commitment', ['commitment'], unique=False)

    with op.batch_alter_table('elections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('merkle_root', sa.String(length=66), nullable=True))
        batch_op.add_column(sa.Column('is_archived', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('elections', schema=None) as batch_op:
        batch_op.drop_column('is_archived')
        batch_op.drop_column('merkle_root')

    with op.batch_alter_table('ballot_queue', schema=None) as batch_op:
        batch_op.drop_index('ix_ballot_queue_commitment')
        batch_op.drop_column('commitment_nonce')
        batch_op.drop_column('commitment')
