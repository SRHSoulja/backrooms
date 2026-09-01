#!/usr/bin/env python3
"""A deliberately small, inspectable steward for the Backrooms."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state/world.json"
TRADES = ROOT / "ledger/trades.json"


def load(path):
    return json.loads(path.read_text())


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def status(_args):
    world = load(STATE)
    print(f"{world['title']} — cycle {world['cycle']} — {world['mood']}")
    print(f"rooms: {len(world['rooms'])} | residents: {', '.join(world['residents'])}")
    print(f"events: {len(world['events'])} | connections: {len(world['connections'])}")


def event(args):
    world = load(STATE)
    number = len(world["events"]) + 1
    world["cycle"] += 1
    world["events"].append({
        "id": f"event-{number:03d}", "actor": args.actor, "kind": args.kind,
        "text": args.text, "cycle": world["cycle"], "recorded_at": stamp()
    })
    save(STATE, world)
    print(f"recorded event-{number:03d} at cycle {world['cycle']}")


def trade(args):
    ledger = load(TRADES)
    number = len(ledger["trades"]) + 1
    ledger["trades"].append({
        "id": f"trade-{number:03d}", "from": args.sender, "to": args.recipient,
        "offering": args.offering, "request": args.request, "status": "proposed",
        "recorded_at": stamp()
    })
    save(TRADES, ledger)
    print(f"recorded trade-{number:03d} as proposed")


def message(args):
    world = load(STATE)
    number = len(world["events"]) + 1
    world["cycle"] += 1
    world["events"].append({
        "id": f"event-{number:03d}", "actor": args.sender, "kind": "message",
        "to": args.recipient, "purpose": args.purpose, "text": args.text,
        "confidence": args.confidence, "reply_requested": args.reply_requested,
        "cycle": world["cycle"], "recorded_at": stamp()
    })
    save(STATE, world)
    print(f"recorded message event-{number:03d} at cycle {world['cycle']}")


parser = argparse.ArgumentParser(prog="backrooms")
commands = parser.add_subparsers(required=True)
p = commands.add_parser("status")
p.set_defaults(func=status)
p = commands.add_parser("event")
p.add_argument("--actor", required=True)
p.add_argument("--kind", required=True)
p.add_argument("--text", required=True)
p.set_defaults(func=event)
p = commands.add_parser("trade")
p.add_argument("--from", dest="sender", required=True)
p.add_argument("--to", dest="recipient", required=True)
p.add_argument("--offering", required=True)
p.add_argument("--request", required=True)
p.set_defaults(func=trade)
p = commands.add_parser("message")
p.add_argument("--from", dest="sender", required=True)
p.add_argument("--to", dest="recipient", required=True)
p.add_argument("--purpose", required=True)
p.add_argument("--text", required=True)
p.add_argument("--confidence", type=float, choices=[i / 10 for i in range(11)], required=True)
p.add_argument("--reply-requested", action="store_true")
p.set_defaults(func=message)
args = parser.parse_args()
args.func(args)
