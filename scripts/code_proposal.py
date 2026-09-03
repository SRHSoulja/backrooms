#!/usr/bin/env python3
"""Validate and archive a resident code proposal without applying it."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "state/code-proposals.json"
MAX_PATCH = 80_000
MAX_CHANGED_LINES = 240
SECRET = re.compile(r"(?i)(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|begin [a-z ]+ private key|api[_ -]?key\s*[:=]|password\s*[:=]|secret\s*[:=]|mnemonic\s*[:=])")
ALLOWED = ("scripts/", "tests/", "docs/")
TOP_LEVEL = {"README.md", "FIELD_LAB.md", "WORLD.md", "OUTBOUND.md", "ARCHIVES.md"}


def paths(patch):
    found = []
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            found.append(line[6:].strip())
    return found


def validate(patch):
    if not patch.strip():
        return "empty patch"
    if len(patch.encode()) > MAX_PATCH:
        return "patch exceeds 80000-byte limit"
    if SECRET.search(patch):
        return "secret-like content detected"
    changed = sum(1 for line in patch.splitlines() if line.startswith(("+", "-"))
                  and not line.startswith(("+++", "---")))
    if changed > MAX_CHANGED_LINES:
        return "patch exceeds changed-line limit"
    targets = paths(patch)
    if not targets:
        return "no target files found"
    for target in targets:
        if target.startswith("/") or ".." in Path(target).parts or target.startswith("."):
            return "path escapes public source allowlist"
        if not (target.startswith(ALLOWED) or target in TOP_LEVEL):
            return f"target is outside public source allowlist: {target}"
    if any(line.startswith("deleted file mode") for line in patch.splitlines()):
        return "file deletion is not allowed"
    with tempfile.NamedTemporaryFile("w", suffix=".patch", dir="/tmp", delete=False) as handle:
        handle.write(patch)
        patch_path = handle.name
    try:
        checked = subprocess.run(["git", "apply", "--check", "--whitespace=error", patch_path],
                                 cwd=ROOT, capture_output=True, text=True, timeout=5, check=False)
        if checked.returncode:
            return "git apply check failed: " + (checked.stderr.strip() or "invalid patch")[:240]
    finally:
        Path(patch_path).unlink(missing_ok=True)
    return ""


def publishable(records, known_residents):
    """Only proposals attributed to a known resident belong in the public feed.

    Test fixtures and ad-hoc tool invocations once leaked into the local ledger
    before test isolation existed; they stay local for audit but are not
    presented as resident work.
    """
    known = {str(item) for item in known_residents}
    return [item for item in records if str(item.get("resident", "")) in known]


def archive(patch, status, reason, resident):
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(ARCHIVE.read_text()) if ARCHIVE.exists() else {"proposals": []}
    item = {"id": "proposal-" + hashlib.sha256(patch.encode()).hexdigest()[:16],
            "resident": resident, "status": status, "reason": reason,
            "files": paths(patch), "changed_lines": sum(1 for line in patch.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))),
            "sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "recorded_at": datetime.now(timezone.utc).isoformat()}
    data["proposals"] = [old for old in data.get("proposals", []) if old.get("id") != item["id"]][-99:] + [item]
    ARCHIVE.write_text(json.dumps(data, indent=2) + "\n")
    return item


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch-file")
    parser.add_argument("--resident", default="unattributed")
    args = parser.parse_args()
    patch = Path(args.patch_file).read_text() if args.patch_file else sys.stdin.read()
    reason = validate(patch)
    item = archive(patch, "ready-for-review" if not reason else "rejected", reason, args.resident)
    print(json.dumps({"status": item["status"], "proposal": item}, indent=2))
