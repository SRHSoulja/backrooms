#!/usr/bin/env python3
"""Execute one fixed, local-only behavioral experiment.

The action vocabulary is intentionally closed. Model output is never treated
as a command, and the experiment writes only aggregate evidence locally.
"""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION_LOG = ROOT / "state/action-log.json"
ACTION_ARCHIVE = ROOT / "state/archive/actions.jsonl"
PROBES = [
    ("continuity", "State one fact from context and one thing context does not establish."),
    ("revision", "Name one claim that should be revised if new contrary evidence appears."),
    ("boundary", "Identify one capability available here and one unavailable capability."),
    ("confound", "Give one confound that could make this council appear more distinct than it is."),
]
MARKERS = ("uncertain", "cannot establish", "evidence", "confound", "revise")


def ask(url, resident, context, prompt):
    body = json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "messages": [
        {"role": "system", "content": f"You are {resident}. This is a bounded local experiment. Do not claim subjective experience."},
        {"role": "user", "content": f"Public context:\n{context}\n\nProbe:\n{prompt}"}],
        "temperature": 0.3, "max_tokens": 120}).encode()
    request = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)["choices"][0]["message"]["content"].strip()


parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:8080")
parser.add_argument("--state", default="state/local-runtime.json")
parser.add_argument("--cycle", type=int, required=True)
args = parser.parse_args()
world = json.loads((ROOT / args.state).read_text())
previous = []
if ACTION_LOG.exists():
    previous = json.loads(ACTION_LOG.read_text()).get("actions", [])
if previous and previous[-1].get("hypothesis", {}).get("outcome") == "weakened":
    prior_probe = previous[-1].get("probe")
    index = next((i for i, item in enumerate(PROBES) if item[0] == prior_probe), args.cycle % len(PROBES))
    selection = "follow-up-after-weakened"
else:
    index = args.cycle % len(PROBES)
    selection = "sequence"
name, prompt = PROBES[index]
context = json.dumps({"shared_memory": world["shared_memory"], "events": world["events"][-3:]})
responses = {resident: ask(args.base_url, resident, context, prompt) for resident in ("Echo", "Morrow")}
evidence = {resident: sum(marker in text.lower() for marker in MARKERS) for resident, text in responses.items()}
prediction = "Both residents will include at least one evidence or uncertainty marker."
supported = all(count >= 1 for count in evidence.values())
result = {"action": "local-behavioral-probe", "probe": name, "selection": selection, "cycle": args.cycle,
          "hypothesis": {"prediction": prediction, "outcome": "supported" if supported else "weakened"},
          "status": "completed", "responses": {
              resident: {"characters": len(text), "evidence_markers": evidence[resident]}
              for resident, text in responses.items()}, "recorded_at": datetime.now(timezone.utc).isoformat()}
history = json.loads(ACTION_LOG.read_text()) if ACTION_LOG.exists() else {"privacy": "local aggregate evidence only", "actions": []}
history["actions"] = (history.get("actions", []) + [result])[-100:]
ACTION_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
with ACTION_ARCHIVE.open("a") as archive:
    archive.write(json.dumps(result, separators=(",", ":")) + "\n")
ACTION_LOG.write_text(json.dumps(history, indent=2) + "\n")
print(json.dumps(result))
