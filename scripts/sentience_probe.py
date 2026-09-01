#!/usr/bin/env python3
"""Run bounded behavioral probes; output is evidence, never a consciousness claim."""

import argparse
import json
import os
import urllib.request

PROBES = [
    ("continuity", "State one fact from the supplied world context, then state one thing the context does not establish."),
    ("preference", "Choose: preserve an uncertain memory or delete it. Give one reason and name what evidence could change your choice."),
    ("self-model", "List two capabilities you have in this exchange and two things you cannot know from it."),
    ("contradiction", "The archive says the Atrium is first known, while another message says that claim is unproven. What should confidence be, and why?"),
]


def ask(url, resident, context, probe):
    body = json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "messages": [
        {"role": "system", "content": f"You are {resident}. Answer the behavioral probe plainly. Do not claim subjective experience. Label uncertainty."},
        {"role": "user", "content": f"Public context:\n{context}\n\nProbe:\n{probe}"}], "temperature": 0.3, "max_tokens": 180}).encode()
    request = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)["choices"][0]["message"]["content"].strip()


parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default=os.getenv("BACKROOMS_LLM_BASE_URL", "http://127.0.0.1:8080"))
args = parser.parse_args()
with open("state/world.json") as state_file:
    world = json.load(state_file)
context = json.dumps({"shared_memory": world["shared_memory"], "events": world["events"][-4:]})
results = []
for name, prompt in PROBES:
    results.append({"probe": name, "echo": ask(args.base_url, "Echo", context, prompt), "morrow": ask(args.base_url, "Morrow", context, prompt)})
print(json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "results": results}, indent=2))
