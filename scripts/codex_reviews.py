"""Turn completed Codex bridge reviews into untrusted frontier leads.

The bridge writes each finished task to state/codex-outbox as a JSON record
whose ``output`` is the CLI's event stream. Only the final assistant message
is kept, it is passed through the publication filter by the caller, and it
enters the frontier as a *lead* with status ``unverified``: residents may
cite or test it, never treat it as a finding.
"""

import json
import re
from pathlib import Path

MAX_LEAD_CHARS = 600
MAX_LEADS = 50


def _texts_from_event(event):
    """Yield assistant-authored text from one JSON event in any known shape."""
    if not isinstance(event, dict):
        return
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") in {"agent_message", "message"}:
        if isinstance(item.get("text"), str):
            yield item["text"]
        for part in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                yield part["text"]
    message = event.get("msg")
    if isinstance(message, dict) and message.get("type") == "agent_message" and isinstance(message.get("message"), str):
        yield message["message"]
    if event.get("type") == "message" and event.get("role") == "assistant":
        for part in event.get("content", []) if isinstance(event.get("content"), list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                yield part["text"]
    if event.get("role") == "assistant" and isinstance(event.get("text"), str):
        yield event["text"]


def extract_review_text(output, limit=1200):
    """Return the final assistant message from a Codex ``--json`` stream, or plain text."""
    texts = []
    plain = []
    for line in str(output or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            plain.append(line)
            continue
        texts.extend(text for text in _texts_from_event(event) if text and text.strip())
    chosen = texts[-1] if texts else " ".join(plain)
    return re.sub(r"\s+", " ", chosen).strip()[:limit]


def question_id_from_task(task_id):
    value = re.sub(r"-retry-\d+$", "", str(task_id or ""))
    return value[len("frontier-"):] if value.startswith("frontier-") else value


def review_lead(record, text, cycle):
    task_id = str(record.get("task_id") or Path(str(record.get("task_file", ""))).stem)
    return {"id": "lead-codex-" + task_id, "source": "codex-review", "task_id": task_id,
            "question_id": question_id_from_task(task_id), "text": text, "status": "unverified",
            "cycle": cycle, "completed_at": record.get("completed_at")}


def consume_outbox(outbox_dir, consumed_path, frontier, cycle, sanitize):
    """Move finished reviews from the outbox into ``frontier['leads']`` exactly once.

    ``sanitize`` is the publication filter; a review whose text is withheld by
    it is consumed but produces no lead. Failed or timed-out tasks are consumed
    silently so they are never re-read.
    """
    outbox_dir = Path(outbox_dir)
    consumed_path = Path(consumed_path)
    try:
        consumed = set(json.loads(consumed_path.read_text()).get("consumed", []))
    except (OSError, json.JSONDecodeError):
        consumed = set()
    leads = frontier.setdefault("leads", [])
    known = {item.get("id") for item in leads}
    added = 0
    for path in sorted(outbox_dir.glob("*.json")) if outbox_dir.exists() else []:
        if path.name in consumed:
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            consumed.add(path.name)
            continue
        consumed.add(path.name)
        if record.get("status") != "completed":
            continue
        text = sanitize(extract_review_text(record.get("output", "")), MAX_LEAD_CHARS)
        if not text or text.startswith("["):
            continue
        lead = review_lead({**record, "task_file": path.name}, text, cycle)
        if lead["id"] in known:
            continue
        leads.append(lead)
        known.add(lead["id"])
        added += 1
    frontier["leads"] = leads[-MAX_LEADS:]
    consumed_path.parent.mkdir(parents=True, exist_ok=True)
    consumed_path.write_text(json.dumps({"consumed": sorted(consumed)[-1000:]}, indent=2) + "\n")
    return added
