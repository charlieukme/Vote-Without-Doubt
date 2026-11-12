"""phase10d v2 election keys and protocol version

Revision ID: f1a2b3c4d5e6
Revises: 67074f333ab4
Create Date: 2026-11-12 11:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = '67074f333ab4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if 'elections' not in existing_tables:
        return

    existing_cols = {col['name'] for col in inspector.get_columns('elections')}

    with op.batch_alter_table('elections', schema=None) as batch_op:
        if 'v2_priv_key_1' not in existing_cols:
            batch_op.add_column(sa.Column('v2_priv_key_1', sa.Text(), nullable=True))
        if 'v2_priv_key_2' not in existing_cols:
            batch_op.add_column(sa.Column('v2_priv_key_2', sa.Text(), nullable=True))
        if 'protocol_version' not in existing_cols:
            batch_op.add_column(sa.Column('protocol_version', sa.String(length=10), nullable=True))

    # Safe backfill for legacy/existing rows without touching historical ballot or key data.
    if 'officer_registrations_v2' in existing_tables or 'ballot_queue_v2' in existing_tables:
        v2_clauses = [
            "v2_priv_key_1 IS NOT NULL",
            "v2_priv_key_2 IS NOT NULL",
            "(status IN ('SCHEDULED', 'OPEN', 'CLOSED', 'FINALIZED') AND id >= 10)",
        ]
        if 'officer_registrations_v2' in existing_tables:
            v2_clauses.append(
                "CAST(id AS TEXT) IN (SELECT DISTINCT CAST(election_id AS TEXT) FROM officer_registrations_v2)"
            )
            v2_clauses.append(
                "election_id IN (SELECT DISTINCT CAST(election_id AS TEXT) FROM officer_registrations_v2)"
            )
        if 'ballot_queue_v2' in existing_tables:
            v2_clauses.append(
                "CAST(id AS TEXT) IN (SELECT DISTINCT CAST(election_id AS TEXT) FROM ballot_queue_v2)"
            )
            v2_clauses.append(
                "election_id IN (SELECT DISTINCT CAST(election_id AS TEXT) FROM ballot_queue_v2)"
            )
        op.execute(
            sa.text(
                f"UPDATE elections SET protocol_version = 'V2' "
                f"WHERE protocol_version IS NULL AND ({' OR '.join(v2_clauses)})"
            )
        )

    v1_clauses = []
    if 'ballot_queue' in existing_tables:
        v1_clauses.append("id IN (SELECT DISTINCT election_id FROM ballot_queue WHERE election_id IS NOT NULL)")
    if 'ballots' in existing_tables:
        v1_clauses.append("election_id IN (SELECT DISTINCT election_id FROM ballots WHERE election_id IS NOT NULL)")
    v1_clauses.append("(v2_priv_key_1 IS NULL AND v2_priv_key_2 IS NULL AND id < 9)")

    op.execute(
        sa.text(
            f"UPDATE elections SET protocol_version = 'V1' "
            f"WHERE protocol_version IS NULL AND ({' OR '.join(v1_clauses)})"
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if 'elections' not in existing_tables:
        return

    existing_cols = {col['name'] for col in inspector.get_columns('elections')}

    with op.batch_alter_table('elections', schema=None) as batch_op:
        if 'protocol_version' in existing_cols:
            batch_op.drop_column('protocol_version')
        if 'v2_priv_key_2' in existing_cols:
            batch_op.drop_column('v2_priv_key_2')
        if 'v2_priv_key_1' in existing_cols:
            batch_op.drop_column('v2_priv_key_1')

