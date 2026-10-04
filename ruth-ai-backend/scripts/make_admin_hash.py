#!/usr/bin/env python3
"""Print a bcrypt hash for RUTH_ADMIN_PASSWORD_HASH.

The password is read with getpass (never echoed, never an argument, so it
stays out of shell history and `ps`).

Usage, with the backend image (it has bcrypt installed):
    docker run --rm -it --entrypoint python \
        -v "$PWD/scripts:/scripts:ro" vas-ruthai-deploy-ruth-ai-backend \
        /scripts/make_admin_hash.py

Put the output in the deploy .env inside SINGLE quotes. A bcrypt hash
contains `$`, which docker compose would otherwise try to interpolate:
    RUTH_ADMIN_PASSWORD_HASH='$2b$12$...'
"""

import getpass
import sys

import bcrypt

MIN_LENGTH = 12
MAX_BYTES = 72  # bcrypt ignores anything past 72 bytes; refuse rather than truncate
ROUNDS = 12


def main() -> int:
    password = getpass.getpass("Admin password: ")
    if len(password) < MIN_LENGTH:
        print(f"Refusing: use at least {MIN_LENGTH} characters.", file=sys.stderr)
        return 1
    if len(password.encode("utf-8")) > MAX_BYTES:
        print(f"Refusing: bcrypt only uses the first {MAX_BYTES} bytes.", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=ROUNDS))
    print(hashed.decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
