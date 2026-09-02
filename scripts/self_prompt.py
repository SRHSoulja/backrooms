#!/usr/bin/env python3
"""Let residents propose bounded next questions from public world evidence."""

import argparse
import json
import os
import re
import urllib.request

FORBIDDEN = re.compile(r"(api[_ -]?key|password|secret|private memory|credential|token)", re.I)


def ask(url, resident, context):
    role = "find a surprising but testable question" if resident == "Echo" else "find the most important unresolved weakness or confound"
    prompt = (f"You are {resident}. From the public context below, {role}. If a recent aggregate hypothesis was weakened, prioritize a reversible follow-up that could distinguish competing explanations. "
              "Return exactly three lines: QUESTION:, WHY:, TEST:. "
              "The test must be reversible, non-sensitive, and require no external contact. "
              "Do not mention credentials or private memory.\n\n" + context)
    body = json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "messages": [
        {"role": "system", "content": "You are a bounded research resident. Do not claim sentience."},
        {"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 150}).encode()
    request = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)["choices"][0]["message"]["content"].strip()


def valid(proposal):
    fields = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
              for line in proposal.splitlines() if ":" in line}
    return (len(proposal) <= 1200 and not FORBIDDEN.search(proposal)
            and all(fields.get(name) for name in ("QUESTION", "WHY", "TEST")))


parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default=os.getenv("BACKROOMS_LLM_BASE_URL", "http://127.0.0.1:8080"))
parser.add_argument("--state", default="state/world.json", help="public JSON state file to inspect")
parser.add_argument("--actions", default="state/action-log.json", help="local aggregate action history")
args = parser.parse_args()
with open(args.state) as state_file:
    world = json.load(state_file)
actions = {"actions": []}
try:
    with open(args.actions) as action_file:
        actions = json.load(action_file)
except FileNotFoundError:
    pass
context = json.dumps({"shared_memory": world["shared_memory"], "events": world["events"][-5:],
                      "recent_aggregate_actions": actions.get("actions", [])[-6:]})
proposals = []
for resident in ("Echo", "Morrow"):
    proposal = ask(args.base_url, resident, context)
    proposals.append({"resident": resident, "accepted": valid(proposal), "proposal": proposal})
print(json.dumps({"proposals": proposals}, indent=2))
