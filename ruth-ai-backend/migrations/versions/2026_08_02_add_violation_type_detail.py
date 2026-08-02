"""preserve the model's specific violation vocabulary alongside the enum

`violations.type` is a Postgres enum with four members (fall_detected,
ppe_violation, zone_intrusion, zone_exit), but the models emit a much larger
and independently-evolving vocabulary: missing_hardhat / missing_vest /
missing_goggles / missing_mask, possible_fall, tank_critical_high /
tank_critical_low / tank_overflow_warning. Those values were written straight
into the enum column, so every insert carrying one failed and the violation was
silently lost — roughly 80% of writes at the time this was found, which is why
`SELECT DISTINCT type` returned only the two values that happened to be legal.

The fix maps each specific value onto its enum family at the write boundary
rather than extending the enum. The enum is schema; the model vocabulary is
not, and it changes whenever a model adds a class (the PPE detector already
recognises gloves and boots), so coupling the two means a migration per model
change and a silent data-loss bug for every one that gets missed. This mirrors
the reasoning already applied to devices.in_out.

`type_detail` keeps the specific value so nothing is lost: `type` stays a
stable, queryable, four-value classification, and `type_detail` answers "which
PPE item was missing". Indexed because "show me every missing_hardhat" is the
question operators actually ask.

Backfill: none possible. Rows that would have carried a specific value were
never written — they failed their insert. Existing rows are genuine
ppe_violation / fall_detected values, so a NULL type_detail correctly means
"no more specific value was reported".

Revision ID: add_violation_type_detail
Revises: add_device_structured_naming
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_violation_type_detail"
down_revision: Union[str, None] = "add_device_structured_naming"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain text, deliberately not an enum: this column exists precisely to
    # hold values whose vocabulary the database should not be coupled to.
    op.add_column(
        "violations",
        sa.Column("type_detail", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_violations_type_detail", "violations", ["type_detail"])


def downgrade() -> None:
    op.drop_index("ix_violations_type_detail", table_name="violations")
    op.drop_column("violations", "type_detail")
