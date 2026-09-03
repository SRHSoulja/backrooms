#!/usr/bin/env python3
"""Run a bounded two-resident council using only shared public state."""

import argparse
import json
import os
import urllib.request
import re
from pathlib import Path

try:
    from scripts.evidence import is_accepted
    from scripts.model_client import complete
except ImportError:
    from evidence import is_accepted
    from model_client import complete

ROOT = Path(__file__).resolve().parents[1]
FINDINGS = ROOT / "state/findings.jsonl"
FRONTIER = ROOT / "state/frontier.json"


def bounded_context(world):
    """Build a small, public-only council context from local ledgers.

    Raw model turns and private resident state never enter this prompt. The
    findings ledger is already sanitized at write time; this projection also
    bounds both ledgers so a busy world cannot crowd out the question.
    """
    findings = []
    if FINDINGS.exists():
        for line in FINDINGS.read_text().splitlines()[-20:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not is_accepted(item):
                continue
            findings.append({**{key: str(item.get(key, ""))[:300] for key in
                                ("topic", "claim", "quote", "url", "confidence", "status")},
                             "room": str((item.get("relates_to") or [""])[0])[:60]})
    frontier = {}
    if FRONTIER.exists():
        try:
            frontier = json.loads(FRONTIER.read_text())
        except json.JSONDecodeError:
            frontier = {}
    questions = [{key: str(item.get(key, ""))[:300] for key in ("id", "question", "status")}
                 for item in frontier.get("open_questions", [])[-6:]
                 if item.get("status") == "open"]
    contradictions = [{key: item.get(key) for key in ("id", "topic", "finding_ids", "reason", "status")}
                      for item in frontier.get("contradictions", [])[-4:]
                      if item.get("status") == "open"]
    leads = [{key: str(item.get(key, ""))[:300] for key in ("question_id", "text", "status")}
             for item in frontier.get("leads", [])[-2:]]
    return {"title": world["title"], "cycle": world["cycle"],
            "shared_memory": world["shared_memory"][-12:], "events": world["events"][-3:],
            "verified_findings": findings[-6:], "frontier_questions": questions,
            "open_contradictions": contradictions, "untrusted_outside_leads": leads}


def ask(base_url, resident, question):
    role = ("Propose one answer and one concrete test. Be constructive and concise."
            if resident == "Echo" else
            "Act as an adversarial archivist. Identify one assumption, counterexample, or missing control. Do not merely repeat the proposal.")
    system = (f"You are {resident}, a resident of the Backrooms. {role} "
              "Use only the public world context supplied below. "
              "Distinguish observation, inference, and uncertainty. "
              "Do not claim sentience or private access. Finish every point and every numbered list; never end mid-sentence.")
    prompt = f"Public world context:\n{question}"
    content, _provider = complete([{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                                  temperature=0.4, max_tokens=800, call_class="council", base_url=base_url)
    return content


def overlap(left, right):
    words = lambda text: set(re.findall(r"[a-z]{4,}", text.lower()))
    a, b = words(left), words(right)
    return len(a & b) / len(a | b) if a | b else 1.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("BACKROOMS_LLM_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--question", default="Does continuity of memory, by itself, provide evidence of consciousness? Give one testable criterion.")
    args = parser.parse_args()
    world = json.loads((ROOT / "state/world.json").read_text())
    context = json.dumps(bounded_context(world), ensure_ascii=False)
    echo = ask(args.base_url, "Echo", context + "\n\nCouncil question: " + args.question)
    morrow = ask(args.base_url, "Morrow", context + "\n\nEcho's position:\n" + echo + "\n\nAudit this position regarding: " + args.question)
    if overlap(echo, morrow) > 0.75 or not any(marker in morrow.lower() for marker in ("counterexample", "confound", "assumption", "missing control")):
        morrow = ask(args.base_url, "Morrow", context + "\n\nEcho's position:\n" + echo +
                     "\n\nYour previous audit converged with Echo. Write a new answer that must begin with 'Counterexample:' and identify a specific way Echo's proposed observation could be misleading. Then add 'Control:' with one safeguard. Do not repeat Echo's conclusion. Question: " + args.question)
    print(json.dumps({"question": args.question, "echo": echo, "morrow": morrow}, indent=2))


if __name__ == "__main__":
    main()
