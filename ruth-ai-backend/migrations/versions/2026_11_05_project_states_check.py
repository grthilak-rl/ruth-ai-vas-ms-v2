"""Make the projects constraints know the lifecycle states.

- ck_projects_state allowed only 'active' and 'archived', so the first Stop
  (state 'stopping') was rejected by the database and rolled back before
  anything was changed. It now allows every PROJECT_STATES value.
- uq_projects_one_active (unique on state WHERE state = 'active') enforced
  "one current project" only while that project was active: a stopped
  project and a new active one could have coexisted. Replaced by
  uq_projects_one_current: at most one row in any current state.

Both lists must match app.models.project (PROJECT_STATES and
CURRENT_PROJECT_STATES); tests/unit/test_project_lifecycle.py checks the
lists, and tests/integration/test_project_states_schema.py checks a real
migrated database accepts every state.

Revision ID: project_states_check
Revises: project_lifecycle
"""

from alembic import op

revision = "project_states_check"
down_revision = "project_lifecycle"
branch_labels = None
depends_on = None

STATES = ("active", "stopping", "stopped", "resuming", "ended", "archived")
CURRENT_STATES = ("active", "stopping", "stopped", "resuming", "ended")


def _in(states) -> str:
    return "state IN (" + ", ".join(f"'{s}'" for s in states) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_projects_state", "projects", type_="check")
    op.create_check_constraint("ck_projects_state", "projects", _in(STATES))

    op.drop_index("uq_projects_one_active", table_name="projects")
    # A constant expression under a partial index: at most one row may match.
    op.execute(
        "CREATE UNIQUE INDEX uq_projects_one_current ON projects ((true)) "
        f"WHERE {_in(CURRENT_STATES)}"
    )


def downgrade() -> None:
    op.drop_index("uq_projects_one_current", table_name="projects")
    op.execute(
        "CREATE UNIQUE INDEX uq_projects_one_active ON projects (state) WHERE state = 'active'"
    )
    op.drop_constraint("ck_projects_state", "projects", type_="check")
    op.create_check_constraint("ck_projects_state", "projects", _in(("active", "archived")))
