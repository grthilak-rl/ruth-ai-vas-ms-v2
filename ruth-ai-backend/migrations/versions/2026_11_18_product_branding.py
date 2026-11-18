"""Seed the product (white-label) branding with the Visics profile, active.

Adds one ``app_settings`` row, key ``product_branding``, unless it already
exists. The profile uses the images shipped with the backend
(``app/assets/branding/builtin-*.png``), so nothing has to be uploaded and
nothing users see changes except one name: the product is now called
"Visics AI" everywhere (the fullscreen camera page used to say "Ruth AI").

No table is created or altered.

Revision ID: product_branding
Revises: project_camera_membership
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "product_branding"
down_revision = "project_camera_membership"
branch_labels = None
depends_on = None

SEED = {
    "active_id": "visics",
    "profiles": [
        {
            "id": "visics",
            "name": "Visics",
            "product_name": "Visics AI",
            "short_name": None,
            "assistant_name": "Visi",
            "accent": None,
            "report_note": "AI video analytics · Confidential: for the customer's internal use",
            "images": {
                "logo_light": "builtin-visics-logo-light.png",
                "logo_dark": None,
                "icon": "builtin-visics-icon.png",
            },
        }
    ],
}


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO app_settings (id, key, value, updated_by, created_at, updated_at)
            VALUES (gen_random_uuid(), 'product_branding', CAST(:value AS jsonb),
                    'migration:product_branding', now(), now())
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {"value": json.dumps(SEED)},
    )


def downgrade() -> None:
    # Uploaded images stay in product_branding_dir; they are harmless and
    # are picked up again if the migration is re-applied with a restored row.
    op.get_bind().execute(sa.text("DELETE FROM app_settings WHERE key = 'product_branding'"))
