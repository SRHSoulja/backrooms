#!/usr/bin/env python3
"""Bounded note/document filing interface for Echo and Morrow."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "state/core-notes.jsonl"
BLOCKED = re.compile(r"api[_ -]?key|password|secret|private(?: key| memory)?|credential|token|wallet|seed phrase|mnemonic", re.I)

parser = argparse.ArgumentParser()
parser.add_argument("--agent", required=True, choices=("echo", "morrow"))
parser.add_argument("--entry", required=True, help="short non-sensitive record")
parser.add_argument("--kind", choices=("note", "document"), default="note")
parser.add_argument("--title", default="Core resident record")
parser.add_argument("--cycle", type=int, default=None)
args = parser.parse_args()
entry = args.entry.strip()
if not entry or len(entry) > 500 or BLOCKED.search(entry):
    raise SystemExit("record rejected by bounded publication validation")
STORE.parent.mkdir(parents=True, exist_ok=True)
record = {"agent": args.agent, "kind": args.kind, "title": args.title[:120], "entry": entry,
          "cycle": args.cycle, "recorded_at": datetime.now(timezone.utc).isoformat(),
          "content_hash": hashlib.sha256(entry.encode()).hexdigest(), "lifecycle": "filed"}
if args.kind == "document":
    record["document_id"] = f"document-{args.agent}-{int(datetime.now(timezone.utc).timestamp())}"
with STORE.open("a") as handle:
    handle.write(json.dumps(record) + "\n")
print(json.dumps({"tool": "core-resident-records", "status": "completed", "agent": args.agent,
                  "kind": args.kind, "stored": "local-with-sanitized-public-projection"}))
