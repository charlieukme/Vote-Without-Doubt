"""phase7: ballot_queue unique constraint on election_id and pseudonym

Revision ID: 7a1b2c3d4e5f
Revises: 4f2b7c91de50
Create Date: 2026-10-05 22:15:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '7a1b2c3d4e5f'
down_revision = '4f2b7c91de50'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ballot_queue', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_ballot_queue_election_pseudonym',
            ['election_id', 'pseudonym']
        )


def downgrade():
    with op.batch_alter_table('ballot_queue', schema=None) as batch_op:
        batch_op.drop_constraint('uq_ballot_queue_election_pseudonym', type_='unique')
