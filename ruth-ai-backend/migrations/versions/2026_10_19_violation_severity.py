"""Add violations.severity and backfill it.

Severity is the firing rule's judgement (critical/high/medium/low) from the
model's manifest. The store plugin has always reported it with every
detection; the write path dropped it, so the Violations page could only
show confidence, styled like a severity.

Backfill: every existing row is matched on its specific type against the
manifest values as of this migration (a unit test keeps this table equal to
ai/store_plugin/manifests), then the built-in defaults by specific type and
by family, then 'medium' — the same order resolve_severity() uses. A
migration must not read the live store, so the values are inlined.

Not added to violations_archive: an archived row restored later has NULL
severity and resolves at read time.

Revision ID: violation_severity
Revises: evidence_file_path
"""

import sqlalchemy as sa
from alembic import op

revision = "violation_severity"
down_revision = "evidence_file_path"
branch_labels = None
depends_on = None

#: Manifest rule severities by violation_type (ai/store_plugin/manifests).
MANIFEST_SEVERITY = {
    "missing_hardhat": "critical",
    "missing_vest": "critical",
    "missing_harness": "critical",
    "missing_gloves": "high",
    "missing_goggles": "high",
}

#: Built-in defaults (app/services/violation_severity.BUILTIN_SEVERITY).
BUILTIN_DETAIL_SEVERITY = {
    "possible_fall": "high",
    "tank_critical_high": "critical",
    "tank_critical_low": "critical",
    "tank_overflow_warning": "high",
}
BUILTIN_FAMILY_SEVERITY = {
    "fall_detected": "critical",
    "ppe_violation": "high",
    "zone_intrusion": "high",
    "zone_exit": "medium",
}


def upgrade() -> None:
    op.add_column("violations", sa.Column("severity", sa.String(16), nullable=True))
    op.create_index("ix_violations_severity", "violations", ["severity"])

    for detail, level in {**BUILTIN_DETAIL_SEVERITY, **MANIFEST_SEVERITY}.items():
        op.execute(
            sa.text(
                "UPDATE violations SET severity = :level "
                "WHERE severity IS NULL AND type_detail = :detail"
            ).bindparams(level=level, detail=detail)
        )
    for family, level in BUILTIN_FAMILY_SEVERITY.items():
        op.execute(
            sa.text(
                "UPDATE violations SET severity = :level "
                "WHERE severity IS NULL AND type::text = :family"
            ).bindparams(level=level, family=family)
        )
    op.execute("UPDATE violations SET severity = 'medium' WHERE severity IS NULL")


def downgrade() -> None:
    op.drop_index("ix_violations_severity", table_name="violations")
    op.drop_column("violations", "severity")
