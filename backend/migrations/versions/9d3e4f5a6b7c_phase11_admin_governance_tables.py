"""phase11: admin_users, admin_sessions, approval_requests, candidates, and election governance columns

Revision ID: 9d3e4f5a6b7c
Revises: 8c2d3e4f5a6b
Create Date: 2026-10-06 13:20:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '9d3e4f5a6b7c'
down_revision = '8c2d3e4f5a6b'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Admin Users
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), server_default='OFFICER', nullable=False),
        sa.Column('totp_secret_encrypted', sa.LargeBinary(), nullable=True),
        sa.Column('totp_enabled', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.Column('failed_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.Column('last_totp_step', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('admin_id'),
        sa.UniqueConstraint('email'),
        mysql_engine='InnoDB'
    )
    with op.batch_alter_table('admin_users', schema=None) as batch_op:
        batch_op.create_index('ix_admin_users_admin_id', ['admin_id'], unique=True)
        batch_op.create_index('ix_admin_users_email', ['email'], unique=True)
        batch_op.create_index('ix_admin_users_role', ['role'], unique=False)

    # 2. Admin Sessions
    op.create_table(
        'admin_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_token', sa.String(length=64), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked', sa.Boolean(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['admin_id'], ['admin_users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_token'),
        mysql_engine='InnoDB'
    )
    with op.batch_alter_table('admin_sessions', schema=None) as batch_op:
        batch_op.create_index('ix_admin_sessions_session_token', ['session_token'], unique=True)
        batch_op.create_index('ix_admin_sessions_admin_id', ['admin_id'], unique=False)

    # 3. Approval Requests
    op.create_table(
        'approval_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('election_id', sa.String(length=50), nullable=False),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('requester_id', sa.Integer(), nullable=False),
        sa.Column('approver_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('rejection_reason', sa.String(length=255), nullable=True),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['requester_id'], ['admin_users.id']),
        sa.ForeignKeyConstraint(['approver_id'], ['admin_users.id']),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB'
    )
    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.create_index('ix_approval_requests_election_id', ['election_id'], unique=False)
        batch_op.create_index('ix_approval_requests_action_type', ['action_type'], unique=False)
        batch_op.create_index('ix_approval_requests_status', ['status'], unique=False)
        batch_op.create_index('ix_approval_requests_requester_id', ['requester_id'], unique=False)
        batch_op.create_index('ix_approval_requests_approver_id', ['approver_id'], unique=False)

    # 4. Candidates
    op.create_table(
        'candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('election_id', sa.String(length=50), nullable=False),
        sa.Column('candidate_index', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('department', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('election_id', 'candidate_index', name='uq_candidate_election_index'),
        mysql_engine='InnoDB'
    )
    with op.batch_alter_table('candidates', schema=None) as batch_op:
        batch_op.create_index('ix_candidates_election_id', ['election_id'], unique=False)

    # 5. Election governance columns
    with op.batch_alter_table('elections', schema=None) as batch_op:
        batch_op.add_column(sa.Column('candidate_count', sa.Integer(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('eligible_count', sa.Integer(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('roll_hash', sa.String(length=66), nullable=True))
        batch_op.add_column(sa.Column('candidates_hash', sa.String(length=66), nullable=True))
        batch_op.add_column(sa.Column('max_ballots', sa.Integer(), server_default=sa.text('3'), nullable=False))
        batch_op.add_column(sa.Column('cancelled', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('scheduled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('closed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('finalized_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('created_by_officer_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('approved_by_officer_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('elections', schema=None) as batch_op:
        batch_op.drop_column('approved_by_officer_id')
        batch_op.drop_column('created_by_officer_id')
        batch_op.drop_column('finalized_at')
        batch_op.drop_column('closed_at')
        batch_op.drop_column('scheduled_at')
        batch_op.drop_column('cancelled')
        batch_op.drop_column('max_ballots')
        batch_op.drop_column('candidates_hash')
        batch_op.drop_column('roll_hash')
        batch_op.drop_column('eligible_count')
        batch_op.drop_column('candidate_count')

    op.drop_table('candidates')
    op.drop_table('approval_requests')
    op.drop_table('admin_sessions')
    op.drop_table('admin_users')
