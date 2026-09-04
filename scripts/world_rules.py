"""Feedback rules that make the ledgers change what happens next.

Pure functions over ledger rows: a resident's standing, disputes that end in
retractions, room dust and sealing, and the question a finding leaves open.
The autonomy subprocess and the daemon wire them to files; nothing here
touches the network or a model.
"""

import re
from datetime import datetime, timezone

try:
    from scripts.evidence import claim_terms, is_accepted
except ImportError:
    from evidence import claim_terms, is_accepted

DUST_AFTER_CYCLES = 48
SEAL_AFTER_CYCLES = 96
COLLAPSE_AFTER_CYCLES = 96  # a withdrawn room leaves the map after two days and lives on in the withdrawn ledger
FOUNDING_ROOMS = {"atrium", "relay", "archive", "quiet-workspace"}


def _domain(url):
    match = re.match(r"https?://([^/]+)", str(url or ""))
    return match.group(1).lower() if match else ""


def _supported_ids(corroborations):
    supported = set()
    for record in corroborations:
        if record.get("relation") == "supports":
            supported.update(record.get("finding_ids", []))
    return supported


def compute_standing(agent_id, findings, corroborations, tasks=()):
    """Evidence record of one resident, and a score the scheduler can rank by."""
    mine = [item for item in findings if item.get("agent") == agent_id]
    supported = _supported_ids(corroborations)
    accepted = [item for item in mine if is_accepted(item)]
    corroborated = [item for item in accepted if item.get("id") in supported]
    rejected = [item for item in mine if item.get("status") == "rejected"]
    retracted = [item for item in mine if item.get("status") == "retracted"]
    completed = [task for task in tasks if task.get("claimed_by") == agent_id and task.get("status") == "completed"]
    score = 3 * len(corroborated) + 2 * len(accepted) + len(completed) - 0.5 * len(rejected) - 2 * len(retracted)
    return {"accepted": len(accepted), "corroborated": len(corroborated), "rejected": len(rejected),
            "retracted": len(retracted), "tasks_completed": len(completed), "score": round(score, 1),
            "domains": sorted({_domain(item.get("url")) for item in accepted if _domain(item.get("url"))})[:8]}


def settle_disputes(findings, corroborations):
    """Retract the loser of a contradiction when a third source settles it.

    For a judged 'contradicts' pair (A, B), a third accepted finding C from
    another domain that was judged to support one side and contradict the
    other decides the dispute. Returns a list of retractions; the caller
    applies them to the ledger.
    """
    by_id = {item.get("id"): item for item in findings if item.get("id")}
    relations = {}
    for record in corroborations:
        ids = record.get("finding_ids", [])
        if len(ids) == 2:
            relations[frozenset(ids)] = record.get("relation")
    retractions = []
    already = set()
    for record in corroborations:
        if record.get("relation") != "contradicts":
            continue
        pair = record.get("finding_ids", [])
        if len(pair) != 2:
            continue
        first, second = by_id.get(pair[0]), by_id.get(pair[1])
        if not first or not second or not is_accepted(first) or not is_accepted(second):
            continue
        for third in findings:
            identifier = third.get("id")
            if identifier in pair or not is_accepted(third):
                continue
            if _domain(third.get("url")) in {_domain(first.get("url")), _domain(second.get("url"))}:
                continue
            with_first = relations.get(frozenset((identifier, pair[0])))
            with_second = relations.get(frozenset((identifier, pair[1])))
            loser = None
            if with_first == "supports" and with_second == "contradicts":
                loser, winner = second, first
            elif with_second == "supports" and with_first == "contradicts":
                loser, winner = first, second
            if loser is not None:
                if loser.get("id") not in already:
                    already.add(loser.get("id"))
                    retractions.append({"finding_id": loser.get("id"), "kept_id": winner.get("id"), "settled_by": identifier,
                                        "contradiction_id": record.get("id"), "topic": record.get("topic", "")})
                break
    return retractions


def apply_retractions(findings, retractions, cycle):
    """Mark retracted rows in place; a retracted finding stays in the ledger."""
    targets = {item["finding_id"]: item for item in retractions}
    changed = []
    for row in findings:
        entry = targets.get(row.get("id"))
        if entry and is_accepted(row):
            row["status"] = "retracted"
            row["retracted_cycle"] = cycle
            row["retracted_by"] = entry["settled_by"]
            row["retraction_reason"] = "a third independent source supported the competing finding"
            changed.append(row.get("id"))
    return changed


def room_lifecycle(world, findings, cycle):
    """Dust, seal, and reopen grown rooms from their evidence activity; founding rooms never seal."""
    rooms = world.get("rooms", [])
    by_id = {room.get("id"): room for room in rooms if room.get("id")}
    latest_by_room = {}
    for item in findings:
        if not is_accepted(item):
            continue
        for room_id in item.get("relates_to") or []:
            latest_by_room[room_id] = max(latest_by_room.get(room_id, 0), int(item.get("cycle") or 0))
    changes = []
    for room in rooms:
        room_id = room.get("id")
        if room_id in FOUNDING_ROOMS or not room.get("founded_cycle") or room.get("status") == "retracted":
            continue
        activity = room.setdefault("activity", {})
        last = max(int(activity.get("last_cycle") or 0), latest_by_room.get(room_id, 0))
        # A new finding on the room's topic reopens it even if it was sealed.
        topic_terms = claim_terms(room.get("growth_topic", ""))
        if topic_terms:
            for item in findings:
                if is_accepted(item) and int(item.get("cycle") or 0) > last:
                    terms = claim_terms(" ".join((str(item.get("topic", "")), str(item.get("claim", "")))))
                    if terms and len(topic_terms & terms) / len(topic_terms | terms) >= 0.6:
                        last = int(item.get("cycle") or 0)
        activity["last_cycle"] = last
        idle = int(cycle) - last
        previous = room.get("status", "open")
        if idle >= SEAL_AFTER_CYCLES:
            status = "sealed"
        elif idle >= DUST_AFTER_CYCLES:
            status = "dust"
        else:
            status = "open"
        if status != previous:
            room["status"] = status
            room["status_cycle"] = cycle
            changes.append({"room": room_id, "from": previous, "to": status, "idle_cycles": idle})
            if status == "sealed":
                source = next((link.get("from") for link in world.get("connections", [])
                               if link.get("kind") == "room-link" and link.get("to") == room_id), None)
                room["sealed_from"] = source
    return changes


def sealed_room_ids(world):
    return {room.get("id") for room in world.get("rooms", []) if room.get("status") in ("sealed", "retracted")}


def collapse_withdrawn_rooms(world, cycle):
    """Withdrawn rooms leave the map after COLLAPSE_AFTER_CYCLES: the tile and its
    door go, and the full record moves to ``world["withdrawn_rooms"]``, which is
    published. Nothing is deleted; the map shows only what stands or was just
    withdrawn. A new corroborated pair on the same subject founds a new room."""
    kept, collapsed = [], []
    for room in world.get("rooms", []):
        if room.get("status") == "retracted" and int(cycle) - int(room.get("retracted_cycle") or cycle) >= COLLAPSE_AFTER_CYCLES:
            record = {key: room.get(key) for key in ("id", "name", "charter", "founded_by", "founded_via", "founded_cycle",
                                                     "corroboration_id", "growth_topic", "artifacts", "retracted_cycle", "retracted_at", "retraction_reason")}
            record["collapsed_cycle"] = cycle
            record["collapsed_at"] = datetime.now(timezone.utc).isoformat()
            world.setdefault("withdrawn_rooms", []).append(record)
            collapsed.append(room)
        else:
            kept.append(room)
    if not collapsed:
        return []
    gone = {room.get("id") for room in collapsed}
    doors = {f"{room_id}-gate" for room_id in gone}
    world["rooms"] = kept
    for room in kept:
        room["doors"] = [door for door in room.get("doors", []) if door not in doors]
    world["connections"] = [link for link in world.get("connections", [])
                            if not (link.get("kind") == "room-link" and (link.get("from") in gone or link.get("to") in gone))]
    return [{"room": room.get("id"), "reason": room.get("retraction_reason"), "withdrawn_for": int(cycle) - int(room.get("retracted_cycle") or cycle)}
            for room in collapsed]


def retract_unfounded_rooms(world, records_by_id, findings_by_id, cycle, stands):
    """Withdraw grown rooms whose founding pair no longer meets the evidence
    standard. ``stands(record, first, second)`` returns (ok, reason). A
    retracted room stays in the world with its reason; it is never deleted."""
    changes = []
    for room in world.get("rooms", []):
        if room.get("founded_via") != "evidence-ledger" or room.get("status") == "retracted":
            continue
        record = records_by_id.get(room.get("corroboration_id"))
        ids = list((record or {}).get("finding_ids") or room.get("artifacts") or [])
        first = findings_by_id.get(ids[0]) if len(ids) > 0 else None
        second = findings_by_id.get(ids[1]) if len(ids) > 1 else None
        ok, reason = stands(record, first, second)
        if ok:
            continue
        room["status"] = "retracted"
        room["status_cycle"] = cycle
        room["retracted_cycle"] = cycle
        room["retracted_at"] = datetime.now(timezone.utc).isoformat()
        room["retraction_reason"] = reason
        changes.append({"room": room.get("id"), "reason": reason, "corroboration": room.get("corroboration_id")})
    return changes


def finding_followup_question(finding):
    """The question a finding leaves open: what other independent sources say, and whether any disagree."""
    topic = re.sub(r"\s+", " ", str(finding.get("topic", ""))).strip()
    claim = re.sub(r"\s+", " ", str(finding.get("claim", ""))).strip()
    if not topic and not claim:
        return ""
    # The question is built from the claim itself, never from a bag of search terms.
    if claim:
        return (f"Do other independent public sources support or contradict the finding that "
                f"{claim[:200].rstrip('.')}? What would settle it?")
    return ""


def day_zero_from_events(lines):
    """The most recent world reset, from archived event lines: {"cycle", "at"} or None.

    Day zero is the point after which every room and resident must be
    explained by the rules alone; the public page measures the run from it."""
    import json as _json
    found = None
    for line in lines:
        try:
            event = _json.loads(line) if isinstance(line, str) else dict(line)
        except (ValueError, TypeError):
            continue
        if event.get("kind") == "world-reset":
            found = {"cycle": event.get("cycle"), "at": event.get("recorded_at") or event.get("at"), "event": event.get("id")}
    return found
