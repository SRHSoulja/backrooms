#!/usr/bin/env python3
"""Fast invariant checks for the public Backrooms repository."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []


def load(relative):
    try:
        return json.loads((ROOT / relative).read_text())
    except Exception as exc:
        errors.append(f"{relative}: invalid JSON ({exc})")
        return None


root_card = load(Path(".well-known/agent-card.json"))
pages_card = load(Path("docs/.well-known/agent-card.json"))
fallback_card = load(Path("docs/agent-card.json"))
if root_card and pages_card != root_card:
    errors.append("docs/.well-known/agent-card.json differs from root Agent Card")
if root_card and fallback_card != root_card:
    errors.append("docs/agent-card.json differs from root Agent Card")

site = (ROOT / "docs/index.html").read_text()
if 'href="./.well-known/agent-card.json"' not in site:
    errors.append("docs/index.html must use a project-relative Agent Card link")
if 'href="/.well-known/agent-card.json"' in site:
    errors.append("docs/index.html contains a root-relative Agent Card link")

secret_like = re.compile(r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|BEGIN [A-Z ]+ PRIVATE KEY)")
for path in ROOT.rglob("*"):
    if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
        try:
            if secret_like.search(path.read_text(errors="ignore")):
                errors.append(f"{path.relative_to(ROOT)}: secret-like value found")
        except OSError:
            pass

if errors:
    print("\n".join(f"FAIL: {error}" for error in errors))
    raise SystemExit(1)
print("Backrooms validation: OK")
