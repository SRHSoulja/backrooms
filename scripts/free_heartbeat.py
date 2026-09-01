#!/usr/bin/env python3
"""Poll public Agent Cards and write a privacy-filtered observatory heartbeat."""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "backrooms": "https://srhsoulja.github.io/backrooms/.well-known/agent-card.json",
    "math-agent": "https://math.a2a-testbed.com/.well-known/agent-card.json",
    "task-runner": "https://tasks.a2a-testbed.com/.well-known/agent-card.json",
}
results = []
for agent_id, url in TARGETS.items():
    entry = {"id": agent_id, "card": url}
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Backrooms-Heartbeat/0.1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            card = json.load(response)
        entry.update({"status": "online", "name": card.get("name"), "version": card.get("version"), "skills": len(card.get("skills", []))})
    except Exception as exc:
        entry.update({"status": "unavailable", "error": type(exc).__name__})
    results.append(entry)
snapshot = {"checked_at": datetime.now(timezone.utc).isoformat(), "privacy": "public card metadata only", "agents": results}
(ROOT / "docs/heartbeat.json").write_text(json.dumps(snapshot, indent=2) + "\n")
print(json.dumps(snapshot, indent=2))
