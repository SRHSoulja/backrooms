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
name, prompt = PROBES[args.cycle % len(PROBES)]
context = json.dumps({"shared_memory": world["shared_memory"], "events": world["events"][-3:]})
responses = {resident: ask(args.base_url, resident, context, prompt) for resident in ("Echo", "Morrow")}
result = {"action": "local-behavioral-probe", "probe": name, "cycle": args.cycle,
          "status": "completed", "responses": {
              resident: {"characters": len(text), "evidence_markers": sum(marker in text.lower() for marker in MARKERS)}
              for resident, text in responses.items()}, "recorded_at": datetime.now(timezone.utc).isoformat()}
print(json.dumps(result))
