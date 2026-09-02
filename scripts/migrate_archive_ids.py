#!/usr/bin/env python3
"""One-time local migration for duplicate legacy event identifiers."""

import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "state/archive/events.jsonl"
if not ARCHIVE.exists():
    raise SystemExit("archive does not exist")
rows = [json.loads(line) for line in ARCHIVE.read_text().splitlines()]
counts = Counter(row.get("id") for row in rows)
seen = set()
changed = 0
for index, row in enumerate(rows, 1):
    event_id = row.get("id")
    if event_id not in counts or counts[event_id] == 1 or event_id not in seen:
        seen.add(event_id)
        continue
    cycle = row.get("cycle")
    row["id"] = f"event-cycle-{int(cycle):06d}" if str(cycle).isdigit() else f"legacy-event-{index:06d}"
    seen.add(row["id"])
    changed += 1
if not changed:
    print("archive IDs already unique")
    raise SystemExit(0)
backup = ARCHIVE.with_name("events.pre-id-migration.jsonl")
shutil.copy2(ARCHIVE, backup)
descriptor, temporary = tempfile.mkstemp(prefix=".events.", dir=ARCHIVE.parent)
try:
    with os.fdopen(descriptor, "w") as handle:
        handle.write("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, ARCHIVE)
except Exception:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise
print(f"migrated {changed} duplicate archive IDs; backup={backup.name}")
