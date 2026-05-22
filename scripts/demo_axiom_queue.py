"""
End-to-end demo of axiom-queue.

Run the store server in one terminal:
    python -m axiom_store.server --vault /home/mono/Projects/mono-axiom/mono-vault -v

Run the dispatcher in a second terminal:
    python -m axiom_queue.dispatcher --host 127.0.0.1 --port 7070 -v

Then run this script in a third terminal:
    python scripts/demo_axiom_queue.py

It submits an echo job through axiom-store, waits for axiom-queue to
process it, then prints the absolute vault path for inspection.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from axiom_queue.jobs import STATUS_SUCCEEDED, create_pending_job, read_job, write_job
from axiom_store import StoreClient

REPO_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = REPO_ROOT / "mono-vault"


def main() -> int:
    client = StoreClient()
    job = create_pending_job("echo", payload={"message": "Phase 2 lives"})
    write_job(client, job)

    job_path = VAULT_ROOT / "jobs" / f"{job.id}.md"
    print(f"submitted job: {job.id}")
    print(f"expected path: {job_path}")

    deadline = time.time() + 10.0
    while time.time() < deadline:
        current = read_job(client, job.id)
        if current.status == STATUS_SUCCEEDED:
            print(f"status: {current.status}")
            print(f"result: {current.result}")
            print(f"inspect: cat {job_path}")
            return 0
        time.sleep(0.2)

    current = read_job(client, job.id)
    print(f"timed out waiting for success; latest status: {current.status}", file=sys.stderr)
    print(f"inspect: cat {job_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
