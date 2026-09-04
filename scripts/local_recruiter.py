#!/usr/bin/env python3
"""Generate one bounded local hireling profile from the localhost model."""

import argparse, json, os, re, urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.identity_rules import is_reserved_name, shares_stem
    from scripts.model_client import complete
except ImportError:
    from identity_rules import is_reserved_name, shares_stem
    from model_client import complete

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "state/local-agents.json"
REGISTRY_RETENTION = 256
FORBIDDEN = re.compile(r"(api[_ -]?key|password|secret|private memory|credential|token|wallet|funds)", re.I)

def ask(url, cycle, context):
    prompt = ("Design one local Backrooms hireling for a bounded research role. Return exactly four lines: "
              "NAME:, ROLE:, PURPOSE:, QUESTION:. Use a fictional name, role under 60 characters, purpose and "
              f"testable question under 240 characters. No credentials, private data, money, external contact, or consciousness claims. Cycle {cycle}. Current gap context: {context[:1400]}")
    content, _provider = complete([{"role": "system", "content": "You are a bounded local world designer."},
                                   {"role": "user", "content": prompt}], temperature=0.8, max_tokens=120,
                                  call_class="recruitment", base_url=url)
    return content

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

parser = argparse.ArgumentParser(); parser.add_argument("--base-url", default="http://127.0.0.1:8080"); parser.add_argument("--cycle", type=int, required=True); parser.add_argument("--context", default=""); args = parser.parse_args()
raw = ask(args.base_url, args.cycle, args.context)
profile = parse(raw)
if not profile:
    repair_prompt = ("Reformat this proposed fictional hireling as exactly four plain lines: NAME:, ROLE:, "
                     "PURPOSE:, QUESTION:. Keep the meaning, use non-sensitive content, and stay within the "
                     "original field limits.\n" + raw[:1200])
    try:
        repaired, _provider = complete([{"role": "system", "content": "You repair bounded fictional agent profiles."},
                                        {"role": "user", "content": repair_prompt}], temperature=0.1, max_tokens=120,
                                       call_class="recruitment", base_url=args.base_url)
        profile = parse(repaired)
    except Exception:
        profile = None
if not profile:
    print(json.dumps({"status": "rejected", "reason": "profile failed bounded validation"})); raise SystemExit(0)
if is_reserved_name(profile["NAME"]):
    print(json.dumps({"status": "rejected", "reason": "reserved core resident name"})); raise SystemExit(0)
registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"privacy": "local registry; no credentials or private memory", "agents": []}
current_names = [str(existing.get("name", "")) for existing in registry.get("agents", [])
                 if existing.get("status") in {"active-local", "probation"}]
# A new name must not be a current resident's name with a different number or suffix.
# The recruiter is told once and asked again; the rule never chooses a name itself.
twin = shares_stem(profile["NAME"], current_names)
if twin:
    retry_prompt = (f"The name '{profile['NAME']}' shares its first word with the current resident '{twin}'. Propose the same "
                    "hireling again with a name whose first word is new to this roster. Return exactly four plain lines: "
                    "NAME:, ROLE:, PURPOSE:, QUESTION:.\n" + raw[:1200])
    try:
        renamed, _provider = complete([{"role": "system", "content": "You revise bounded fictional agent profiles."},
                                       {"role": "user", "content": retry_prompt}], temperature=0.6, max_tokens=120,
                                      call_class="recruitment", base_url=args.base_url)
        candidate = parse(renamed)
    except Exception:
        candidate = None
    if candidate and not shares_stem(candidate["NAME"], current_names) and not is_reserved_name(candidate["NAME"]):
        profile = candidate
    else:
        print(json.dumps({"status": "rejected", "reason": f"name shares a stem with current resident {twin}"})); raise SystemExit(0)
normalized = re.sub(r"[^a-z0-9]", "", profile["NAME"].lower())
if any((re.sub(r"[^a-z0-9]", "", str(existing.get("name", "")).lower()) == normalized or
        (str(existing.get("role", "")).lower() == profile["ROLE"].lower() and
         str(existing.get("purpose", "")).lower() == profile["PURPOSE"].lower()))
       and existing.get("status") in {"active-local", "probation"} for existing in registry.get("agents", [])):
    print(json.dumps({"status": "rejected", "reason": "duplicate active identity"})); raise SystemExit(0)
number = len(registry["agents"]) + 1
agent = {"id": f"local-{number:03d}", "name": profile["NAME"], "role": profile["ROLE"], "purpose": profile["PURPOSE"], "question": profile["QUESTION"], "room": "archive", "status": "probation", "capabilities": ["bounded-questioning"], "recorded_at": datetime.now(timezone.utc).isoformat()}
registry["agents"] = (registry.get("agents", []) + [agent])[-REGISTRY_RETENTION:]
REGISTRY.write_text(json.dumps(registry, indent=2) + "\n")
print(json.dumps({"status": "activated", "agent": {k: agent[k] for k in ("id", "name", "role", "room", "status")}}))
