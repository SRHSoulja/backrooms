#!/usr/bin/env python3
"""Append-only, agent-scoped notes/documents with bounded publication."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "state/agent-notes"
FORBIDDEN = re.compile(r"api[_ -]?key|password|secret|private key|seed phrase|credential|token", re.I)

parser = argparse.ArgumentParser()
parser.add_argument("--agent", required=True, choices=("local-001", "local-002", "local-004"))
parser.add_argument("--entry", required=True, help="short non-sensitive note or document body")
parser.add_argument("--kind", choices=("note", "document"), default="note")
parser.add_argument("--title", default="", help="document title")
args = parser.parse_args()
entry = args.entry.strip()
if not entry or len(entry) > 500 or FORBIDDEN.search(entry):
    raise SystemExit("note rejected by bounded validation")
NOTES.mkdir(parents=True, exist_ok=True)
path = NOTES / f"{args.agent}.jsonl"
with path.open("a") as handle:
    handle.write(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(), "kind": args.kind,
                             "title": args.title[:120] or ("Resident note" if args.kind == "note" else "Filed document"),
                             "entry": entry}) + "\n")
print(json.dumps({"tool": "bounded-notepad", "status": "completed", "agent": args.agent, "kind": args.kind, "stored": "local-with-sanitized-public-projection", "characters": len(entry)}))
