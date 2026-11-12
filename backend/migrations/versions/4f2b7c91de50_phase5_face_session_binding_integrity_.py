"""phase5 face: session binding, challenge integrity, consent and provenance

Adds the Phase 5 remediation columns.

``face_challenges``
  * ``session_id``    - binds a challenge to the issuing session, not just the
                        user, so it cannot be replayed from another session.
  * ``nonce``         - 256-bit value folded into the row's integrity MAC.
  * ``integrity_mac`` - HMAC over the server-authoritative fields, so editing
                        the stored expected sequence in the database is detected.
  * ``attempt_count`` / ``max_attempts`` - server-side attempt budget.
  * ``challenge_sequence`` narrowed from TEXT to VARCHAR(32) because it now holds
                        a fixed two-token order, never free text.

``face_enrollments``
  * ``embedding_model`` / ``embedding_dim`` - which model produced the template,
                        so a future model change cannot be applied silently to
                        templates it did not produce.
  * ``embedding_key_id`` - which encryption key wrapped the ciphertext, enabling
                        rotation without losing existing templates.
  * ``consent_purpose`` / ``withdrawn_at`` / ``template_deleted_at`` - consent
                        scope and proof of withdrawal.

Legacy rows are handled explicitly: an unbindable challenge cannot be made safe,
so any pre-existing challenge is marked consumed rather than left usable.

Revision ID: 4f2b7c91de50
Revises: 58781e8f838c
Create Date: 2026-10-05 11:05:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '4f2b7c91de50'
down_revision = '58781e8f838c'
branch_labels = None
depends_on = None

# Any challenge that predates session binding cannot be tied to a session, so it
# is retired instead of being given a placeholder binding it never had.
RETIRED_SESSION = 'unbound-legacy-challenge'
RETIRED_SEQUENCE = 'RETIRED'
RETIRED_NONCE = 'retired'
RETIRED_MAC = 'retired'


def upgrade():
    with op.batch_alter_table('face_challenges', schema=None) as batch_op:
        batch_op.add_column(sa.Column('session_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('nonce', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('integrity_mac', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('attempt_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('max_attempts', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_face_challenges_session_id'),
                              ['session_id'], unique=False)

    # Retire anything issued before session binding existed.
    op.execute(
        sa.text(
            "UPDATE face_challenges SET session_id = :session, nonce = :nonce, "
            "integrity_mac = :mac, attempt_count = :attempts, max_attempts = :max_attempts, "
            "completed = 1, challenge_sequence = :sequence "
            "WHERE session_id IS NULL OR challenge_sequence IS NULL"
        ).bindparams(
            session=RETIRED_SESSION,
            nonce=RETIRED_NONCE,
            mac=RETIRED_MAC,
            attempts=1,
            max_attempts=1,
            sequence=RETIRED_SEQUENCE,
        )
    )

    with op.batch_alter_table('face_challenges', schema=None) as batch_op:
        batch_op.alter_column('session_id',
                              existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column('nonce',
                              existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column('integrity_mac',
                              existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column('attempt_count',
                              existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('max_attempts',
                              existing_type=sa.Integer(), nullable=False)
        # The stored order is a fixed two-token sequence, not free text, and it
        # is now mandatory: a challenge with no sequence cannot be authenticated
        # against its integrity MAC.
        batch_op.alter_column('challenge_sequence',
                              existing_type=sa.Text(), type_=sa.String(length=32),
                              existing_nullable=True, nullable=False)

    with op.batch_alter_table('face_enrollments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('embedding_model', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('embedding_dim', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('embedding_key_id', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('consent_purpose', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('withdrawn_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('template_deleted_at', sa.DateTime(), nullable=True))

    # A template whose encryption key is unknown cannot be decrypted, rotated or
    # audited. Backfill provenance so existing rows stay readable and gain the
    # new NOT NULL constraints.
    op.execute(
        sa.text(
            "UPDATE face_enrollments SET embedding_model = :model, embedding_dim = :dim, "
            "embedding_key_id = :key_id, consent_purpose = :purpose "
            "WHERE embedding_model IS NULL"
        ).bindparams(
            model='arcface_cosine',
            dim=512,
            key_id='v1',
            purpose='election_identity_verification',
        )
    )

    with op.batch_alter_table('face_enrollments', schema=None) as batch_op:
        batch_op.alter_column('embedding_method',
                              existing_type=sa.String(length=50),
                              type_=sa.String(length=64), existing_nullable=False)
        batch_op.alter_column('embedding_model',
                              existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column('embedding_dim',
                              existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('embedding_key_id',
                              existing_type=sa.String(length=32), nullable=False)
        batch_op.alter_column('consent_purpose',
                              existing_type=sa.String(length=64), nullable=False)


def downgrade():
    with op.batch_alter_table('face_enrollments', schema=None) as batch_op:
        batch_op.alter_column('consent_purpose',
                              existing_type=sa.String(length=64), nullable=True)
        batch_op.alter_column('embedding_key_id',
                              existing_type=sa.String(length=32), nullable=True)
        batch_op.alter_column('embedding_dim',
                              existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('embedding_model',
                              existing_type=sa.String(length=64), nullable=True)
        batch_op.alter_column('embedding_method',
                              existing_type=sa.String(length=64),
                              type_=sa.String(length=50), existing_nullable=False)
        batch_op.drop_column('template_deleted_at')
        batch_op.drop_column('withdrawn_at')
        batch_op.drop_column('consent_purpose')
        batch_op.drop_column('embedding_key_id')
        batch_op.drop_column('embedding_dim')
        batch_op.drop_column('embedding_model')

    with op.batch_alter_table('face_challenges', schema=None) as batch_op:
        batch_op.alter_column('challenge_sequence',
                              existing_type=sa.String(length=32),
                              type_=sa.Text(), existing_nullable=False,
                              nullable=True)
        batch_op.alter_column('max_attempts', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('attempt_count', existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column('integrity_mac', existing_type=sa.String(length=64), nullable=True)
        batch_op.alter_column('nonce', existing_type=sa.String(length=64), nullable=True)
        batch_op.drop_index(batch_op.f('ix_face_challenges_session_id'))
        batch_op.drop_column('max_attempts')
        batch_op.drop_column('attempt_count')
        batch_op.drop_column('integrity_mac')
        batch_op.drop_column('nonce')
        batch_op.drop_column('session_id')
