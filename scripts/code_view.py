#!/usr/bin/env python3
"""Expose a sanitized, read-only view of public project source to residents."""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 120_000
MAX_TOTAL_BYTES = 400_000
ALLOWED_ROOTS = ("scripts", "tests", "docs")
ALLOWED_TOP_LEVEL = {"README.md", "FIELD_LAB.md", "WORLD.md", "OUTBOUND.md", "ARCHIVES.md"}
SENSITIVE = re.compile(r"(?i)(api[_ -]?key|password|secret|credential|private[_ -]?key|seed phrase|mnemonic|bearer\s+[A-Za-z0-9._-]+)")


def allowed(relative):
    path = Path(relative)
    return (not path.is_absolute() and ".." not in path.parts and not path.name.startswith(".")
            and (path.parts[0] in ALLOWED_ROOTS or str(path) in ALLOWED_TOP_LEVEL))


def public_text(path):
    text = path.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
    return "\n".join("[redacted sensitive line]" if SENSITIVE.search(line) else line
                     for line in text.splitlines())[:MAX_FILE_BYTES]


def inventory():
    paths = []
    for root_name in ALLOWED_ROOTS:
        root = ROOT / root_name
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file() and allowed(str(path.relative_to(ROOT))))
    paths.extend(ROOT / name for name in sorted(ALLOWED_TOP_LEVEL) if (ROOT / name).is_file())
    return sorted(paths)


def run(relative=None):
    if relative:
        if not allowed(relative):
            return {"status": "rejected", "reason": "path is outside the public source allowlist"}
        path = ROOT / relative
        if not path.is_file():
            return {"status": "rejected", "reason": "public source file not found"}
        text = public_text(path)
        return {"status": "completed", "file": relative, "bytes": len(text.encode()),
                "sha256": hashlib.sha256(text.encode()).hexdigest(), "content": text,
                "read_only": True, "privacy": "sanitized public source only"}
    files, total = [], 0
    for path in inventory():
        size = min(path.stat().st_size, MAX_FILE_BYTES)
        if total + size > MAX_TOTAL_BYTES:
            continue
        relative_path = str(path.relative_to(ROOT))
        files.append({"file": relative_path, "bytes": size,
                      "sha256": hashlib.sha256(public_text(path).encode()).hexdigest()})
        total += size
    return {"status": "completed", "files": files, "total_bytes": total,
            "read_only": True, "privacy": "sanitized public source inventory only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="one allowlisted public source path")
    parser.add_argument("--list", action="store_true", help="list the allowlisted source inventory")
    args = parser.parse_args()
    print(json.dumps(run(args.file), indent=2))
