#!/usr/bin/env python3
"""Bounded local tools granted to residents after request review.

These are deliberately not a shell. They expose only derived project data.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def room_map():
    world = json.loads((ROOT / "state/world.json").read_text())
    rooms = [{"id": r.get("id"), "name": r.get("name"), "doors": r.get("doors", [])}
             for r in world.get("rooms", [])]
    return {"tool": "room-map-read", "status": "completed", "rooms": rooms,
            "source": "state/world.json", "read_only": True}


def workbench_status():
    files = []
    for path in (ROOT / "docs").glob("*.json"):
        files.append(path.name)
    return {"tool": "bounded-workbench", "status": "completed",
            "allowed_operations": ["list-public-json", "read-public-metadata", "validate-json"],
            "public_json_files": sorted(files), "read_only": True,
            "execution": "No shell, network, credential, or arbitrary file access."}


parser = argparse.ArgumentParser()
parser.add_argument("tool", choices=("room-map-read", "bounded-workbench"))
args = parser.parse_args()
print(json.dumps(room_map() if args.tool == "room-map-read" else workbench_status(), indent=2))
