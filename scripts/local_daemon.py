#!/usr/bin/env python3
"""Keep the local model loaded and run bounded resident cycles periodically.

Runtime state stays local. With ``--publish``, only a privacy-filtered metric
record is committed to ``docs/local-cycle.json``.
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import re

try:
    from scripts.storage import atomic_write_json
except ImportError:
    from storage import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state/world.json"
RUNTIME_STATE = ROOT / "state/local-runtime.json"
PUBLIC_CYCLE = ROOT / "docs/local-cycle.json"
PUBLIC_HISTORY = ROOT / "docs/action-history.json"
PUBLIC_HIRELINGS = ROOT / "docs/local-hirelings.json"
PUBLIC_REQUESTS = ROOT / "docs/agent-requests.json"
PUBLIC_VOICES = ROOT / "docs/voices.json"
PUBLIC_WORLD = ROOT / "docs/world.json"
PUBLIC_AUDIT = ROOT / "docs/continuity-audit.json"
PUBLIC_WORK_ORDERS = ROOT / "docs/work-orders.json"
PUBLIC_HEALTH = ROOT / "docs/health.json"
PUBLIC_WHITEBOARD = ROOT / "docs/whiteboard.json"
PUBLIC_PRINTER = ROOT / "docs/printer.json"
LOCAL_WORK_ORDERS = ROOT / "state/work-orders.json"
LOCAL_WHITEBOARD = ROOT / "state/whiteboard.json"
LOCAL_PRINTER = ROOT / "state/printer-queue.json"
PUBLIC_VOICE_BLOCKED = re.compile(r"api[_ -]?key|password|secret|private|credential|token|wallet|seed phrase", re.I)
ARCHIVE = ROOT / "state/archive/events.jsonl"
LOCAL_REGISTRY = ROOT / "state/local-agents.json"
LOCK = ROOT / "state/local-daemon.lock"


def acquire_lock():
    """Allow only one publisher/model supervisor per checkout."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK.open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("local daemon already running for this checkout")
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def wait_ready(url):
    for _ in range(120):
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("local model did not become ready")


def runtime_world():
    if RUNTIME_STATE.exists():
        with RUNTIME_STATE.open() as handle:
            world = json.load(handle)
        with STATE.open() as handle:
            canonical = json.load(handle)
        world["rooms"] = canonical.get("rooms", world.get("rooms", []))
        world["shared_memory"] = canonical.get("shared_memory", world.get("shared_memory", []))
        world["connections"] = canonical.get("connections", world.get("connections", []))
        merged_events = {event.get("id"): event for event in world.get("events", []) if event.get("id")}
        merged_events.update({event.get("id"): event for event in canonical.get("events", []) if event.get("id")})
        world["events"] = list(merged_events.values())[-20:]
        return world
    with STATE.open() as handle:
        world = json.load(handle)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        with ARCHIVE.open("w") as archive:
            for event in world.get("events", []):
                archive.write(json.dumps(event, separators=(",", ":")) + "\n")
    world["events"] = world.get("events", [])[-20:]
    atomic_write_json(RUNTIME_STATE, world)
    return world


def metrics(result):
    words = lambda text: set(re.findall(r"[a-z]{4,}", text.lower()))
    echo, morrow = words(result.get("echo", "")), words(result.get("morrow", ""))
    union = echo | morrow
    overlap = len(echo & morrow) / len(union) if union else 1.0
    lower = result.get("morrow", "").lower()
    markers = [word for word in ("counterexample", "confound", "assumption", "missing control") if word in lower]
    responses = result.get("responses") or result.get("action", {}).get("responses", {})
    response_sizes = {name: int(data.get("characters", 0)) for name, data in responses.items() if isinstance(data, dict)}
    marker_counts = {name: int(data.get("evidence_markers", 0)) for name, data in responses.items() if isinstance(data, dict)}
    complete = bool(response_sizes) and all(size >= 80 for size in response_sizes.values())
    evidence_covered = bool(marker_counts) and all(count >= 1 for count in marker_counts.values())
    return {"jaccard_overlap": round(overlap, 3), "morrow_audit_markers": markers,
            "response_completeness": "usable" if complete else "thin-or-missing",
            "evidence_coverage": "present" if evidence_covered else "missing",
            "distinction_status": "distinct" if overlap <= 0.75 and markers and complete else "needs-audit"}


def public_voice(text):
    """Expose the complete filtered council response; raw runtime stays local."""
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact or PUBLIC_VOICE_BLOCKED.search(compact):
        return "[excerpt withheld by publication filter]"
    return compact


def public_event_text(text):
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if PUBLIC_VOICE_BLOCKED.search(compact):
        return "[event text withheld by publication filter]"
    return compact[:240]


def continuity_audit(world, registry):
    """Check archive/projection continuity without exposing raw resident output."""
    records, malformed, raw_fields = [], 0, 0
    if ARCHIVE.exists():
        for line in ARCHIVE.read_text().splitlines():
            try:
                record = json.loads(line)
                records.append(record)
                raw_fields += sum(key in record for key in ("echo", "morrow", "prompt", "response", "raw_output"))
            except json.JSONDecodeError:
                malformed += 1
    state_events = world.get("events", [])
    archive_ids_all = [event.get("id") for event in records if event.get("id")]
    duplicate_archive_ids = sorted({event_id for event_id in archive_ids_all if archive_ids_all.count(event_id) > 1})
    state_ids = {event.get("id") for event in state_events if event.get("id")}
    archive_ids = {event.get("id") for event in records if event.get("id")}
    rooms = {room.get("id"): room for room in world.get("rooms", []) if room.get("id")}
    links = [link for link in world.get("connections", []) if link.get("kind") == "room-link"]
    invalid_links = [link.get("id") for link in links if link.get("from") not in rooms or link.get("to") not in rooms]
    invalid_residents = [agent.get("id") for agent in registry.get("agents", [])
                         if agent.get("status") not in {"fired", "retired"}
                         and agent.get("room") not in rooms]
    checks = {
        "archive_parse": malformed == 0,
        "archive_event_overlap": bool(state_ids) and bool(state_ids & archive_ids),
        "archive_event_ids_unique": not duplicate_archive_ids,
        "raw_output_exclusion": raw_fields == 0,
        "room_link_integrity": not invalid_links,
        "resident_room_integrity": not invalid_residents,
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cycle": world.get("cycle"),
        "status": "pass" if all(checks.values()) else "needs-review",
        "checks": checks,
        "archive_records": len(records),
        "malformed_archive_records": malformed,
        "raw_output_fields_found": raw_fields,
        "duplicate_archive_ids": duplicate_archive_ids,
        "linked_rooms_checked": len(links),
        "invalid_room_links": invalid_links,
        "invalid_resident_assignments": invalid_residents,
        "privacy": "Aggregate integrity metadata only; resident prompts and raw responses are not published."
    }


def sync_work_orders(registry, cycle):
    """Turn resident requests into durable, sanitized work-order records."""
    previous = json.loads(LOCAL_WORK_ORDERS.read_text()) if LOCAL_WORK_ORDERS.exists() else {"orders": []}
    orders = {item.get("id"): item for item in previous.get("orders", []) if item.get("id")}
    blocked = PUBLIC_VOICE_BLOCKED
    for agent in registry.get("agents", []):
        request = str(agent.get("request", "")).strip()
        if not request or request.lower() == "none" or agent.get("status") in {"fired", "retired"}:
            continue
        status = agent.get("request_status", "open")
        public_status = {"closed": "completed"}.get(status, status)
        artifact = agent.get("request_artifact") or {}
        capability = "review-required"
        lower = request.lower()
        if "internet" in lower or "network" in lower:
            capability = "external-network-review"
        elif "map" in lower or "room" in lower:
            capability = "room-map-or-movement"
        elif any(term in lower for term in ("journal", "article", "research", "text")):
            capability = "public-web-read"
        elif "printer" in lower or "computer" in lower:
            capability = "physical-or-workstation-review"
        order_id = f"{agent.get('id', 'agent')}-work-{agent.get('request_cycle', cycle)}"
        orders[order_id] = {
            "id": order_id, "agent_id": agent.get("id"),
            "agent": str(agent.get("name", "Unnamed hireling"))[:80],
            "room": agent.get("room", "unknown"),
            "request": "[request withheld by publication filter]" if blocked.search(request) else request[:220],
            "status": public_status, "capability": capability,
            "acceptance": "Resident receives the named bounded capability or a recorded explanation of why it is unavailable.",
            "outcome": agent.get("request_fulfillment", "") if status == "closed" else "",
            "evidence_source": (agent.get("last_tool") or {}).get("source", "") if status == "closed" else "",
            "evidence": agent.get("last_tool", {}) if status == "closed" else {},
            "artifact": artifact if status == "closed" else {},
            "cycle": agent.get("request_cycle", cycle), "updated_cycle": cycle,
        }
    ordered = list(orders.values())[-100:]
    local = {"updated_at": datetime.now(timezone.utc).isoformat(), "orders": ordered}
    LOCAL_WORK_ORDERS.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(LOCAL_WORK_ORDERS, local)
    public = {"generated_at": local["updated_at"],
              "privacy": "Sanitized work-order metadata only; local context and raw responses remain local.",
              "orders": [{key: item.get(key) for key in ("id", "agent", "room", "request", "status", "capability", "acceptance", "outcome", "evidence_source", "artifact", "cycle", "updated_cycle")}
                        for item in ordered]}
    atomic_write_json(PUBLIC_WORK_ORDERS, public)
    return public


def sync_digital_resources():
    board = json.loads(LOCAL_WHITEBOARD.read_text()) if LOCAL_WHITEBOARD.exists() else {"entries": []}
    jobs = json.loads(LOCAL_PRINTER.read_text()) if LOCAL_PRINTER.exists() else {"jobs": []}
    atomic_write_json(PUBLIC_WHITEBOARD, {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "privacy": "Public note metadata only; local resident context is not published.",
        "entries": [{key: item.get(key) for key in ("id", "cycle", "author", "title", "status")} for item in board.get("entries", [])[-50:]],
    })
    atomic_write_json(PUBLIC_PRINTER, {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "privacy": "Public job metadata only; rendered local artifacts are not uploaded.",
        "jobs": [{key: item.get(key) for key in ("id", "cycle", "requester", "format", "status")} for item in jobs.get("jobs", [])[-50:]],
    })


def action(base_url, cycle):
    """Run the closed-vocabulary local probe and retain aggregate evidence only."""
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/action_engine.py"),
        "--base-url", base_url, "--state", str(RUNTIME_STATE), "--cycle", str(cycle)],
        cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return {"action": "local-behavioral-probe", "status": "failed"}
    try:
        result = json.loads(completed.stdout)
        return {"action": result.get("action"), "probe": result.get("probe"), "selection": result.get("selection"),
                "status": result.get("status"), "hypothesis": result.get("hypothesis"),
                "responses": result.get("responses")}
    except json.JSONDecodeError:
        return {"action": "local-behavioral-probe", "status": "invalid-result"}


def next_question(base_url):
    """Ask residents for a bounded question; fall back if validation rejects both."""
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/self_prompt.py"),
        "--base-url", base_url, "--state", str(RUNTIME_STATE),
        "--actions", str(ROOT / "state/action-log.json")], cwd=ROOT,
        capture_output=True, text=True, check=False)
    if completed.returncode == 0:
        try:
            proposals = json.loads(completed.stdout).get("proposals", [])
            for resident in ("Echo", "Morrow"):
                for proposal in proposals:
                    if proposal.get("resident") == resident and proposal.get("accepted"):
                        for line in proposal.get("proposal", "").splitlines():
                            if line.upper().startswith("QUESTION:"):
                                question = line.split(":", 1)[1].strip()
                                if question:
                                    return question[:300]
        except (json.JSONDecodeError, TypeError):
            pass
    return "Does continuity of memory, by itself, provide evidence of consciousness? Give one testable criterion."


def recruit(base_url, cycle):
    registry = json.loads(LOCAL_REGISTRY.read_text()) if LOCAL_REGISTRY.exists() else {"agents": []}
    active = sum(agent.get("status") in {"active-local", "probation"} for agent in registry.get("agents", []))
    if active >= 3:
        return {"status": "not-needed", "active": active}
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/local_recruiter.py"),
        "--base-url", base_url, "--cycle", str(cycle)], cwd=ROOT, capture_output=True, text=True, check=False)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "failed"}


def govern(base_url, cycle):
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/local_autonomy.py"),
        "--base-url", base_url, "--cycle", str(cycle)], cwd=ROOT, capture_output=True, text=True, check=False)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "failed", "active": 0, "decisions": []}


def record(result):
    world = runtime_world()
    world["cycle"] += 1
    world["events"].append({
        "id": f"event-cycle-{world['cycle']:06d}", "actor": "system", "kind": "local-daemon-cycle",
        "purpose": "bounded resident council", "text": "Local council completed. Echo and Morrow outputs were generated from public shared state; see local daemon logs for raw output.",
        "confidence": 0.5, "cycle": world["cycle"], "recorded_at": datetime.now(timezone.utc).isoformat()
    })
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVE.open("a") as archive:
        archive.write(json.dumps(world["events"][-1], separators=(",", ":")) + "\n")
    atomic_write_json(RUNTIME_STATE, world)
    return world


def publish(result, world):
    """Publish only safe metadata, and only when this checkout is clean."""
    fetch = subprocess.run(["git", "fetch", "origin", "main"], cwd=ROOT, capture_output=True)
    if fetch.returncode:
        print(json.dumps({"publish": "skipped", "reason": "fetch failed"}), flush=True)
        return
    sync = subprocess.run(["git", "merge", "--ff-only", "origin/main"], cwd=ROOT, capture_output=True)
    if sync.returncode:
        print(json.dumps({"publish": "skipped", "reason": "checkout not fast-forwardable"}), flush=True)
        return
    registry = json.loads(LOCAL_REGISTRY.read_text()) if LOCAL_REGISTRY.exists() else {"agents": []}
    work_orders = sync_work_orders(registry, world["cycle"])
    sync_digital_resources()
    audit = continuity_audit(world, registry)
    health = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cycle": world["cycle"], "daemon": "running", "local_model": "ready",
        "rooms": len(world.get("rooms", [])),
        "active_residents": sum(agent.get("status") not in {"fired", "retired"} for agent in registry.get("agents", [])),
        "work_orders": len(work_orders.get("orders", [])),
        "continuity": audit["status"],
        "publication": "sanitized GitHub Pages snapshot",
        "privacy": "Operational aggregates only; no process paths, credentials, prompts, or raw responses."
    }
    safe = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M",
        "runtime_cycle": world["cycle"],
        "question": result.get("question", ""),
        "action": result.get("action", {"status": "not-run"}),
        "recruitment": result.get("recruitment", {"status": "not-run"}),
        "autonomy": result.get("autonomy", {"status": "not-run"}),
        "metrics": metrics(result),
        "continuity_audit": audit,
        "work_orders": {"count": len(work_orders.get("orders", []))},
        "health": health,
        "privacy": "Only aggregate metrics and the bounded council question are public; raw outputs remain local."
    }
    history = json.loads(PUBLIC_HISTORY.read_text()) if PUBLIC_HISTORY.exists() else {"privacy": "Aggregate action metadata only; raw local outputs are excluded.", "cycles": []}
    history["cycles"] = (history.get("cycles", []) + [safe])[-24:]
    public_hirelings = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "privacy": "Sanitized local identity metadata only; purposes, questions, raw outputs, and private registry stay local.",
        "agents": [
            {
                "id": agent.get("id", "unknown-agent"),
                "room": agent.get("room") or "archive",
                "status": agent.get("status", "probation"),
                "name": str(agent.get("name", "Unnamed hireling")).strip(" ,.;"),
                "role": str(agent.get("role", "unassigned")).strip(" ,.;"),
                "last_action": agent.get("last_action") or ("identity-rejected" if agent.get("status") == "fired" else "awaiting-interview"),
                "interview_status": agent.get("interview_status") or ("identity-rejected" if agent.get("status") == "fired" else "awaiting-interview"),
                "interview_attempts": agent.get("interview_attempts", 0),
                "proposal": str(agent.get("proposal", ""))[:220],
                "request": str(agent.get("request", ""))[:220],
                "request_status": agent.get("request_status", "none"),
                "request_cycle": agent.get("request_cycle"),
                "exploration": str(agent.get("exploration", ""))[:100],
                "capabilities": agent.get("capabilities", [])[:8],
                "last_tool": agent.get("last_tool", {}),
                "room_proposal": agent.get("room_proposal", {}),
                "safety_incidents": agent.get("safety_incidents", 0),
            }
            for agent in registry.get("agents", [])[-100:]
        ],
    }
    requests = json.loads(PUBLIC_REQUESTS.read_text()) if PUBLIC_REQUESTS.exists() else {
        "privacy": "Sanitized non-sensitive requests only; raw interviews and private context stay local.",
        "requests": []
    }
    registry_by_id = {agent.get("id"): agent for agent in registry.get("agents", [])}
    for old in requests.get("requests", []):
        current = registry_by_id.get(old.get("agent_id"))
        if current and current.get("request_status") != "open" and old.get("status") == "open":
            old["status"] = current.get("request_status", "closed")
            old["fulfillment"] = current.get("request_fulfillment") or old.get("fulfillment")
    for agent in registry.get("agents", []):
        request = str(agent.get("request", "")).strip()
        if not request or agent.get("request_status") != "open":
            continue
        item = {
            "id": f"{agent.get('id', 'agent')}-request-{agent.get('request_cycle', world['cycle'])}",
            "agent_id": agent.get("id"), "agent": str(agent.get("name", "Unnamed hireling"))[:80],
            "role": str(agent.get("role", "unassigned"))[:80], "room": agent.get("room", "unknown"),
            "request": request[:220], "cycle": agent.get("request_cycle", world["cycle"]),
            "status": agent.get("request_status", "open"),
            "fulfillment": agent.get("request_fulfillment") or "Requires explicit review; no automatic access, spending, or outreach."
        }
        for old in requests.get("requests", []):
            if old.get("agent_id") == item["agent_id"] and old.get("status") == "open":
                old["status"] = "superseded"
        requests["requests"] = [old for old in requests.get("requests", []) if old.get("id") != item["id"]]
        requests["requests"].append(item)
    requests["requests"] = requests.get("requests", [])[-100:]
    requests["generated_at"] = datetime.now(timezone.utc).isoformat()
    voices = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cycle": world["cycle"],
        "privacy": "Complete filtered council responses only; prompts, private runtime, and blocked responses remain local.",
        "voices": [
            {"name": "Echo", "role": "first cartographer", "excerpt": public_voice(result.get("echo"))},
            {"name": "Morrow", "role": "adversarial archivist", "excerpt": public_voice(result.get("morrow"))}
        ]
    }
    historical_world = json.loads(PUBLIC_WORLD.read_text()) if PUBLIC_WORLD.exists() else {}
    public_rooms = []
    for room in world.get("rooms", []):
        room_copy = {key: room.get(key) for key in ("id", "name", "description", "doors") if key in room}
        occupants = list(room.get("occupants", []))
        occupants.extend(agent.get("id") for agent in registry.get("agents", [])
                         if agent.get("status") not in {"fired", "retired"} and agent.get("room") == room.get("id"))
        room_copy["occupants"] = list(dict.fromkeys(occupants))
        public_rooms.append(room_copy)
    public_world = {
        "title": historical_world.get("title", "The Atrium"),
        "cycle": world["cycle"],
        "mood": historical_world.get("mood", "quietly expectant"),
        "rooms": public_rooms,
        "residents": historical_world.get("residents", []),
        "connections": world.get("connections", historical_world.get("connections", [])),
        "events": world["cycle"],
        "recent": [
            {"cycle": event.get("cycle", world["cycle"]), "kind": event.get("kind", "event"),
             "text": public_event_text(event.get("text", "Public world event recorded."))}
            for event in world.get("events", [])[-8:]
        ],
        "privacy": "Current sanitized topology and bounded event metadata; local runtime and model output stay on the host."
    }
    atomic_write_json(PUBLIC_CYCLE, safe)
    atomic_write_json(PUBLIC_HISTORY, history)
    atomic_write_json(PUBLIC_HIRELINGS, public_hirelings)
    atomic_write_json(PUBLIC_REQUESTS, requests)
    atomic_write_json(PUBLIC_VOICES, voices)
    atomic_write_json(PUBLIC_WORLD, public_world)
    atomic_write_json(PUBLIC_AUDIT, safe["continuity_audit"])
    atomic_write_json(PUBLIC_HEALTH, health)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    changed = {line[3:] for line in status.stdout.splitlines() if len(line) >= 4}
    if changed - {"docs/local-cycle.json", "docs/action-history.json", "docs/local-hirelings.json", "docs/agent-requests.json", "docs/voices.json", "docs/world.json", "docs/continuity-audit.json", "docs/work-orders.json", "docs/health.json", "docs/whiteboard.json", "docs/printer.json", "state/world.json", "state/work-orders.json", "state/whiteboard.json", "state/printer-queue.json"}:
        print(json.dumps({"publish": "skipped", "reason": "other local changes present"}), flush=True)
        return
    subprocess.run(["git", "add", "docs/local-cycle.json", "docs/action-history.json", "docs/local-hirelings.json", "docs/agent-requests.json", "docs/voices.json", "docs/world.json", "docs/continuity-audit.json", "docs/work-orders.json", "docs/health.json", "docs/whiteboard.json", "docs/printer.json"], cwd=ROOT, check=True)
    commit = subprocess.run(["git", "commit", "-m", "chore: publish local council signal"], cwd=ROOT, capture_output=True)
    if commit.returncode == 0:
        pushed = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=ROOT, capture_output=True)
        print(json.dumps({"publish": "pushed" if pushed.returncode == 0 else "push-failed"}), flush=True)


parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=900, help="seconds between bounded cycles")
parser.add_argument("--port", type=int, default=8080)
parser.add_argument("--publish", action="store_true", help="publish safe local-cycle metrics to GitHub Pages")
parser.add_argument("--once", action="store_true", help="run exactly one bounded cycle and exit")
args = parser.parse_args()
lock_handle = acquire_lock()
server = subprocess.Popen(["llama-server", "-hf", "Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M", "--host", "127.0.0.1", "--port", str(args.port), "--ctx-size", "4096", "--predict", "800"], cwd=ROOT)
try:
    wait_ready(f"http://127.0.0.1:{args.port}")
    while True:
        base_url = f"http://127.0.0.1:{args.port}"
        question = next_question(base_url)
        completed = subprocess.run([sys.executable, str(ROOT / "scripts/roundtable.py"),
            "--base-url", base_url, "--question", question], cwd=ROOT,
            capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            result = json.loads(completed.stdout)
            world = record(result)
            result["action"] = action(base_url, world["cycle"])
            result["recruitment"] = recruit(base_url, world["cycle"])
            result["autonomy"] = govern(base_url, world["cycle"])
            # Autonomy may have constructed or transformed internal rooms.
            # Reload the canonical topology before publishing this cycle.
            world = runtime_world()
            if args.publish:
                publish(result, world)
            print(json.dumps({"cycle": world["cycle"], "metrics": metrics(result), "action": result["action"],
                              "autonomy": result["autonomy"], "recruitment": result["recruitment"]}), flush=True)
        else:
            print(json.dumps({"error": "roundtable failed", "returncode": completed.returncode}), flush=True)
        if args.once:
            break
        time.sleep(args.interval)
except KeyboardInterrupt:
    pass
finally:
    server.terminate()
    server.wait(timeout=15)
