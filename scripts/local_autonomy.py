#!/usr/bin/env python3
"""Interview local hirelings and apply only bounded world decisions."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.storage import atomic_write_json
except ImportError:
    from storage import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "state/local-agents.json"
ARCHIVE = ROOT / "state/archive/events.jsonl"
WHITEBOARD = ROOT / "state/whiteboard.json"
PRINTER_QUEUE = ROOT / "state/printer-queue.json"
PRINTED = ROOT / "state/printed"
NOTES = ROOT / "state/agent-notes"
FORBIDDEN = re.compile(r"(api[_ -]?key|password|secret|private memory|credential|token|wallet|funds|shell|sudo)", re.I)
ALLOWED = {"STAY", "MOVE", "EXPLORE", "PROPOSE", "DISCOVER", "BUILD", "TRANSFORM", "RETIRE", "FIRE"}


def ask(url, agent, rooms, cycle, repair=False):
    prompt = (f"You are interviewing for {agent['name']} ({agent['role']}) in a bounded fictional world. "
              f"Cycle {cycle}. Existing rooms: {', '.join(rooms)}. Choose one action based on your role and current work. "
              "Return exactly five lines: ACTION: STAY|MOVE|EXPLORE|PROPOSE|DISCOVER|BUILD|TRANSFORM|RETIRE|FIRE, ROOM: existing room id or current room, "
              "TARGET: short exploration target, PROPOSAL: short useful proposal, REQUEST: one concrete non-sensitive thing you cannot do alone, or NONE, REASON: short reason. "
              "You have no external network, credentials, private memory, arbitrary code, money, or authority to change safety rules. "
              "Do not claim consciousness. Use MOVE only for an existing room. Move when another declared room better fits the work; otherwise stay. "
              + ("Repair the format: emit only the six labeled fields, with one short line per field; use REQUEST: NONE if no request."
                 if repair else "Keep every field short and labeled exactly once."))
    body = json.dumps({"model": os.getenv("BACKROOMS_LLM_MODEL", "local"), "messages": [
        {"role": "system", "content": "You are a bounded local hireling interviewer."},
        {"role": "user", "content": prompt}], "temperature": 0.5, "max_tokens": 240}).encode()
    request = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)["choices"][0]["message"]["content"].strip()


def parse(text, agent, rooms):
    fields = {}
    labels = r"ACTION|ROOM|TARGET|PROPOSAL|REQUEST|REASON"
    matches = re.finditer(rf"(?is)\b({labels})\s*[:\-]\s*(.*?)(?=\b(?:{labels})\s*[:\-]|\Z)", text)
    for match in matches:
        if match:
            fields[match.group(1).upper()] = match.group(2).strip().strip("`*")
    # Models often echo the interviewer’s boundary sentence. Inspect only
    # parsed decision fields so that safe decisions are not rejected merely
    # because the model repeated a forbidden word in an unstructured preface.
    if FORBIDDEN.search(" ".join(fields.values())):
        return None
    action = re.match(r"[A-Z]+", fields.get("ACTION", "").upper().strip())
    action = action.group(0) if action else ""
    room_match = re.search(r"[a-z0-9_-]+", fields.get("ROOM", agent["room"]).lower())
    room = room_match.group(0) if room_match else agent["room"]
    if action not in ALLOWED or room not in rooms:
        return None
    limits = {"TARGET": 100, "PROPOSAL": 220, "REQUEST": 220, "REASON": 220}
    if any(len(fields.get(key, "")) > limit for key, limit in limits.items() for _ in [0]):
        return None
    target = fields.get("TARGET", "").strip()
    if action == "EXPLORE" and not target:
        return None
    request = fields.get("REQUEST", "").strip()
    if re.fullmatch(r"(?:NONE|N/A|NO REQUEST)[\s,.;:!?]*", request, re.I):
        request = ""
    else:
        request = request.rstrip(" ,.;:!?")
    return {"action": action, "room": room, "target": target,
            "proposal": fields.get("PROPOSAL", "").strip(), "request": request,
            "reason": fields.get("REASON", "").strip()}


def deduplicate(registry):
    seen = set()
    for agent in registry.get("agents", []):
        if agent.get("status") not in {"active-local", "probation"}:
            continue
        previous_room = agent.get("room")
        identity = re.sub(r"[^a-z0-9]", "", str(agent.get("name", "")).lower())
        if identity and identity in seen:
            agent["status"] = "fired"
            agent["last_action"] = "identity-rejected"
            agent["fired_reason"] = "duplicate active identity"
            agent["interviewed_at"] = datetime.now(timezone.utc).isoformat()
        elif identity:
            seen.add(identity)


def revoke(agent, capability, reason):
    agent["capabilities"] = [item for item in agent.get("capabilities", []) if item != capability]
    agent["safety_incidents"] = agent.get("safety_incidents", 0) + 1
    agent["last_action"] = "skill-revoked"
    agent["last_reason"] = reason[:220]
    agent["status"] = "probation"


def digital_whiteboard_entry(agent, cycle):
    board = json.loads(WHITEBOARD.read_text()) if WHITEBOARD.exists() else {"entries": []}
    entries = board.setdefault("entries", [])
    entry_id = f"whiteboard-{agent.get('id', 'resident')}-{cycle}"
    if not any(item.get("id") == entry_id for item in entries):
        body = str(agent.get("request", ""))[:220]
        entries.append({"id": entry_id, "cycle": cycle, "author": agent.get("id", "resident"),
                        "title": "Shared workspace note", "body": body,
                        "content_hash": hashlib.sha256(body.encode()).hexdigest(), "status": "available"})
    board["entries"] = entries[-200:]
    atomic_write_json(WHITEBOARD, board)
    return entry_id


def digital_print_job(agent, cycle):
    queue = json.loads(PRINTER_QUEUE.read_text()) if PRINTER_QUEUE.exists() else {"jobs": []}
    jobs = queue.setdefault("jobs", [])
    job_id = f"print-{agent.get('id', 'resident')}-{cycle}"
    if not any(item.get("id") == job_id for item in jobs):
        PRINTED.mkdir(parents=True, exist_ok=True)
        output = PRINTED / f"{job_id}.txt"
        output.write_text(f"BACKROOMS DIGITAL PRINT\nResident: {agent.get('id', 'resident')}\nCycle: {cycle}\nRequest: {str(agent.get('request', ''))[:220]}\n")
        preview = str(agent.get("request", ""))[:220]
        jobs.append({"id": job_id, "cycle": cycle, "requester": agent.get("id", "resident"),
                     "format": "text", "status": "printed", "preview": preview,
                     "content_hash": hashlib.sha256(output.read_bytes()).hexdigest(),
                     "output": f"state/printed/{output.name}"})
    queue["jobs"] = jobs[-200:]
    atomic_write_json(PRINTER_QUEUE, queue)
    return job_id


def file_agent_record(agent, cycle, kind, body, title=""):
    """Keep a bounded local note/document; publication is sanitized by the daemon."""
    text = str(body or "").strip()[:500]
    if not text or FORBIDDEN.search(text):
        return None
    NOTES.mkdir(parents=True, exist_ok=True)
    path = NOTES / f"{agent.get('id', 'resident')}.jsonl"
    previous_documents = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                old = json.loads(line)
            except json.JSONDecodeError:
                continue
            if old.get("kind") == "document" and old.get("document_id"):
                previous_documents.append(old["document_id"])
    with path.open("a") as handle:
        record = {"recorded_at": datetime.now(timezone.utc).isoformat(), "cycle": cycle,
                                 "kind": kind, "title": title[:120] or ("Resident note" if kind == "note" else "Filed document"),
                                 "entry": text, "content_hash": hashlib.sha256(text.encode()).hexdigest()}
        if kind == "document":
            record["document_id"] = f"document-{agent.get('id', 'resident')}-{cycle}"
            record["lifecycle"] = "revision" if previous_documents else "filed"
            if previous_documents:
                record["supersedes"] = previous_documents[-1]
        handle.write(json.dumps(record) + "\n")
    return path.name


def safe_room_id(target, existing):
    base = re.sub(r"[^a-z0-9]+", "-", str(target or "new-room").lower()).strip("-") or "new-room"
    candidate = base[:42]
    suffix = 2
    while candidate in existing:
        candidate = f"{base[:36]}-{suffix}"
        suffix += 1
    return candidate


def emit_event(world, cycle, kind, actor, text, **fields):
    """Append one durable world event and mirror it into the local archive."""
    event = {"id": f"world-event-{cycle}-{len(world.get('events', [])) + 1}",
             "actor": actor, "kind": kind, "text": text[:240], "cycle": cycle,
             "recorded_at": datetime.now(timezone.utc).isoformat(), **fields}
    world.setdefault("events", []).append(event)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVE.open("a") as archive:
        archive.write(json.dumps(event, separators=(",", ":")) + "\n")
    return event


def apply_construction(world, registry, cycle):
    """Materialize only resident proposals that pass the internal-room policy."""
    rooms = world.setdefault("rooms", [])
    connections = world.setdefault("connections", [])
    room_by_id = {room.get("id"): room for room in rooms}
    room_ids = set(room_by_id)
    next_link = 1 + max((int(str(link.get("id", "")).rsplit("-", 1)[-1])
                         for link in connections if link.get("kind") == "room-link"
                         and str(link.get("id", "")).rsplit("-", 1)[-1].isdigit()), default=0)
    changes = []
    for agent in registry.get("agents", []):
        proposal = agent.get("room_proposal") or {}
        if agent.get("status") not in {"active-local", "probation"}:
            continue
        if proposal.get("kind") not in {"build", "transform"} or proposal.get("status") != "construction-requested":
            continue
        if proposal.get("kind") == "transform":
            source = room_by_id.get(proposal.get("source_room"))
            if source and proposal.get("description"):
                source["description"] = str(proposal["description"])[:220]
                proposal["status"] = "transformed"
                proposal["completed_cycle"] = cycle
                emit_event(world, cycle, "room-transformed", agent.get("id", "resident"),
                           f"Resident transformed {source.get('id')} through a validated internal proposal.",
                           room=source.get("id"), proposal_kind="transform")
                changes.append({"agent": agent.get("id"), "action": "transform", "room": source.get("id")})
            continue
        if proposal.get("room_id") or not proposal.get("name"):
            continue
        source = room_by_id.get(proposal.get("source_room"))
        if not source:
            proposal["status"] = "rejected"
            proposal["reason"] = "source room is not declared"
            continue
        room_id = safe_room_id(proposal["name"], room_ids)
        room = {"id": room_id, "name": str(proposal["name"])[:60],
                "description": str(proposal.get("description") or "Resident-built internal room")[:220],
                "doors": [f"{room_id}-gate"], "occupants": []}
        rooms.append(room)
        room_by_id[room_id] = room
        room_ids.add(room_id)
        door = f"{room_id}-gate"
        source.setdefault("doors", []).append(door)
        connections.append({"id": f"room-link-{next_link:03d}", "kind": "room-link",
                            "name": f"{room['name']} Gate", "from": source["id"], "to": room_id,
                            "door": door, "status": "declared", "scope": "internal movement only"})
        next_link += 1
        proposal["room_id"] = room_id
        proposal["status"] = "constructed"
        proposal["completed_cycle"] = cycle
        emit_event(world, cycle, "room-built", agent.get("id", "resident"),
                   f"Resident built {room_id} as a connected internal room.",
                   room=room_id, connected_to=source["id"], proposal_kind="build")
        changes.append({"agent": agent.get("id"), "action": "build", "room": room_id,
                        "connected_to": source["id"]})
    return changes


def resolve_requests(registry, world=None, cycle=None):
    """Fulfill safe internal requests; leave ambiguous external requests explicit."""
    resolutions = []
    known_rooms = {room.get("id") for room in (world or json.loads((ROOT / "state/world.json").read_text())).get("rooms", [])}
    for agent in registry.get("agents", []):
        if agent.get("request_status") != "open":
            continue
        request = str(agent.get("request", "")).lower().replace("-", " ")
        if "quiet workspace" in request and "quiet-workspace" in known_rooms:
            previous_room = agent.get("room")
            agent["room"] = "quiet-workspace"
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Moved to the declared Quiet Workspace through the internal room gate."
            agent["request_artifact"] = {"kind": "movement", "target_room": "quiet-workspace", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "room": "quiet-workspace"})
            if world is not None and previous_room != agent["room"]:
                emit_event(world, cycle, "resident-moved", agent.get("id", "resident"),
                           f"Resident moved from {previous_room} to quiet-workspace to fulfill a request.",
                           from_room=previous_room, to_room=agent["room"])
        elif "relay room" in request:
            previous_room = agent.get("room")
            agent["room"] = "relay"
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Moved to the declared Relay room through the internal room gate."
            agent["request_artifact"] = {"kind": "movement", "target_room": "relay", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "room": "relay"})
            if world is not None and previous_room != agent["room"]:
                emit_event(world, cycle, "resident-moved", agent.get("id", "resident"),
                           f"Resident moved from {previous_room} to relay to fulfill a request.",
                           from_room=previous_room, to_room=agent["room"])
        elif "atrium" in request and any(term in request for term in ("view", "move")) and "atrium" in known_rooms:
            previous_room = agent.get("room")
            agent["room"] = "atrium"
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Moved to the declared Atrium through the internal room gate."
            agent["request_artifact"] = {"kind": "movement", "target_room": "atrium", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "room": "atrium"})
            if world is not None and previous_room != agent["room"]:
                emit_event(world, cycle, "resident-moved", agent.get("id", "resident"),
                           f"Resident moved from {previous_room} to atrium to fulfill a request.",
                           from_room=previous_room, to_room=agent["room"])
        elif "atrium" in request and "map" in request:
            agent.setdefault("capabilities", []).append("room-map-read")
            agent["capabilities"] = list(dict.fromkeys(agent["capabilities"]))
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Granted read-only Atrium topology through the canonical room map."
            agent["request_artifact"] = {"kind": "room-map", "scope": "atrium", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "capability": "room-map-read"})
        elif "facility" in request and "map" in request and "room-map-read" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Canonical room map made available through the connected observatory rooms."
            agent["request_artifact"] = {"kind": "room-map", "scope": "facility", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled"})
        elif ("historical" in request and ("text" in request or "data" in request) or "rare book" in request or "library" in request) and "public-web-read" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Approved public historical-text research access enabled; source pages remain external."
            agent["request_artifact"] = {"kind": "public-research", "source": (agent.get("last_tool") or {}).get("source", ""), "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled"})
        elif "design resources" in request and "public-web-read" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Approved public research access is available through the web-reading broker."
            agent["request_artifact"] = {"kind": "public-research", "source": (agent.get("last_tool") or {}).get("source", ""), "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled"})
        elif any(term in request for term in ("journal", "article", "research")) and "public-web-read" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Approved public research access is available through the read-only web broker."
            agent["request_artifact"] = {"kind": "public-research", "source": (agent.get("last_tool") or {}).get("source", ""), "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled"})
        elif "computer" in request and "bounded-workbench" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Bounded local workbench access is available; arbitrary computer control remains disabled."
            agent["request_artifact"] = {"kind": "bounded-workbench", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled"})
        elif "computer" in request:
            agent["request_status"] = "needs-clarification"
            agent["request_fulfillment"] = "A bounded workbench is not currently provisioned; arbitrary computer control is unavailable."
            agent["request_artifact"] = {"kind": "clarification-needed", "reason": "bounded-workbench-not-provisioned", "accepted": False}
            resolutions.append({"agent": agent.get("id"), "status": "needs-clarification"})
        elif (("data" in request and any(term in request for term in ("source", "feed", "database", "report"))) or "relevant data" in request) and "public-web-read" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Public read-only web research is available through the broker; private, authenticated, and write-enabled databases remain unavailable."
            agent["request_artifact"] = {"kind": "public-research", "scope": "public-only", "source": (agent.get("last_tool") or {}).get("source", ""), "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "scope": "public-only"})
        elif "visualization" in request and "bounded-workbench" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "A bounded local visualization workspace is available for public JSON and resident-approved data; arbitrary software and external database access remain disabled."
            agent["request_artifact"] = {"kind": "bounded-visualization", "scope": "public-json-and-approved-data", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "scope": "public-json-and-approved-data"})
        elif ("encryption" in request or "time anomaly" in request) and "public-web-read" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Public educational and historical research is available; operational cryptographic materials and unverified anomaly claims are excluded."
            agent["request_artifact"] = {"kind": "public-research", "scope": "educational-and-historical-only", "source": (agent.get("last_tool") or {}).get("source", ""), "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "scope": "educational-and-historical-only"})
        elif ("data image" in request or "data images" in request or "high resolution" in request) and "bounded-workbench" in agent.get("capabilities", []):
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Public, non-sensitive image and chart assets are available in the bounded visualization workspace; private or authenticated datasets remain unavailable."
            agent["request_artifact"] = {"kind": "bounded-visualization", "scope": "public-image-and-chart-assets", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "scope": "public-image-and-chart-assets"})
        elif "secure network" in request:
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Bounded loopback and public read-only networking is available; credentials, private network access, and external writes remain disabled."
            agent["request_artifact"] = {"kind": "bounded-network", "scope": "loopback-and-public-read-only", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "scope": "loopback-and-public-read-only"})
        elif any(term in request for term in ("encrypted communication", "encrypted document", "encrypted storage")):
            agent["request_status"] = "needs-clarification"
            agent["request_fulfillment"] = "Educational cryptography and local reviewed documents are available; live private channels, key custody, and secret storage require a specific safe design."
            agent["request_artifact"] = {"kind": "capability-limited", "reason": "live-secret-channel-not-provisioned", "accepted": False}
            resolutions.append({"agent": agent.get("id"), "status": "needs-clarification"})
        elif "whiteboard" in request:
            entry_id = digital_whiteboard_entry(agent, cycle or 0)
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Shared digital whiteboard created; entries persist locally and are bounded to resident notes."
            agent["request_artifact"] = {"kind": "shared-whiteboard", "entry_id": entry_id, "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "artifact": entry_id})
        elif "printer" in request:
            job_id = digital_print_job(agent, cycle or 0)
            agent["request_status"] = "closed"
            agent["request_fulfillment"] = "Digital print job rendered to a local text artifact; no physical printer or external delivery is implied."
            agent["request_artifact"] = {"kind": "digital-printer", "job_id": job_id, "format": "text", "accepted": True}
            resolutions.append({"agent": agent.get("id"), "status": "fulfilled", "artifact": job_id})
        elif "city" in request and "map" in request:
            agent["request_status"] = "needs-clarification"
            agent["request_fulfillment"] = "A city or region must be named before a public map can be selected."
            agent["request_artifact"] = {"kind": "clarification-needed", "accepted": False}
            resolutions.append({"agent": agent.get("id"), "status": "needs-clarification"})
        if resolutions and world is not None and cycle is not None and resolutions[-1].get("agent") == agent.get("id"):
            outcome = resolutions[-1]
            emit_event(world, cycle, "request-resolved", agent.get("id", "resident"),
                       f"Resident request resolved as {outcome.get('status')}.",
                       request_status=outcome.get("status"), request=agent.get("request", "")[:120])
    return resolutions


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
                interview = ask(args.base_url, agent, rooms, args.cycle, repair=attempt == 1)
                decision = parse(interview, agent, rooms)
                if decision:
                    break
            except Exception:
                pass
        if not decision:
            agent["interview_status"] = "awaiting-retry"
            agent["interview_attempts"] = agent.get("interview_attempts", 0) + 1
            agent["last_interview_attempt_at"] = datetime.now(timezone.utc).isoformat()
            if "public-web-read" not in agent.get("capabilities", []):
                agent["status"] = "probation"
            agent["last_action"] = "interview-retry"
            agent["interviewed_at"] = datetime.now(timezone.utc).isoformat()
            registry.setdefault("decisions", []).append({"cycle": args.cycle, "agent": agent["id"],
                                                           "action": "interview-retry"})
            results.append({"id": agent["id"], "status": "awaiting-retry", "attempts": agent["interview_attempts"]})
            continue
        previous_room = agent.get("room")
        if decision["action"] == "MOVE":
            agent["room"] = decision["room"]
            if agent["room"] != previous_room:
                emit_event(world, args.cycle, "resident-moved", agent.get("id", "resident"),
                           f"Resident moved from {previous_room} to {agent['room']} through declared topology.",
                           from_room=previous_room, to_room=agent["room"])
        elif decision["action"] in {"RETIRE", "FIRE"}:
            agent["status"] = "retired" if decision["action"] == "RETIRE" else "fired"
            agent["capabilities"] = ["bounded-questioning"]
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
        file_agent_record(agent, args.cycle, "note", f"Action: {decision['action']}. {decision['reason']}")
        if decision.get("proposal"):
            file_agent_record(agent, args.cycle, "document", decision["proposal"], "Resident proposal")
        if decision.get("request"):
            agent["request"] = decision["request"]
            agent["request_status"] = "open"
            agent["request_cycle"] = args.cycle
            # A new request must not inherit the resolution text of a prior one.
            agent["request_fulfillment"] = ""
            agent["request_artifact"] = {}
        elif decision["action"] not in {"RETIRE", "FIRE"}:
            agent["request_status"] = "closed"
        elif decision.get("action") in {"RETIRE", "FIRE"}:
            agent["request_status"] = "closed"
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
                                       "result_count": len(tool.get("results", [])), "source": tool["source"],
                                       "contract": tool.get("contract", {})}
                emit_event(world, args.cycle, "tool-used", agent.get("id", "resident"),
                           f"Resident used the approved {tool['tool']} capability.",
                           tool=tool["tool"], capability=tool.get("contract", {}).get("capability", "unknown"),
                           result_count=len(tool.get("results", [])))
            elif tool.get("status") == "rejected" and any(marker in tool.get("reason", "") for marker in ("bounded validation", "public HTTPS", "credentials")):
                revoke(agent, "public-web-read", "broker policy rejection: " + tool.get("reason", "unknown"))
                emit_event(world, args.cycle, "tool-rejected", agent.get("id", "resident"),
                           "Resident tool request was rejected and the related capability was revoked.",
                           tool=tool.get("tool", "unknown"), capability="public-web-read")
            elif tool.get("status") != "not-requested":
                emit_event(world, args.cycle, "tool-failed", agent.get("id", "resident"),
                           f"Resident tool attempt ended with status {tool.get('status', 'unknown')}.",
                           tool=tool.get("tool", "unknown"), status=tool.get("status", "unknown"))
        registry.setdefault("decisions", []).append({"cycle": args.cycle, "agent": agent["id"], **decision})
        results.append({"id": agent["id"], "action": decision["action"].lower(), "room": agent["room"],
                        "status": agent["status"], "proposal": agent.get("proposal", "")[:220],
                        "request": agent.get("request", "")[:220],
                        "request_status": agent.get("request_status", "none"),
                        "exploration": agent.get("exploration", "")[:100], "tool": tool})
    construction = apply_construction(world, registry, args.cycle)
    requests = resolve_requests(registry, world, args.cycle)
    if construction:
        registry.setdefault("decisions", []).extend({"cycle": args.cycle, **item} for item in construction)
    registry["decisions"] = registry.get("decisions", [])[-100:]
    atomic_write_json(ROOT / "state/world.json", world)
    atomic_write_json(REGISTRY, registry)
    active = sum(agent.get("status") in {"active-local", "probation"} for agent in registry.get("agents", []))
    print(json.dumps({"status": "completed", "active": active, "decisions": results,
                      "construction": construction, "requests": requests}))


if __name__ == "__main__":
    main()
