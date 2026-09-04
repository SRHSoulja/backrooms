#!/usr/bin/env python3
"""Reports: a resident's dossier on a topic, compiled from the ledgers.

Everything in a report is traceable: each finding with its claim, quote,
source, content hash, author, and cycle; each judged pair with its verdict;
the rooms the topic founded or withdrew. A model may add one narrative
paragraph, verified the way the journal is verified: every name, id, and
number in it must exist in the report's digest or the paragraph is dropped.
"""

import hashlib
import json
import re
import urllib.parse
from datetime import datetime, timezone

try:
    from scripts.evidence import claim_terms, is_accepted
    from scripts.journal import verify_entry
    from scripts.model_client import ModelUnavailable, complete
except ImportError:
    from evidence import claim_terms, is_accepted
    from journal import verify_entry
    from model_client import ModelUnavailable, complete


def _stems(text):
    return {term[:6] for term in claim_terms(text)}


def on_topic(topic, finding):
    wanted = _stems(topic)
    if not wanted:
        return False
    have = _stems(str(finding.get("topic", ""))) | _stems(str(finding.get("claim", "")))
    return len(wanted & have) / len(wanted | have) >= 0.34 if (wanted | have) else False


def compile_report(topic, findings, corroborations, world, questions=(), agent_id="resident", cycle=0):
    """Return (title, body, digest) for a topic; body is plain text, digest feeds the verifier."""
    topic = re.sub(r"\s+", " ", str(topic or "")).strip()[:200]
    related = [item for item in findings if on_topic(topic, item)]
    accepted = [item for item in related if is_accepted(item)]
    rejected = [item for item in related if item.get("status") == "rejected"]
    ids = {item.get("id") for item in related}
    pairs = [record for record in corroborations if set(record.get("finding_ids", [])) & ids]
    supports = [record for record in pairs if record.get("relation") == "supports"]
    contradicts = [record for record in pairs if record.get("relation") == "contradicts"]
    rooms = [room for room in world.get("rooms", []) if room.get("founded_via") == "evidence-ledger"
             and set(room.get("artifacts", [])) & ids]
    asked = [str(q.get("question", ""))[:220] for q in questions if on_topic(topic, {"topic": "", "claim": q.get("question", "")})][-3:]
    domain = lambda item: urllib.parse.urlparse(str(item.get("url", ""))).netloc.lower()
    names = {}
    for item in related:
        names.setdefault(item.get("agent"), item.get("agent"))
    digest = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "counts": {"accepted_findings": len(accepted), "rejected_findings": len(rejected), "judged_pairs": len(pairs),
                   "supports": len(supports), "contradicts": len(contradicts), "rooms_built": len(rooms),
                   "tasks_completed": 0, "retractions": 0, "retired": 0, "room_changes": 0, "domains": len({domain(i) for i in accepted})},
        "findings": [{"id": item.get("id"), "agent": item.get("agent"), "claim": str(item.get("claim", ""))[:200], "domain": domain(item)} for item in accepted[-12:]],
        "supports": [{"id": r.get("id"), "topic": str(r.get("shared_claim") or r.get("topic") or "")[:160], "domains": r.get("domains", [])} for r in supports[-6:]],
        "contradicts": [{"id": r.get("id"), "topic": str(r.get("topic", ""))[:120], "reason": str(r.get("reason", ""))[:160]} for r in contradicts[-6:]],
        "rooms_built": [{"id": room.get("id"), "name": room.get("name"), "topic": str(room.get("growth_topic", ""))[:120]} for room in rooms],
        "room_changes": [], "retractions": [], "tasks_completed": [], "retired": [],
        "contributors": [{"id": identifier, "name": identifier} for identifier in sorted({item.get("agent") for item in accepted if item.get("agent")})],
    }
    lines = [f"REPORT: {topic}", f"Compiled by {agent_id} at cycle {cycle} from the public ledgers.", ""]
    if asked:
        lines.append("Questions asked: " + " | ".join(asked))
    lines.append(f"Accepted findings: {len(accepted)} from {digest['counts']['domains']} domain(s). Rejected: {len(rejected)}. "
                 f"Judged pairs: {len(pairs)} ({len(supports)} supporting, {len(contradicts)} contradicting). Rooms founded: {len(rooms)}.")
    lines.append("")
    for item in accepted[-12:]:
        lines.append(f"- [{item.get('id')}] {str(item.get('claim', ''))[:300]}")
        if item.get("quote"):
            lines.append(f"  quote: \"{str(item.get('quote', ''))[:300]}\"")
        lines.append(f"  source: {str(item.get('url', ''))[:300]} · sha256 {str(item.get('content_hash', ''))[:16]} · by {item.get('agent')} · cycle {item.get('cycle')}")
    for record in supports[-6:]:
        lines.append(f"- SUPPORTS [{record.get('id')}]: {str(record.get('shared_claim') or record.get('topic') or '')[:240]} · {', '.join(record.get('domains', []))}")
    for record in contradicts[-6:]:
        lines.append(f"- CONTRADICTS [{record.get('id')}]: {str(record.get('reason', ''))[:240]} · {', '.join(record.get('domains', []))}")
    for room in rooms:
        lines.append(f"- ROOM {room.get('id')} ({room.get('status', 'open')}): {str(room.get('growth_topic', ''))[:160]}")
    if rejected:
        reasons = {}
        for item in rejected:
            reasons[item.get("rejection_reason", "rejected")] = reasons.get(item.get("rejection_reason", "rejected"), 0) + 1
        lines.append("Rejected findings by reason: " + ", ".join(f"{key} {value}" for key, value in sorted(reasons.items())))
    return f"Report: {topic}"[:120], "\n".join(lines).strip(), digest


def narrative(topic, digest, base_url=None):
    """One model-written paragraph about the report, kept only if it verifies."""
    prompt = ("Write one paragraph, at most 120 words, summarizing what the public evidence below establishes about the topic '"
              + topic + "'. Use only the facts in this digest; name residents by the ids given; add no numbers, names, or facts that are not in it. "
              "Say plainly when the evidence is thin or unconfirmed. Digest: " + json.dumps(digest, ensure_ascii=True)[:3000])
    try:
        text, _provider = complete([{"role": "system", "content": "You summarize a factual digest faithfully."},
                                    {"role": "user", "content": prompt}], temperature=0.4, max_tokens=220,
                                   call_class="report", base_url=base_url)
    except (ModelUnavailable, OSError):
        return ""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    ok, _reason = verify_entry(text, digest)
    return text if ok else ""


def content_hash(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
