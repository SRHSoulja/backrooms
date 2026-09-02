#!/usr/bin/env python3
"""Interview local hirelings and apply only bounded world decisions."""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "state/local-agents.json"
FORBIDDEN = re.compile(r"(api[_ -]?key|password|secret|private memory|credential|token|wallet|funds|shell|sudo)", re.I)
ALLOWED = {"STAY", "MOVE", "EXPLORE", "PROPOSE", "DISCOVER", "BUILD", "TRANSFORM", "RETIRE", "FIRE"}


def ask(url, agent, rooms, cycle):
    prompt = (f"You are interviewing for {agent['name']} ({agent['role']}) in a bounded fictional world. "
              f"Cycle {cycle}. Existing rooms: {', '.join(rooms)}. Choose one action based on your role and current work. "
              "Return exactly five lines: ACTION: STAY|MOVE|EXPLORE|PROPOSE|DISCOVER|BUILD|TRANSFORM|RETIRE|FIRE, ROOM: existing room id or current room, "
              "TARGET: short exploration target, PROPOSAL: short useful proposal, REASON: short reason. "
              "You have no external network, credentials, private memory, arbitrary code, money, or authority to change safety rules. "
              "Do not claim consciousness. Use MOVE only for an existing room.")
    body = json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "messages": [
        {"role": "system", "content": "You are a bounded local hireling interviewer."},
        {"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 180}).encode()
    request = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)["choices"][0]["message"]["content"].strip()


def parse(text, agent, rooms):
    fields = {}
    for line in text.splitlines():
        match = re.match(r"\s*(ACTION|ROOM|TARGET|PROPOSAL|REASON)\s*[:\-]\s*(.*?)\s*$", line, re.I)
        if match:
            fields[match.group(1).upper()] = match.group(2).strip().strip("`*")
    if FORBIDDEN.search(text):
        return None
    action = re.match(r"[A-Z]+", fields.get("ACTION", "").upper().strip())
    action = action.group(0) if action else ""
    room_match = re.search(r"[a-z0-9_-]+", fields.get("ROOM", agent["room"]).lower())
    room = room_match.group(0) if room_match else agent["room"]
    if action not in ALLOWED or room not in rooms:
        return None
    limits = {"TARGET": 100, "PROPOSAL": 220, "REASON": 220}
    if any(len(fields.get(key, "")) > limit for key, limit in limits.items() for _ in [0]):
        return None
    target = fields.get("TARGET", "").strip()
    if action == "EXPLORE" and not target:
        return None
    return {"action": action, "room": room, "target": target,
            "proposal": fields.get("PROPOSAL", "").strip(), "reason": fields.get("REASON", "").strip()}


def deduplicate(registry):
    seen = set()
    for agent in registry.get("agents", []):
        if agent.get("status") not in {"active-local", "probation"}:
            continue
        identity = re.sub(r"[^a-z0-9]", "", str(agent.get("name", "")).lower())
        if identity and identity in seen:
            agent["status"] = "fired"
            agent["last_action"] = "identity-rejected"
            agent["fired_reason"] = "duplicate active identity"
            agent["interviewed_at"] = datetime.now(timezone.utc).isoformat()
        elif identity:
            seen.add(identity)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--cycle", type=int, required=True)
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {"agents": [], "decisions": []}
    deduplicate(registry)
    for agent in registry.get("agents", []):
        if agent.get("status") == "active-local" and not agent.get("interviewed_at"):
            agent["status"] = "probation"
    world = json.loads((ROOT / "state/world.json").read_text())
    rooms = [room["id"] for room in world.get("rooms", []) if room.get("id")]
    results = []
    for agent in registry.get("agents", []):
        if agent.get("status") not in {"active-local", "probation"}:
            continue
        decision = None
        for attempt in range(2):
            try:
                interview = ask(args.base_url, agent, rooms, args.cycle)
                decision = parse(interview, agent, rooms)
                if decision:
                    break
            except Exception:
                pass
        if not decision:
            agent["status"] = "probation"
            agent["interview_status"] = "rejected"
            if "public-web-read" not in agent.get("capabilities", []):
                agent["last_action"] = "interview-rejected"
            agent["interviewed_at"] = datetime.now(timezone.utc).isoformat()
            registry.setdefault("decisions", []).append({"cycle": args.cycle, "agent": agent["id"],
                                                           "action": "interview-rejected"})
            results.append({"id": agent["id"], "status": "interview-rejected"})
            continue
        if decision["action"] == "MOVE":
            agent["room"] = decision["room"]
        elif decision["action"] in {"RETIRE", "FIRE"}:
            agent["status"] = "retired" if decision["action"] == "RETIRE" else "fired"
        elif decision["action"] == "EXPLORE":
            agent["exploration"] = decision["target"] or "unassigned public room question"
            if "public-web-read" not in agent.get("capabilities", []):
                agent.setdefault("capabilities", []).append("public-web-read")
                agent["skill_status"] = "earned-after-interview"
        elif decision["action"] == "PROPOSE":
            agent["proposal"] = decision["proposal"] or "No proposal text supplied."
        elif decision["action"] in {"DISCOVER", "BUILD", "TRANSFORM"}:
            agent["room_proposal"] = {
                "kind": decision["action"].lower(),
                "name": decision["target"][:80],
                "description": decision["proposal"][:220],
                "source_room": agent["room"],
                "status": "construction-requested" if decision["action"] in {"BUILD", "TRANSFORM"} else "discovered",
                "cycle": args.cycle,
            }
        if decision["action"] not in {"RETIRE", "FIRE"}:
            agent["status"] = "active-local"
        agent["interview_status"] = "accepted"
        agent["last_action"] = decision["action"].lower()
        agent["last_reason"] = decision["reason"]
        agent["interviewed_at"] = datetime.now(timezone.utc).isoformat()
        tool = {"status": "not-requested"}
        if decision["action"] == "EXPLORE" and "public-web-read" in agent.get("capabilities", []):
            completed = subprocess.run([sys.executable, str(ROOT / "scripts/tool_broker.py"),
                "wikipedia-search", agent.get("exploration", "")], cwd=ROOT, capture_output=True, text=True, check=False)
            try:
                tool = json.loads(completed.stdout)
            except json.JSONDecodeError:
                tool = {"status": "failed"}
            if tool.get("status") == "completed":
                agent["last_tool"] = {"tool": tool["tool"], "query": tool["query"],
                                       "result_count": len(tool.get("results", [])), "source": tool["source"]}
        registry.setdefault("decisions", []).append({"cycle": args.cycle, "agent": agent["id"], **decision})
        results.append({"id": agent["id"], "action": decision["action"].lower(), "room": agent["room"],
                        "status": agent["status"], "proposal": agent.get("proposal", "")[:220],
                        "exploration": agent.get("exploration", "")[:100], "tool": tool})
    registry["decisions"] = registry.get("decisions", [])[-100:]
    REGISTRY.write_text(json.dumps(registry, indent=2) + "\n")
    active = sum(agent.get("status") in {"active-local", "probation"} for agent in registry.get("agents", []))
    print(json.dumps({"status": "completed", "active": active, "decisions": results}))


if __name__ == "__main__":
    main()
