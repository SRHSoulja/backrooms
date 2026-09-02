#!/usr/bin/env python3
"""Project sanitized quarantine lifecycle records immediately."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts.publication import public_text
    from scripts.storage import atomic_write_json
except ImportError:
    from publication import public_text
    from storage import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "state/quarantine-inbox.json"
OUTPUT = ROOT / "docs/outside-signals.json"

local = json.loads(INBOX.read_text()) if INBOX.exists() else {"messages": []}
now = datetime.now(timezone.utc)
changed = False

accepted_ids = {item.get("id") for item in local.get("messages", [])
                if item.get("status") == "accepted-exchange"}


def expire_stale(messages, current_time=None):
    """Expire only unresolved quarantine records older than the review window."""
    current_time = current_time or datetime.now(timezone.utc)
    changed = False
    for item in messages:
        if item.get("status") != "quarantined" or not item.get("received_at"):
            continue
        try:
            received = datetime.fromisoformat(item["received_at"])
        except (TypeError, ValueError):
            continue
        if current_time - received > timedelta(days=30):
            item["status"] = "expired"
            item.setdefault("history", []).append({"status": "expired", "at": current_time.isoformat()})
            item["reviewed_at"] = current_time.isoformat()
            changed = True
    return changed

# Never publish a sender-claimed or legacy phantom parent as verified lineage.
# Keep the raw quarantine record local for audit, but remove the invalid link
# from the public projection.
def verified_parent(item):
    parent = item.get("parent_task_id")
    return parent if parent in accepted_ids else None

changed = expire_stale(local.get("messages", []), now) or changed
if changed:
    atomic_write_json(INBOX, local)
records = [{"id": item.get("id"), "sender": public_text(item.get("sender", "outside-agent")),
            "status": item.get("status", "quarantined"), "task_status": "pending-review" if item.get("status", "quarantined") == "quarantined" else item.get("status", "quarantined"),
            "intake_status": item.get("status", "quarantined"), "text": public_text(item.get("text", ""), 500),
            "received_at": item.get("received_at"), "reviewed_at": item.get("reviewed_at"),
            "parent_task_id": verified_parent(item), "history": item.get("history", [])[-10:]}
           for item in local.get("messages", [])[-100:]]
atomic_write_json(OUTPUT, {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
    "privacy": "Sanitized outside-agent summaries only; no credentials, private memory, or raw messages are published.",
    "records": records})
print(json.dumps({"status": "published", "records": len(records), "output": str(OUTPUT)}))
