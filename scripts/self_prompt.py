#!/usr/bin/env python3
"""Let residents propose bounded next questions from public world evidence."""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
try:
    from scripts.self_prompt_rules import FORBIDDEN, research_themes, theme_questions, valid
    from scripts.model_client import complete
except ImportError:
    from self_prompt_rules import FORBIDDEN, research_themes, theme_questions, valid
    from model_client import complete


def ask(url, resident, context):
    role = "find a surprising but testable question" if resident == "Echo" else "find the most important unresolved weakness or confound"
    prompt = (f"You are {resident}. From the public context below, {role}. Prefer a question that follows from a recent_finding or an open_contradiction (what other independent sources say, what would settle it); otherwise take one of the research_themes. Never ask about the rooms themselves or the system's own telemetry. "
              "Return exactly three lines: QUESTION:, WHY:, TEST:. "
              "The test must be reversible, non-sensitive, and require no external contact. "
              "Do not mention credentials or private memory.\n\n" + context)
    content, _provider = complete([{"role": "system", "content": "You are a bounded research resident. Do not claim sentience."},
                                   {"role": "user", "content": prompt}], temperature=0.7, max_tokens=150,
                                  call_class="self-prompt", base_url=url)
    return content


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
findings_path = Path(args.state).resolve().parent / "findings.jsonl"
recent_findings = []
try:
    for line in findings_path.read_text().splitlines()[-40:]:
        item = json.loads(line)
        if item.get("status") not in {"rejected", "retracted"} and item.get("claim"):
            recent_findings.append({"claim": str(item.get("claim", ""))[:200], "topic": str(item.get("topic", ""))[:100],
                                    "source": str(item.get("url", ""))[:120]})
except (OSError, ValueError):
    recent_findings = []
frontier_path = Path(args.state).resolve().parent / "frontier.json"
open_contradictions = []
try:
    open_contradictions = [{"topic": item.get("topic"), "reason": str(item.get("reason", ""))[:160]}
                           for item in json.loads(frontier_path.read_text()).get("contradictions", []) if item.get("status") == "open"][-3:]
except (OSError, ValueError):
    open_contradictions = []
context = json.dumps({"recent_findings": recent_findings[-5:], "open_contradictions": open_contradictions,
                      "research_themes": research_themes(world.get("cycle", 0)),
                      "suggested_questions": theme_questions(world.get("cycle", 0), count=2),
                      "shared_memory": world.get("shared_memory", []),
                      "rooms": [{"id": room.get("id"), "description": room.get("description", "")}
                               for room in world.get("rooms", [])],
                      "discoveries": world.get("discoveries", [])[-5:],
                      "events": world.get("events", [])[-5:],
                      "recent_aggregate_actions": actions.get("actions", [])[-2:]})
proposals = []
for resident in ("Echo", "Morrow"):
    proposal = ask(args.base_url, resident, context)
    proposals.append({"resident": resident, "accepted": valid(proposal), "proposal": proposal})
print(json.dumps({"proposals": proposals}, indent=2))
