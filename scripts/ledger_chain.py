#!/usr/bin/env python3
"""Tamper-evident event archive: every appended event carries the hash of the
line before it and its own hash, so the published log can be checked for
contiguity and any later edit is detectable. This is not a proof that no one
influenced a cycle; it is a guarantee that the record shown is the record kept.

Lines written before the chain existed have no hash; they are linked by the
hash of their raw text, so the chain covers the whole file."""

import argparse
import hashlib
import json
import os
from pathlib import Path


def line_hash(event):
    canonical = json.dumps({key: value for key, value in event.items() if key != "hash"}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def raw_hash(line):
    return hashlib.sha256(str(line).strip().encode()).hexdigest()


def _last_line(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        chunk = b""
        while position > 0:
            step = min(4096, position)
            position -= step
            handle.seek(position)
            chunk = handle.read(step) + chunk
            lines = [line for line in chunk.split(b"\n") if line.strip()]
            if len(lines) >= 2 or position == 0:
                return lines[-1].decode("utf-8", "replace") if lines else ""
    return ""


def link_of(line):
    """What the next event must name as ``prev``: the line's stored hash, or the hash of its raw text."""
    if not line.strip():
        return ""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return raw_hash(line)
    return str(event.get("hash") or raw_hash(line)) if isinstance(event, dict) else raw_hash(line)


def append_event(path, event):
    """Append one event with ``prev`` and ``hash`` set; returns the stored event."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = {key: value for key, value in dict(event).items() if key not in ("prev", "hash")}
    stored["prev"] = link_of(_last_line(path))
    stored["hash"] = line_hash(stored)
    with path.open("a") as handle:
        handle.write(json.dumps(stored, separators=(",", ":")) + "\n")
    return stored


def head(path):
    """{"count", "head"}: how many events the archive holds and the link its next event must name."""
    path = Path(path)
    if not path.exists():
        return {"count": 0, "head": ""}
    count = 0
    with path.open() as handle:
        for line in handle:
            if line.strip():
                count += 1
    return {"count": count, "head": link_of(_last_line(path))}


def verify(path):
    """(ok, count, problem): walk the archive and check every link and hash."""
    path = Path(path)
    if not path.exists():
        return True, 0, ""
    previous = ""
    count = 0
    with path.open() as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            count += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return False, count, f"line {number} is not JSON"
            if isinstance(event, dict) and "hash" in event:
                if str(event.get("prev", "")) != previous:
                    return False, count, f"line {number} names a different previous event"
                if line_hash(event) != event["hash"]:
                    return False, count, f"line {number} does not match its own hash"
                previous = event["hash"]
            else:
                previous = raw_hash(line)
    return True, count, ""


def main():
    parser = argparse.ArgumentParser(description="Verify the tamper-evident event archive.")
    parser.add_argument("path", nargs="?", default=str(Path(__file__).resolve().parents[1] / "state/archive/events.jsonl"))
    args = parser.parse_args()
    ok, count, problem = verify(args.path)
    print(json.dumps({"ok": ok, "events": count, "problem": problem, **head(args.path)}))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
