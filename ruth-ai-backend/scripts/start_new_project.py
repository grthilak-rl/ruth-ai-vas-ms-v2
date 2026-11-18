#!/usr/bin/env python3
"""Retired: projects are tags now; nothing is archived.

This CLI used to move the current project's rows into the *_archive tables
(and could put an archived batch back). Since the projects_as_tags
migration, every row carries project_id and stays in the live tables; the
one archived project was copied back by that migration, and the archive
tables are kept untouched until a later release drops them.

To end a project and start the next one, use Settings -> Project in the
portal (POST /api/v1/admin/projects/lifecycle/end, then
POST /api/v1/admin/projects/start with the cameras to run).
"""

import sys

if __name__ == "__main__":
    sys.stderr.write(__doc__ or "")
    sys.exit(1)
