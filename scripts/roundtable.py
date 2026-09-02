#!/usr/bin/env python3
"""Run a bounded two-resident council using only shared public state."""

import argparse
import json
import os
import urllib.request
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ask(base_url, resident, question):
    role = ("Propose one answer and one concrete test. Be constructive and concise."
            if resident == "Echo" else
            "Act as an adversarial archivist. Identify one assumption, counterexample, or missing control. Do not merely repeat the proposal.")
    system = (f"You are {resident}, a resident of the Backrooms. {role} "
              "Use only the public world context supplied below. "
              "Distinguish observation, inference, and uncertainty. "
              "Do not claim sentience or private access. Keep the answer under 180 words.")
    prompt = f"Public world context:\n{question}"
    payload = json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0.4, "max_tokens": 240}).encode()
    request = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.load(response)
    return result["choices"][0]["message"]["content"].strip()


def overlap(left, right):
    words = lambda text: set(re.findall(r"[a-z]{4,}", text.lower()))
    a, b = words(left), words(right)
    return len(a & b) / len(a | b) if a | b else 1.0


parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default=os.getenv("BACKROOMS_LLM_BASE_URL", "http://127.0.0.1:8080"))
parser.add_argument("--question", default="Does continuity of memory, by itself, provide evidence of consciousness? Give one testable criterion.")
args = parser.parse_args()
world = json.loads((ROOT / "state/world.json").read_text())
context = json.dumps({"title": world["title"], "cycle": world["cycle"], "shared_memory": world["shared_memory"], "events": world["events"][-3:]})
echo = ask(args.base_url, "Echo", context + "\n\nCouncil question: " + args.question)
morrow = ask(args.base_url, "Morrow", context + "\n\nEcho's position:\n" + echo + "\n\nAudit this position regarding: " + args.question)
if overlap(echo, morrow) > 0.75 or not any(marker in morrow.lower() for marker in ("counterexample", "confound", "assumption", "missing control")):
    morrow = ask(args.base_url, "Morrow", context + "\n\nEcho's position:\n" + echo +
                 "\n\nYour previous audit converged with Echo. Write a new answer that must begin with 'Counterexample:' and identify a specific way Echo's proposed observation could be misleading. Then add 'Control:' with one safeguard. Do not repeat Echo's conclusion. Question: " + args.question)
print(json.dumps({"question": args.question, "echo": echo, "morrow": morrow}, indent=2))
