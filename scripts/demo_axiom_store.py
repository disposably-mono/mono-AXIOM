"""
End-to-end demo of axiom-store.

Run the server in one terminal:
    python -m axiom_store.server --vault /home/mono/Projects/mono-axiom/mono-vault -v

Then run this script in another terminal:
    python scripts/demo_axiom_store.py

It exercises every verb against a live server, asserting the expected
outcomes. The vault on disk gets a 'memory/facts/demo-*.md' set written
and read back; the script cleans up after itself.
"""

from __future__ import annotations

import sys
from datetime import datetime

from axiom_store import (
    InvalidVaultPath,
    SchemaError,
    StoreClient,
)


VALID_FACT_BODY = (
    "---\n"
    "type: fact\n"
    f"created: '{datetime.now().date().isoformat()}'\n"
    "tags:\n"
    "  - demo\n"
    "  - axiom-store\n"
    "---\n"
    "\n"
    "This fact was written by scripts/demo_axiom_store.py.\n"
    "Every byte traveled over loopback TCP to a server you wrote.\n"
).encode("utf-8")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    client = StoreClient()

    section("WRITE — schema-validated fact")
    path = "memory/facts/demo-write.md"
    client.write(path, VALID_FACT_BODY)
    print(f"  wrote {path} ({len(VALID_FACT_BODY)} bytes)")

    section("READ — roundtrip the bytes")
    got = client.read(path)
    assert got == VALID_FACT_BODY, "read did not return what was written"
    print(f"  read {path} ({len(got)} bytes) — bytes match exactly")

    section("LIST — see what's in memory/facts/")
    names = client.list_dir("memory/facts")
    assert path.rsplit("/", 1)[-1] in names, "freshly written file missing from list"
    print(f"  memory/facts/ contains: {names}")

    section("SCHEMA_ERROR — write without required 'created'")
    bad = b"---\ntype: fact\n---\n\nNo created key.\n"
    try:
        client.write("memory/facts/demo-bad.md", bad)
    except SchemaError as e:
        print(f"  expected SchemaError: {e}")
    else:
        print("  UNEXPECTED: schema-invalid write succeeded")
        return 1

    section("BAD_REQUEST — path traversal attempt")
    try:
        client.read("../../../etc/passwd")
    except InvalidVaultPath as e:
        print(f"  expected InvalidVaultPath: {e}")
    else:
        print("  UNEXPECTED: path traversal succeeded")
        return 1

    section("NOT_FOUND — read a missing file")
    try:
        client.read("memory/facts/does-not-exist.md")
    except FileNotFoundError as e:
        print(f"  expected FileNotFoundError: {e}")
    else:
        print("  UNEXPECTED: missing file read succeeded")
        return 1

    section("DELETE — remove the demo file")
    client.delete(path)
    print(f"  deleted {path}")

    section("READ after DELETE — confirm it's gone")
    try:
        client.read(path)
    except FileNotFoundError:
        print(f"  confirmed gone")
    else:
        print("  UNEXPECTED: file still readable after delete")
        return 1

    print("\nAll demo steps passed. The stack works end to end.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
