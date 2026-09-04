#!/usr/bin/env python3
"""Let residents propose bounded next questions from public world evidence."""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path
try:
    from scripts.self_prompt_rules import FORBIDDEN, RESIDENT_SOURCES, rejection_reason, valid
    from scripts.model_client import complete
except ImportError:
    from self_prompt_rules import FORBIDDEN, RESIDENT_SOURCES, rejection_reason, valid
    from model_client import complete


def ask(url, resident, context, retry_reason=""):
    role = "find a surprising but testable question" if resident == "Echo" else "find the most important unresolved weakness or confound"
    prompt = (f"You are {resident}. From the public context below, {role}. Prefer a question that follows from a "
              "recent_finding, an open_contradiction, or an open_question (what other independent sources say, what would settle it); "
              "otherwise ask about a real, documented subject in the outside world that a public source could support or refute. "
              "Never ask about this world's own rooms, residents, or telemetry. "
              + (f"Your previous proposal was rejected: {retry_reason}. Propose a different question. " if retry_reason else "") +
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
open_questions = []
try:
    items = json.loads(frontier_path.read_text()).get("open_questions", [])
    own = [item for item in items if item.get("status") == "open" and any(str(item.get("question_source") or "").startswith(p) for p in RESIDENT_SOURCES)]
    open_questions = [{"question": str(item.get("question", ""))[:200], "cycle": item.get("cycle")} for item in (own or [i for i in items if i.get("status") == "open"])[-3:]]
except (OSError, ValueError):
    open_questions = []
# No standing list of topics: the residents see only the world's own record
# (charter, memory, findings, contradictions, their earlier questions).
context = json.dumps({"recent_findings": recent_findings[-5:], "open_contradictions": open_contradictions,
                      "open_questions": open_questions,
                      "shared_memory": world.get("shared_memory", []),
                      "rooms": [{"id": room.get("id"), "description": room.get("description", "")}
                               for room in world.get("rooms", [])],
                      "discoveries": world.get("discoveries", [])[-5:],
                      "events": world.get("events", [])[-5:],
                      "recent_aggregate_actions": actions.get("actions", [])[-2:]})
proposals = []
for resident in ("Echo", "Morrow"):
    proposal = ask(args.base_url, resident, context)
    reason = rejection_reason(proposal)
    attempts = 1
    if reason:
        # Tell the resident why and let it try once more, instead of reaching for a list.
        proposal = ask(args.base_url, resident, context, retry_reason=reason)
        reason = rejection_reason(proposal)
        attempts = 2
    proposals.append({"resident": resident, "accepted": not reason, "proposal": proposal, "attempts": attempts,
                      "rejection_reason": reason})
print(json.dumps({"proposals": proposals}, indent=2))
