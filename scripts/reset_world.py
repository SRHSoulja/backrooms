#!/usr/bin/env python3
"""Start the world fresh without losing its history.

Archives every internal ledger into ``state/archive/reset-<stamp>/``, restores
the founding topology with Echo and Morrow, empties the roster and the
evidence ledgers, keeps the cycle counter, the journal, the quarantine inbox
and the outside-agent records, and writes a ``world-reset`` event. It refuses
to run while the daemon holds its lock. ``--dry-run`` only reports.
"""

import argparse
import fcntl
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.storage import atomic_write_json
except ImportError:
    from storage import atomic_write_json

FOUNDING_ROOMS = ("atrium", "relay", "archive", "quiet-workspace")
FOUNDING_OCCUPANTS = {"atrium": ["echo"], "relay": ["morrow"]}
ARCHIVE_ONLY = ("local-agents.json", "findings.jsonl", "corroborations.jsonl", "frontier.json", "trades.json",
                "work-orders.json", "whiteboard.json", "printer-queue.json", "analysis-results.jsonl",
                "core-notes.jsonl", "action-log.json", "provider-usage.json", "recruitment.json",
                "code-proposals.json", "autonomy-errors.log")
ARCHIVE_DIRS = ("printed", "agent-notes", "interviews")
KEEP = ("quarantine-inbox.json", "quarantine-inbox.lock", "codex-inbox", "codex-outbox", "codex-consumed.json",
        "codex-bridge-log.jsonl", "codex-bridge-status.json", "treasury-intents.json", "daemon.log",
        "llama-server.log", "archive")
# Never read, moved, or rewritten by a reset: the reset only edits files under ``state/``.
UNTOUCHED = ("wallet/ (public receiving address and treasury policy, tracked in git)",
             "docs/ (public feeds; the daemon rebuilds them from the fresh state)",
             "journal/ (daily entries, tracked in git)",
             "~/.config/backrooms/ (the vault: wallet private key and the provider key file)",
             "git history")


def daemon_running(root):
    lock = Path(root) / "state/local-daemon.lock"
    if not lock.exists():
        return False
    try:
        with lock.open("a") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True


def founding_world(world, cycle, stamp):
    """The four founding rooms, the two core residents, the bootstrap memories, one reset event."""
    rooms = []
    for room in world.get("rooms", []):
        if room.get("id") not in FOUNDING_ROOMS:
            continue
        rooms.append({"id": room["id"], "name": room.get("name", room["id"]), "description": room.get("description", ""),
                      "charter": room.get("charter") or room.get("description", ""), "doors": list(room.get("doors", [])),
                      "occupants": list(FOUNDING_OCCUPANTS.get(room["id"], [])), "artifacts": [], "board": [],
                      "activity": {"last_cycle": cycle, "score": 0}, "status": "open"})
    founding_ids = {room["id"] for room in rooms}
    connections = [link for link in world.get("connections", [])
                   if link.get("kind") != "room-link" or (link.get("from") in founding_ids and link.get("to") in founding_ids)]
    memories = [item for item in world.get("shared_memory", []) if item.get("source") in {"bootstrap", "world-expansion"}]
    event = {"id": f"event-reset-{stamp}", "actor": "steward", "kind": "world-reset", "cycle": cycle,
             "text": "The world was reset: ledgers archived, founding rooms restored, roster emptied; history kept in the archive.",
             "confidence": 1.0, "recorded_at": datetime.now(timezone.utc).isoformat()}
    return {**{key: world.get(key) for key in ("schema", "world", "title", "mood") if key in world},
            "cycle": cycle, "rooms": rooms, "residents": ["echo", "morrow"], "shared_memory": memories,
            "events": [event], "connections": connections, "discoveries": [], "messages": []}


def reset_world(root, stamp=None, dry_run=False):
    root = Path(root)
    state = root / "state"
    if daemon_running(root):
        raise SystemExit("the daemon holds state/local-daemon.lock; stop the supervisor first")
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = state / "archive" / f"reset-{stamp}"
    plan = {"archive": str(archive.relative_to(root)), "archived": [], "kept": [], "restored": [], "untouched": list(UNTOUCHED)}
    for name in ARCHIVE_ONLY + ARCHIVE_DIRS:
        if (state / name).exists():
            plan["archived"].append(name)
    for name in KEEP:
        if (state / name).exists():
            plan["kept"].append(name)
    runtime = state / "local-runtime.json"
    try:
        cycle = int(json.loads(runtime.read_text()).get("cycle", 0)) if runtime.exists() else 0
    except (ValueError, TypeError):
        cycle = 0
    world_path = state / "world.json"
    world = json.loads(world_path.read_text()) if world_path.exists() else {"rooms": [], "connections": [], "shared_memory": []}
    fresh = founding_world(world, cycle, stamp)
    plan["restored"] = ["state/world.json (founding rooms, Echo and Morrow, bootstrap memories)",
                        "state/local-runtime.json (cycle counter kept: %d)" % cycle, "state/local-agents.json (empty roster)"]
    if dry_run:
        return plan
    archive.mkdir(parents=True, exist_ok=False)
    for name in plan["archived"]:
        shutil.move(str(state / name), str(archive / name))
    shutil.copy2(world_path, archive / "world.json") if world_path.exists() else None
    if runtime.exists():
        shutil.copy2(runtime, archive / "local-runtime.json")
    atomic_write_json(world_path, fresh)
    atomic_write_json(runtime, {**fresh, "events": fresh["events"][-20:]})
    atomic_write_json(state / "local-agents.json", {"privacy": "local registry; no credentials or private memory", "agents": [], "decisions": []})
    (archive / "RESET.md").write_text(
        f"# World reset {stamp}\n\nArchived: {', '.join(plan['archived']) or 'nothing'}.\nKept in place: {', '.join(plan['kept']) or 'nothing'}.\n"
        f"Cycle counter kept at {cycle}. Founding rooms restored with Echo and Morrow.\n"
        f"Never touched: {'; '.join(UNTOUCHED)}.\n")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="perform the reset (otherwise only the plan is printed)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    plan = reset_world(root, dry_run=not args.yes)
    print(json.dumps(plan, indent=2))
    if not args.yes:
        print("dry run only; rerun with --yes to reset", flush=True)


if __name__ == "__main__":
    main()
