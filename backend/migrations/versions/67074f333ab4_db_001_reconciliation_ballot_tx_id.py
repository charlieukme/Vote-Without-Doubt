"""db_001_reconciliation_ballot_tx_id

Revision ID: 67074f333ab4
Revises: 86592d28e4c4
Create Date: 2026-11-09 23:58:29.539703

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '67074f333ab4'
down_revision = '86592d28e4c4'
branch_labels = None
depends_on = None

naming_convention = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade():
    with op.batch_alter_table(
        'reconciliation_issues',
        schema=None,
        naming_convention=naming_convention,
    ) as batch_op:
        batch_op.add_column(sa.Column('protocol_version', sa.String(length=10), nullable=False, server_default='V1'))
        batch_op.drop_constraint('fk_reconciliation_issues_ballot_tx_id_ballots', type_='foreignkey')


def downgrade():
    with op.batch_alter_table(
        'reconciliation_issues',
        schema=None,
        naming_convention=naming_convention,
    ) as batch_op:
        batch_op.create_foreign_key(
            'fk_reconciliation_issues_ballot_tx_id_ballots',
            'ballots',
            ['ballot_tx_id'],
            ['id'],
        )
        batch_op.drop_column('protocol_version')
