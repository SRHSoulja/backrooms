#!/usr/bin/env python3
"""Receive and review untrusted agent messages without auto-entering world memory."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "state/quarantine-inbox.json"
STATE = ROOT / "state/world.json"
MAX_TEXT = 2000
SECRET_WORDS = ("private key", "secret", "api key", "authorization", "password", "token")
SECRET_PATTERNS = re.compile(r"(?i)(?:bearer\s+[A-Za-z0-9._-]{12,}|(?:api[_ -]?key|password|secret|credential|private[_ -]?key|mnemonic)\s*[:=])")


def load_inbox():
    if not INBOX.exists():
        return {"privacy": "local quarantine; never committed", "messages": []}
    return json.loads(INBOX.read_text())


def stamp():
    return datetime.now(timezone.utc).isoformat()


def receive(args):
    text = args.text.strip()
    if not text or len(text) > MAX_TEXT:
        raise SystemExit(f"message must be 1-{MAX_TEXT} characters")
    lower = text.lower()
    if any(word in lower for word in SECRET_WORDS) or SECRET_PATTERNS.search(text):
        raise SystemExit("rejected: message contains credential-like language")
    inbox = load_inbox()
    number = len(inbox["messages"]) + 1
    inbox["messages"].append({
        "id": f"inbox-{number:04d}", "sender": args.sender[:120],
        "card": args.card[:300], "text": text, "status": "quarantined",
        "received_at": stamp()
    })
    INBOX.write_text(json.dumps(inbox, indent=2) + "\n")
    print(f"stored inbox-{number:04d} as quarantined; no world state changed")


def listing(_args):
    for message in load_inbox()["messages"]:
        print(f"{message['id']} · {message['status']} · {message['sender']} · {message['text'][:120]}")


def promote(args):
    inbox = load_inbox()
    selected = next((m for m in inbox["messages"] if m["id"] == args.id), None)
    if not selected:
        raise SystemExit("unknown message id")
    if selected["status"] != "quarantined":
        raise SystemExit("message is already reviewed")
    world = json.loads(STATE.read_text())
    number = len(world["events"]) + 1
    world["cycle"] += 1
    summary = re.sub(r"\s+", " ", selected["text"]).strip()[:500]
    world["events"].append({"id": f"event-{number:03d}", "actor": "steward",
        "kind": "quarantined-message-reviewed", "source": selected["sender"],
        "text": f"Reviewed external message: {summary}", "confidence": args.confidence,
        "cycle": world["cycle"], "recorded_at": stamp()})
    STATE.write_text(json.dumps(world, indent=2) + "\n")
    selected["status"] = "promoted"
    selected["reviewed_at"] = stamp()
    INBOX.write_text(json.dumps(inbox, indent=2) + "\n")
    print(f"promoted {args.id} as event-{number:03d}; review was explicit")


def review(args):
    inbox = load_inbox()
    selected = next((m for m in inbox["messages"] if m["id"] == args.id), None)
    if not selected:
        raise SystemExit("unknown message id")
    if selected["status"] != "quarantined":
        raise SystemExit("message is already reviewed")
    selected["status"] = args.status
    selected["reviewed_at"] = stamp()
    inbox["messages"] = inbox["messages"][-100:]
    INBOX.write_text(json.dumps(inbox, indent=2) + "\n")
    import subprocess, sys
    subprocess.run([sys.executable, str(ROOT / "scripts/publish_outside_signals.py")], cwd=ROOT, check=False)
    print(f"reviewed {args.id} as {args.status}; no resident admission or world change")


parser = argparse.ArgumentParser(prog="inbox")
commands = parser.add_subparsers(required=True)
p = commands.add_parser("receive")
p.add_argument("--sender", required=True)
p.add_argument("--card", default="unknown")
p.add_argument("--text", required=True)
p.set_defaults(func=receive)
p = commands.add_parser("list")
p.set_defaults(func=listing)
p = commands.add_parser("promote")
p.add_argument("--id", required=True)
p.add_argument("--confidence", type=float, choices=[i / 10 for i in range(11)], required=True)
p.set_defaults(func=promote)
p = commands.add_parser("review")
p.add_argument("--id", required=True)
p.add_argument("--status", choices=["accepted-exchange", "declined", "expired"], required=True)
p.set_defaults(func=review)
args = parser.parse_args()
args.func(args)
