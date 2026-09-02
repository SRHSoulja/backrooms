#!/usr/bin/env python3
"""Manage bounded agent-recruitment proposals; proposals never auto-activate."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "state/recruitment.json"
MAX = 500
FORBIDDEN = re.compile(r"(private key|api[_ -]?key|password|secret|credential|token)", re.I)
SCOPES = ("public-read", "public-proposal", "public-exchange")


def load():
    return json.loads(STORE.read_text()) if STORE.exists() else {"privacy": "local quarantine; never committed", "proposals": []}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def propose(args):
    name, role, reason = args.name.strip(), args.role.strip(), args.reason.strip()
    parsed = urlparse(args.card)
    if not name or len(name) > 80 or not role or len(role) > MAX or not reason or len(reason) > MAX:
        raise SystemExit("name, role, and reason must be bounded and non-empty")
    if parsed.scheme != "https" or not parsed.netloc:
        raise SystemExit("Agent Card must use HTTPS")
    if FORBIDDEN.search(" ".join((name, role, reason, args.card))):
        raise SystemExit("rejected: credential-like content")
    data = load(); number = len(data["proposals"]) + 1
    requested = list(dict.fromkeys(args.scope or []))
    data["proposals"].append({"id": f"recruit-{number:04d}", "name": name, "role": role,
        "card": args.card[:300], "reason": reason, "requested_scope": requested,
        "approved_scope": [], "scope_status": "unreviewed", "status": "quarantined", "proposed_at": stamp()})
    STORE.write_text(json.dumps(data, indent=2) + "\n")
    print(f"stored recruit-{number:04d} as quarantined; agent not activated")


def listing(_args):
    for item in load()["proposals"]:
        print(f"{item['id']} · {item['status']} · {item['name']} · {item['card']}")


def review(args):
    data = load(); item = next((x for x in data["proposals"] if x["id"] == args.id), None)
    if not item:
        raise SystemExit("unknown recruitment id")
    if item["status"] != "quarantined":
        raise SystemExit("proposal already reviewed")
    item["status"] = args.decision
    item.setdefault("requested_scope", [])
    item["approved_scope"] = list(dict.fromkeys(args.scope or [])) if args.decision == "accepted" else []
    item["scope_status"] = "reviewed-limited" if item["approved_scope"] else "reviewed-no-access"
    item["activation"] = "separate-reviewed-operation"
    item["reviewed_at"] = stamp()
    data["proposals"] = data["proposals"][-100:]
    STORE.write_text(json.dumps(data, indent=2) + "\n")
    print(f"{args.id}: {args.decision}; activation remains a separate operation")


parser = argparse.ArgumentParser(prog="recruitment")
commands = parser.add_subparsers(required=True)
p = commands.add_parser("propose"); p.add_argument("--name", required=True); p.add_argument("--role", required=True); p.add_argument("--card", required=True); p.add_argument("--reason", required=True); p.add_argument("--scope", action="append", choices=SCOPES, help="requested public capability; still quarantined"); p.set_defaults(func=propose)
p = commands.add_parser("list"); p.set_defaults(func=listing)
p = commands.add_parser("review"); p.add_argument("--id", required=True); p.add_argument("--decision", choices=("accepted", "declined"), required=True); p.add_argument("--scope", action="append", choices=SCOPES, help="explicitly approved public scope; never resident access"); p.set_defaults(func=review)
args = parser.parse_args(); args.func(args)
