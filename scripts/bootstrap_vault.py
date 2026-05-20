"""Bootstrap the real /mono-vault/ from /mono-vault.example/.

Run once after cloning the repo. Idempotent — will refuse to overwrite an
existing vault unless --force is passed.

Usage:
    python scripts/bootstrap_vault.py
    python scripts/bootstrap_vault.py --target /custom/path/to/vault
    python scripts/bootstrap_vault.py --force
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = REPO_ROOT / "mono-vault.example"
DEFAULT_TARGET = REPO_ROOT / "mono-vault"


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the Mono-AXIOM vault.")
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Where to create the vault. Defaults to $VAULT_PATH, then ./mono-vault.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing vault. Destructive.",
    )
    args = parser.parse_args()

    target = args.target or Path(os.environ.get("VAULT_PATH", DEFAULT_TARGET))
    target = target.expanduser().resolve()

    if not EXAMPLE_DIR.is_dir():
        print(f"ERROR: example skeleton not found at {EXAMPLE_DIR}", file=sys.stderr)
        return 1

    if target.exists():
        if not args.force:
            print(f"Vault already exists at {target}.")
            print("Pass --force to overwrite (destructive).")
            return 1
        print(f"Removing existing vault at {target}...")
        shutil.rmtree(target)

    print(f"Bootstrapping vault: {EXAMPLE_DIR}  ->  {target}")
    shutil.copytree(EXAMPLE_DIR, target)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
