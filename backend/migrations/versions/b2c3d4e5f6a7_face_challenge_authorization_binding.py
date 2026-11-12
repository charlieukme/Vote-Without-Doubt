"""face_challenge_authorization_binding

Revision ID: b2c3d4e5f6a7
Revises: a1e2d3c4b5a6
Create Date: 2026-10-21 18:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1e2d3c4b5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('face_challenges') as batch_op:
        batch_op.add_column(sa.Column('authorization_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_face_challenges_auth_id', 'voting_authorizations', ['authorization_id'], ['id'])
        batch_op.create_index('ix_face_challenges_authorization_id', ['authorization_id'])
        batch_op.add_column(sa.Column('election_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_face_challenges_election_id', ['election_id'])
        batch_op.add_column(sa.Column('consumed', sa.Boolean(), server_default='0', nullable=False))
        batch_op.create_index('ix_face_challenges_consumed', ['consumed'])
        batch_op.add_column(sa.Column('consumed_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('face_challenges') as batch_op:
        batch_op.drop_column('consumed_at')
        batch_op.drop_index('ix_face_challenges_consumed')
        batch_op.drop_column('consumed')
        batch_op.drop_index('ix_face_challenges_election_id')
        batch_op.drop_column('election_id')
        batch_op.drop_constraint('fk_face_challenges_auth_id', type_='foreignkey')
        batch_op.drop_index('ix_face_challenges_authorization_id')
        batch_op.drop_column('authorization_id')
