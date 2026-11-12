"""phase9: ballot_queue unique constraint on (election_id, pseudonym, sequence) and is_null column

Revision ID: 8c2d3e4f5a6b
Revises: 7a1b2c3d4e5f
Create Date: 2026-10-06 06:15:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '8c2d3e4f5a6b'
down_revision = '7a1b2c3d4e5f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ballot_queue', schema=None) as batch_op:
        batch_op.drop_constraint('uq_ballot_queue_election_pseudonym', type_='unique')
        batch_op.add_column(sa.Column('is_null', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.create_unique_constraint(
            'uq_ballot_queue_election_pseudonym_seq',
            ['election_id', 'pseudonym', 'sequence']
        )


def downgrade():
    with op.batch_alter_table('ballot_queue', schema=None) as batch_op:
        batch_op.drop_constraint('uq_ballot_queue_election_pseudonym_seq', type_='unique')
        batch_op.drop_column('is_null')
        batch_op.create_unique_constraint(
            'uq_ballot_queue_election_pseudonym',
            ['election_id', 'pseudonym']
        )
