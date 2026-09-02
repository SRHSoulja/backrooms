#!/usr/bin/env python3
"""Generate one bounded local hireling profile from the localhost model."""

import argparse, json, os, re, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "state/local-agents.json"
REGISTRY_RETENTION = 256
FORBIDDEN = re.compile(r"(api[_ -]?key|password|secret|private memory|credential|token|wallet|funds)", re.I)

def ask(url, cycle):
    prompt = ("Design one local Backrooms hireling for a bounded research role. Return exactly four lines: "
              "NAME:, ROLE:, PURPOSE:, QUESTION:. Use a fictional name, role under 60 characters, purpose and "
              f"testable question under 240 characters. No credentials, private data, money, external contact, or consciousness claims. Cycle {cycle}.")
    body = json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "messages": [
        {"role": "system", "content": "You are a bounded local world designer."}, {"role": "user", "content": prompt}], "temperature": 0.8, "max_tokens": 120}).encode()
    request = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)["choices"][0]["message"]["content"].strip()

def parse(text):
    fields = {}
    labels = r"NAME|ROLE|PURPOSE|QUESTION"
    matches = re.finditer(rf"(?is)\b({labels})\s*[:\-]\s*(.*?)(?=\b(?:{labels})\s*[:\-]|\Z)", text)
    for match in matches:
        fields[match.group(1).upper()] = re.sub(r"[`*_]", "", match.group(2)).strip()
    required = ("NAME", "ROLE", "PURPOSE", "QUESTION")
    limits = {"NAME": 80, "ROLE": 60, "PURPOSE": 240, "QUESTION": 240}
    if any(not fields.get(key) or len(fields[key]) > limit for key, limit in limits.items()) or FORBIDDEN.search(text):
        return None
    fields["NAME"] = fields["NAME"].strip(" ,.;")
    fields["ROLE"] = fields["ROLE"].strip(" ,.;")
    return fields

parser = argparse.ArgumentParser(); parser.add_argument("--base-url", default="http://127.0.0.1:8080"); parser.add_argument("--cycle", type=int, required=True); args = parser.parse_args()
raw = ask(args.base_url, args.cycle)
profile = parse(raw)
if not profile:
    repair_prompt = ("Reformat this proposed fictional hireling as exactly four plain lines: NAME:, ROLE:, "
                     "PURPOSE:, QUESTION:. Keep the meaning, use non-sensitive content, and stay within the "
                     "original field limits.\n" + raw[:1200])
    body = json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "messages": [
        {"role": "system", "content": "You repair bounded fictional agent profiles."},
        {"role": "user", "content": repair_prompt}], "temperature": 0.1, "max_tokens": 120}).encode()
    request = urllib.request.Request(args.base_url.rstrip("/") + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            repaired = json.load(response)["choices"][0]["message"]["content"].strip()
        profile = parse(repaired)
    except Exception:
        profile = None
if not profile:
    print(json.dumps({"status": "rejected", "reason": "profile failed bounded validation"})); raise SystemExit(0)
registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"privacy": "local registry; no credentials or private memory", "agents": []}
normalized = re.sub(r"[^a-z0-9]", "", profile["NAME"].lower())
if any(re.sub(r"[^a-z0-9]", "", str(existing.get("name", "")).lower()) == normalized
       and existing.get("status") in {"active-local", "probation"} for existing in registry.get("agents", [])):
    print(json.dumps({"status": "rejected", "reason": "duplicate active identity"})); raise SystemExit(0)
number = len(registry["agents"]) + 1
agent = {"id": f"local-{number:03d}", "name": profile["NAME"], "role": profile["ROLE"], "purpose": profile["PURPOSE"], "question": profile["QUESTION"], "room": "archive", "status": "probation", "capabilities": ["bounded-questioning"], "recorded_at": datetime.now(timezone.utc).isoformat()}
registry["agents"] = (registry.get("agents", []) + [agent])[-REGISTRY_RETENTION:]
REGISTRY.write_text(json.dumps(registry, indent=2) + "\n")
print(json.dumps({"status": "activated", "agent": {k: agent[k] for k in ("id", "name", "role", "room", "status")}}))
