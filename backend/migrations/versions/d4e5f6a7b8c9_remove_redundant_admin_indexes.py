"""remove redundant unique indexes on admin_users and admin_sessions

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-27 16:30:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    # Drop redundant explicit unique indexes while preserving table UniqueConstraints
    with op.batch_alter_table('admin_users', schema=None) as batch_op:
        batch_op.drop_index('ix_admin_users_admin_id')
        batch_op.drop_index('ix_admin_users_email')

    with op.batch_alter_table('admin_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_admin_sessions_session_token')


def downgrade():
    # Restore explicit unique indexes if rolled back
    with op.batch_alter_table('admin_users', schema=None) as batch_op:
        batch_op.create_index('ix_admin_users_admin_id', ['admin_id'], unique=True)
        batch_op.create_index('ix_admin_users_email', ['email'], unique=True)

    with op.batch_alter_table('admin_sessions', schema=None) as batch_op:
        batch_op.create_index('ix_admin_sessions_session_token', ['session_token'], unique=True)
