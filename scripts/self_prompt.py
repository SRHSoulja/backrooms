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


def ask(url, resident, context, retry_reason="", line=None):
    role = "find a surprising but testable question" if resident == "Echo" else "find the most important unresolved weakness or confound"
    if line and line.get("root"):
        known = line.get("known_facts") or []
        steer = (f"The council works one research line at a time. The open line is: '{str(line.get('root', ''))[:240]}' "
                 f"(anchors: {', '.join(line.get('anchors', [])[:6])}; question {line.get('hop', 1)} of {line.get('cap', 3)}). "
                 + (("The world has already established about this subject: " + " | ".join(str(item)[:160] for item in known[:5]) +
                     ". Build on those: ask for the next fact that would extend them, or for a source likely to give a different figure. ") if known else ""))
                 "Propose the next step on this line: what would settle its claim, which independent public source could confirm or refute it. "
                 "If the line has used its questions, or you have a better subject, propose a new line about a different, documented subject "
                 "in the outside world; a new subject waits in a queue until the line closes. ")
    else:
        steer = ("No research line is open. Propose the root question of a new line: a real, documented subject in the outside world "
                 "that two independent public sources could confirm or refute. today_public_events lists sourced events from the public "
                 "record; a question that checks one of them for a second source or a different figure is a strong root. ")
    prompt = (f"You are {resident}. From the public context below, {role}. " + steer +
              "Never ask about this world's own rooms, residents, or telemetry, and never about an individual's account or profile. "
              + (f"Your previous proposal was rejected: {retry_reason}. Propose a different question. " if retry_reason else "") +
              "Return exactly three lines: QUESTION:, WHY:, TEST:. "
              "The test must be reversible, non-sensitive, and require no external contact. "
              "Do not mention credentials or private memory.\n\n" + context)
    content, provider = complete([{"role": "system", "content": "You are a bounded research resident. Do not claim sentience."},
                                  {"role": "user", "content": prompt}], temperature=0.7, max_tokens=150,
                                 call_class="self-prompt", base_url=url, prefer=RESIDENT_PROVIDERS.get(resident))
    LAST_PROVIDER[resident] = provider
    return content


# Adversarial model pairs: each resident prefers a different provider family, so
# the two voices come from different models whenever more than one key exists.
RESIDENT_PROVIDERS = {"Echo": ("gemini", "groq", "cerebras", "openrouter", "mistral"),
                      "Morrow": ("mistral", "mistral-8b", "mistral-small", "cerebras", "groq", "gemini")}
LAST_PROVIDER = {}


parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default=os.getenv("BACKROOMS_LLM_BASE_URL", "http://127.0.0.1:8080"))
parser.add_argument("--state", default="state/world.json", help="public JSON state file to inspect")
parser.add_argument("--actions", default="state/action-log.json", help="local aggregate action history")
parser.add_argument("--line", default="", help="JSON of the open research line (root, anchors, hop, cap), if any")
parser.add_argument("--today", default="", help="JSON list of today's sourced public events (from Wikipedia's current-events portal)")
args = parser.parse_args()
try:
    research_line = json.loads(args.line) if args.line else None
except ValueError:
    research_line = None
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
if research_line and research_line.get("questions"):
    # On an open line the residents see that line's own questions, not the
    # world's whole backlog, so a proposal follows the line rather than an old subject.
    open_questions = [{"question": str(item)[:200]} for item in research_line.get("questions", [])[-3:]]
# No standing list of topics: the residents see only the world's own record
# (charter, memory, findings, contradictions, their earlier questions).
try:
    today_events = json.loads(args.today) if args.today else []
except ValueError:
    today_events = []
context = json.dumps({"research_line": research_line, "today_public_events": today_events[:8],
                      "recent_findings": recent_findings[-5:], "open_contradictions": open_contradictions,
                      "open_questions": open_questions,
                      "shared_memory": world.get("shared_memory", []),
                      "rooms": [{"id": room.get("id"), "description": room.get("description", "")}
                               for room in world.get("rooms", [])],
                      "discoveries": world.get("discoveries", [])[-5:],
                      "events": world.get("events", [])[-5:],
                      "recent_aggregate_actions": actions.get("actions", [])[-2:]})
proposals = []
for resident in ("Echo", "Morrow"):
    proposal = ask(args.base_url, resident, context, line=research_line)
    reason = rejection_reason(proposal)
    attempts = 1
    if reason:
        # Tell the resident why and let it try once more, instead of reaching for a list.
        proposal = ask(args.base_url, resident, context, retry_reason=reason, line=research_line)
        reason = rejection_reason(proposal)
        attempts = 2
    proposals.append({"resident": resident, "accepted": not reason, "proposal": proposal, "attempts": attempts,
                      "rejection_reason": reason, "provider": LAST_PROVIDER.get(resident)})
print(json.dumps({"proposals": proposals}, indent=2))
