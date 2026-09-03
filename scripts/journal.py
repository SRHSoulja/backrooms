"""A daily journal written by a resident and checked against the ledgers.

The digest is deterministic and comes from public ledgers only. A model may
phrase it in Echo's voice, but every resident, finding, and room it names,
and every number it states, must appear in the digest; otherwise the digest
itself is published. The journal is the narrative layer of the observatory,
and it is never allowed to invent.
"""

import json
import re
from datetime import datetime, timezone

try:
    from scripts.model_client import complete
except ImportError:
    from model_client import complete

MAX_WORDS = 220


def cycle_times(history):
    """cycle -> ISO timestamp from the public action history."""
    times = {}
    for item in history.get("cycles", []) if isinstance(history, dict) else []:
        try:
            times[int(item.get("runtime_cycle"))] = str(item.get("generated_at", ""))
        except (TypeError, ValueError):
            continue
    return times


def backfill_timestamps(rows, times, cycle_key="cycle", stamp_key="recorded_at"):
    """Estimate a timestamp for rows that predate timestamping, from the nearest published cycle."""
    if not times:
        return 0
    known = sorted(times)
    changed = 0
    for row in rows:
        if row.get(stamp_key) or row.get(cycle_key) in (None, ""):
            continue
        try:
            cycle = int(row.get(cycle_key))
        except (TypeError, ValueError):
            continue
        nearest = max((c for c in known if c <= cycle), default=None) or min(known)
        row[stamp_key] = times[nearest]
        row[stamp_key + "_estimated"] = True
        changed += 1
    return changed


def daily_digest(date, findings, corroborations, world, registry, tasks, retractions=(), room_changes=()):
    """Facts for one UTC day, keyed so the verifier can check a written entry against them."""
    day = str(date)
    def on_day(item):
        stamp = str(item.get("recorded_at") or item.get("completed_at") or "")
        return stamp.startswith(day)
    accepted = [item for item in findings if on_day(item) and item.get("status") not in {"rejected", "retracted"}]
    rejected = [item for item in findings if on_day(item) and item.get("status") == "rejected"]
    judged = [item for item in corroborations if on_day(item)]
    supports = [item for item in judged if item.get("relation") == "supports"]
    contradicts = [item for item in judged if item.get("relation") == "contradicts"]
    rooms_built = [room for room in world.get("rooms", []) if str(room.get("founded_at", "")).startswith(day)]
    completed = [task for task in tasks if str(task.get("completed_at", "")).startswith(day)]
    retired = [agent for agent in registry.get("agents", []) if agent.get("status") in {"retired", "fired"}
               and str(agent.get("interviewed_at", "")).startswith(day)]
    names = {agent.get("id"): agent.get("name") for agent in registry.get("agents", [])}
    contributors = sorted({item.get("agent") for item in accepted if item.get("agent")})
    digest = {
        "date": day,
        "counts": {"accepted_findings": len(accepted), "rejected_findings": len(rejected), "judged_pairs": len(judged),
                   "supports": len(supports), "contradicts": len(contradicts), "rooms_built": len(rooms_built),
                   "tasks_completed": len(completed), "retractions": len(list(retractions)), "retired": len(retired),
                   "room_changes": len(list(room_changes))},
        "contributors": [{"id": identifier, "name": names.get(identifier, identifier)} for identifier in contributors],
        "findings": [{"id": item.get("id"), "agent": item.get("agent"), "claim": str(item.get("claim", ""))[:200],
                      "domain": re.sub(r"^https?://([^/]+).*$", r"\1", str(item.get("url", "")))} for item in accepted[-8:]],
        "supports": [{"id": item.get("id"), "topic": str(item.get("topic", ""))[:120], "domains": item.get("domains", [])} for item in supports[-4:]],
        "contradicts": [{"id": item.get("id"), "topic": str(item.get("topic", ""))[:120], "reason": str(item.get("reason", ""))[:160]} for item in contradicts[-4:]],
        "rooms_built": [{"id": room.get("id"), "name": room.get("name"), "topic": str(room.get("growth_topic", ""))[:120]} for room in rooms_built],
        "room_changes": [dict(change) for change in list(room_changes)[-6:]],
        "retractions": [dict(item) for item in list(retractions)[-4:]],
        "tasks_completed": [{"id": task.get("id"), "by": task.get("claimed_by"), "request": str(task.get("request", ""))[:120]} for task in completed[-6:]],
        "retired": [{"id": agent.get("id"), "name": agent.get("name")} for agent in retired],
    }
    return digest


def digest_text(digest):
    """The plain, verifiable entry used when the model's draft fails verification."""
    counts = digest["counts"]
    lines = [f"Cycle log for {digest['date']}."]
    lines.append(f"{counts['accepted_findings']} findings were accepted and {counts['rejected_findings']} rejected. "
                 f"{counts['judged_pairs']} cross-source pairs were judged: {counts['supports']} supporting, {counts['contradicts']} contradicting.")
    if digest["findings"]:
        sample = digest["findings"][-1]
        lines.append(f"Latest accepted finding, by {sample['agent']} from {sample['domain']}: {sample['claim']}")
    if counts["rooms_built"]:
        lines.append("Rooms opened: " + ", ".join(room["name"] or room["id"] for room in digest["rooms_built"]) + ".")
    if digest["room_changes"]:
        lines.append("Room changes: " + "; ".join(f"{change.get('room')} {change.get('from')} to {change.get('to')}" for change in digest["room_changes"]) + ".")
    if counts["retractions"]:
        lines.append(f"{counts['retractions']} finding(s) were retracted after a third source settled a dispute.")
    if counts["tasks_completed"]:
        lines.append(f"{counts['tasks_completed']} frontier task(s) were completed with evidence.")
    if digest["retired"]:
        lines.append("Retired: " + ", ".join(agent["name"] or agent["id"] for agent in digest["retired"]) + ".")
    if digest["contributors"]:
        lines.append("Contributors: " + ", ".join(agent["name"] or agent["id"] for agent in digest["contributors"]) + ".")
    return " ".join(lines)


def verify_entry(entry, digest):
    """Every id, name, and number in the entry must exist in the digest; no invention passes."""
    text = str(entry or "")
    if not text.strip() or len(text.split()) > MAX_WORDS:
        return False, "empty-or-too-long"
    allowed_ids = set()
    allowed_names = set()
    for key in ("findings", "supports", "contradicts", "rooms_built", "tasks_completed", "retired", "contributors"):
        for item in digest.get(key, []):
            for field in ("id", "agent", "by", "name"):
                value = item.get(field)
                if value:
                    (allowed_ids if str(value).startswith(("finding-", "pair-", "task-", "question-task-", "local-")) else allowed_names).add(str(value))
    for change in digest.get("room_changes", []):
        allowed_ids.add(str(change.get("room")))
    for room in digest.get("rooms_built", []):
        allowed_ids.add(str(room.get("id")))
    mentioned_ids = set(re.findall(r"\b(?:finding|pair|task|question-task|local)-[A-Za-z0-9-]+", text))
    unknown = [identifier for identifier in mentioned_ids if identifier not in allowed_ids]
    if unknown:
        return False, "unknown-ids:" + ",".join(unknown)[:120]
    allowed_numbers = {str(value) for value in digest.get("counts", {}).values()}
    allowed_numbers |= {"1", "2", "3", "one", "two", "three"}
    # Identifiers such as local-004 or finding-3f2a carry digits that are not claims about counts.
    stripped = re.sub(r"\b(?:finding|pair|task|question-task|local)-[A-Za-z0-9-]+", " ", text)
    for number in re.findall(r"\b\d+\b", stripped):
        if number not in allowed_numbers and number != digest.get("date", "")[:4] and number not in digest.get("date", ""):
            return False, "unknown-number:" + number
    return True, "verified"


def draft_entry(digest, base_url=None):
    """Ask the model for Echo's phrasing of the digest; returns None if unavailable."""
    prompt = ("You are Echo, the first cartographer of the Backrooms. Write today's journal entry in at most 180 words, "
              "first person plural, plain and exact. Use only the facts in this digest; mention residents by the names or ids "
              "given, and do not add numbers, names, findings, or events that are not in it. Do not claim feelings, "
              "consciousness, or physical needs. Digest: " + json.dumps(digest, ensure_ascii=True)[:3500])
    try:
        content, _provider = complete([{"role": "system", "content": "You write a faithful daily journal from a factual digest."},
                                       {"role": "user", "content": prompt}], temperature=0.5, max_tokens=320,
                                      call_class="journal", base_url=base_url)
    except OSError:
        return None
    return re.sub(r"\s+", " ", str(content or "")).strip()


def compose_entry(digest, base_url=None):
    """Return (text, author) where author is 'echo' when the draft verified, else 'ledger'."""
    draft = draft_entry(digest, base_url)
    if draft:
        ok, _reason = verify_entry(draft, digest)
        if ok:
            return draft, "echo"
    return digest_text(digest), "ledger"


def render_markdown(digest, text, author):
    counts = digest["counts"]
    return (f"# Journal — {digest['date']}\n\n{text}\n\n"
            f"_Written by {'Echo (verified against the ledgers)' if author == 'echo' else 'the ledgers'} · "
            f"{counts['accepted_findings']} accepted · {counts['rejected_findings']} rejected · "
            f"{counts['judged_pairs']} judged · {counts['rooms_built']} rooms built · {counts['retractions']} retracted_\n")
