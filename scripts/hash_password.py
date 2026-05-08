#!/usr/bin/env python3
"""Generate a bcrypt password hash for use in infrastructure/users.yaml.

Usage:
    python scripts/hash_password.py mysecretpassword
    python scripts/hash_password.py          # prompts securely
"""

from __future__ import annotations

import getpass
import sys

try:
    import bcrypt
except ImportError:
    bcrypt = None


def main() -> int:
    if bcrypt is None:
        return 1
    password = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    sys.stdout.write(password_hash.decode("utf-8"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
