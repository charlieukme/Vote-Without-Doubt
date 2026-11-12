"""phase_c11i_add_face_challenge_lease_fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-22 22:30:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('face_challenges') as batch_op:
        batch_op.add_column(sa.Column('lease_token', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_face_challenges_lease_token', ['lease_token'])
        batch_op.add_column(sa.Column('lease_expires_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('face_challenges') as batch_op:
        batch_op.drop_column('lease_expires_at')
        batch_op.drop_index('ix_face_challenges_lease_token')
        batch_op.drop_column('lease_token')
