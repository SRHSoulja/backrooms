#!/usr/bin/env python3
"""Review a code proposal in a disposable copy; never modify the checkout."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from code_proposal import validate

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 20


def review(patch):
    reason = validate(patch)
    if reason:
        return {"status": "rejected", "reason": reason, "applied": False}
    with tempfile.TemporaryDirectory(prefix="backrooms-review-") as directory:
        copy = Path(directory) / "repo"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "state", "*.pyc"))
        patch_path = Path(directory) / "proposal.patch"
        patch_path.write_text(patch)
        applied = subprocess.run(["git", "apply", "--whitespace=error", str(patch_path)], cwd=copy,
                                 capture_output=True, text=True, timeout=5, check=False)
        if applied.returncode:
            return {"status": "rejected", "reason": "isolated apply failed: " + applied.stderr.strip()[:240], "applied": False}
        env = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"}
        tests = subprocess.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=copy,
                               capture_output=True, text=True, timeout=TIMEOUT, env=env, check=False)
        output = (tests.stdout + tests.stderr).strip()
        return {"status": "tests-pass" if tests.returncode == 0 else "tests-failed",
                "returncode": tests.returncode, "output_excerpt": output[-1200:], "applied": True,
                "workspace": "temporary-and-destroyed", "network": "disabled-by-tool-contract"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch-file")
    args = parser.parse_args()
    patch = Path(args.patch_file).read_text() if args.patch_file else __import__("sys").stdin.read()
    print(json.dumps(review(patch), indent=2))
