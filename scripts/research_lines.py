"""Research lines: the council works one root question at a time.

A line is a root question, the rare terms that anchor it, the questions asked
on it (at most HOP_CAP), and how it ended. A finding on the line must mention
an anchor; a resident proposal that shares no anchor with the open line is a
proposal for a new line and waits in a queue instead of steering the day. A
closed line's anchors stay closed for COOLDOWN_CYCLES so the world cannot
reopen the same subject by rephrasing. Pure rules; the daemon does the I/O.
"""

import hashlib
import json
import re
from pathlib import Path

try:
    from scripts.evidence import FUNCTION_WORDS, STOPWORDS
except ImportError:
    from evidence import FUNCTION_WORDS, STOPWORDS

HOP_CAP = 3
EMPTY_CYCLES_CAP = 4
COOLDOWN_CYCLES = 24
QUEUE_CAP = 10
MAX_ANCHORS = 6
GENERIC_FLOOR = 0.15
GENERIC_MINIMUM = 20
# Words that name where evidence lives or how research talks, never what it is
# about. The ledger's own frequencies add to this list as it grows.
GENERIC_SEED = {
    "github", "wikipedia", "google", "twitter", "reddit", "arxiv", "readme", "readmes", "profile", "profiles", "account", "accounts",
    "repository", "repositories", "repo", "repos", "data", "dataset", "datasets", "paper", "papers", "study", "studies", "research",
    "source", "sources", "public", "publicly", "documented", "documentation", "official", "organization", "organizations", "website",
    "websites", "online", "information", "system", "systems", "model", "models", "agent", "agents", "evidence", "claim", "claims",
    "question", "questions", "finding", "findings", "independent", "framework", "frameworks", "approach", "approaches", "method",
    "methods", "analysis", "analyses", "result", "results", "report", "reports", "published", "publication", "available", "specific",
    "example", "examples", "using", "based", "related", "different", "between", "within", "without", "whether", "which", "their",
    "there", "these", "those", "would", "could", "should", "verify", "verified", "verifiable", "visible", "support", "supports",
    "contradict", "contradicts", "settle", "metadata", "criteria", "explicitly", "statistically", "significant", "measurable",
    "reliable", "reputable", "recent", "current", "existing", "known", "provide", "provides", "return", "exact", "confidence",
    "media", "news", "archive", "archives", "record", "records", "web", "site", "sites", "page", "pages", "user", "users",
    "according", "publish", "publishes", "similar", "handle", "handles", "choose", "hide", "mean", "consistently", "hold",
    "holds", "show", "shows", "list", "lists", "include", "includes", "name", "names", "content", "contents", "activity",
    "history", "timeline", "affiliation", "connection", "channel", "channels", "input", "output", "phrasing", "return",
}
ANCHOR_STOPWORDS = STOPWORDS | FUNCTION_WORDS | GENERIC_SEED


def stem(term):
    """Eight characters keep 'Roskomnadzor' and 'Roscomnadzor27' apart while 'repositories' still meets 'repository'."""
    term = str(term or "").lower()
    return term[:8] if len(term) > 8 else term


def content_terms(text):
    """Lower-case content words of a text, in order, without repeats."""
    seen = []
    clean = re.sub(r"[*_`]+", "", str(text or ""))
    for term in re.findall(r"[a-z0-9][a-z0-9-]{3,}", clean.lower()):
        if term in STOPWORDS or term in FUNCTION_WORDS or term in seen:
            continue
        seen.append(term)
    return seen


def generic_terms(claims, floor=GENERIC_FLOOR, minimum=GENERIC_MINIMUM):
    """Terms that appear in at least ``floor`` of the ledger's claims are the
    world's own generic vocabulary; they anchor nothing. Needs ``minimum``
    claims before it says anything, so a young ledger does not over-fit."""
    claims = [str(claim) for claim in claims if str(claim or "").strip()]
    if len(claims) < minimum:
        return set()
    counts = {}
    for claim in claims:
        for term in set(content_terms(claim)):
            counts[term] = counts.get(term, 0) + 1
    return {term for term, count in counts.items() if count / len(claims) >= floor}


def anchor_terms(question, generic=()):
    """The rare terms that say what a question is about: names, numbers, long
    technical words. Generic research vocabulary never anchors a line."""
    text = re.sub(r"[*_`]+", "", str(question or ""))
    original = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{3,}", text)
    capitalised = set()
    for index, token in enumerate(original):
        if index > 0 and token[0].isupper():
            capitalised.add(token.lower())
    generic = set(generic or ())
    acronyms = [token.lower() for token in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", text)
                if token.lower() not in ANCHOR_STOPWORDS and token.lower() not in generic]
    proper, common = [], []
    for term in acronyms + content_terms(text):
        if term in ANCHOR_STOPWORDS or term in generic or term in proper or term in common:
            continue
        if term in acronyms or term in capitalised or any(char.isdigit() for char in term):
            proper.append(term)
        else:
            common.append(term)
    common.sort(key=lambda term: -len(term))
    anchors = []
    for term in proper + (common if len(proper) < 2 else []):
        if stem(term) in {stem(item) for item in anchors}:
            continue
        anchors.append(term)
        if len(anchors) >= (MAX_ANCHORS if len(proper) >= 2 else 3):
            break
    return anchors


def shares_anchor(text, anchors):
    """True when a text mentions any anchor (by stem), so 'Roskomnadzor's' matches 'roskomnadzor'."""
    anchors = [stem(item) for item in (anchors or []) if item]
    if not anchors:
        return False
    words = {stem(term) for term in content_terms(text)}
    return any(item in words for item in anchors)


def line_query(line):
    """The search terms a line is pursued with: anchors first, then the root's other content words."""
    anchors = list(line.get("anchors") or [])
    if not anchors:
        return ""  # an unanchored line (the fixed fallback) steers no search
    extra = [term for term in content_terms(line.get("root", "")) if term not in anchors and term not in ANCHOR_STOPWORDS]
    return " ".join((anchors + extra)[:8])[:160]


def empty_state():
    return {"schema_version": 1, "lines": [], "queue": [], "used_hire_questions": []}


def load_state(path):
    try:
        state = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(state, dict):
        return empty_state()
    for key, default in empty_state().items():
        state.setdefault(key, default)
    return state


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def open_line(state):
    for line in reversed(state.get("lines", [])):
        if line.get("status") == "open":
            return line
    return None


def new_line(cycle, question, anchors, origin):
    digest = hashlib.sha256(f"{cycle}:{question}".encode()).hexdigest()[:8]
    return {"id": f"line-{int(cycle):06d}-{digest}", "root": str(question)[:300], "anchors": list(anchors or []),
            "opened_cycle": int(cycle), "origin": str(origin or "")[:80], "status": "open",
            "hops": [{"cycle": int(cycle), "question": str(question)[:300], "source": str(origin or "")[:80]}],
            "findings": 0, "empty_cycles": 0, "rooms": []}


def close_line(line, cycle, reason):
    line["status"] = "closed"
    line["closed_cycle"] = int(cycle)
    line["closed_reason"] = str(reason)[:120]
    return line


def in_cooldown(anchors, state, cycle):
    """True when any anchor belongs to a line closed within COOLDOWN_CYCLES."""
    stems = {stem(item) for item in (anchors or []) if item}
    if not stems:
        return False
    for line in state.get("lines", []):
        if line.get("status") != "closed":
            continue
        if int(cycle) - int(line.get("closed_cycle") or 0) >= COOLDOWN_CYCLES:
            continue
        if stems & {stem(item) for item in line.get("anchors", [])}:
            return True
    return False


def queue_proposal(state, cycle, question, source, anchors):
    """Hold a proposal for a new line. One entry per subject: a proposal that
    shares an anchor with a queued one is the same subject and is dropped."""
    question = re.sub(r"\s+", " ", str(question or "")).strip()[:300]
    if not question or not anchors:
        return False
    for item in state.get("queue", []):
        if shares_anchor(question, item.get("anchors", [])) or shares_anchor(item.get("question", ""), anchors):
            return False
    state.setdefault("queue", []).append({"question": question, "source": str(source or "")[:80], "cycle": int(cycle),
                                          "anchors": list(anchors)})
    state["queue"] = state["queue"][-QUEUE_CAP:]
    return True


def _result(question, source, line, opened=False, closed=()):
    return {"question": str(question or "")[:300], "source": source, "line_id": line.get("id") if line else "",
            "anchors": list(line.get("anchors") or []) if line else [], "research_topic": line_query(line) if line else "",
            "opened": opened, "closed": list(closed)}


def decide(state, cycle, proposals, followup_for, hire_questions, fallback, generic=(), stream_questions=None):
    """Choose the cycle's council question and update the line state.

    ``proposals`` are accepted resident proposals as (question, source) in
    council order; ``followup_for(line)`` returns the question the line's own
    newest finding leaves behind, or ""; ``hire_questions`` are (agent_id,
    question) pairs that pass the council's rules; ``fallback`` is the fixed
    last-resort question. Returns the decision as a dict.
    """
    cycle = int(cycle)
    closed = []
    line = open_line(state)
    proposals = [(re.sub(r"\s+", " ", str(q or "")).strip()[:300], s) for q, s in (proposals or []) if str(q or "").strip()]
    steps = [(q, s) for q, s in proposals if line and shares_anchor(q, line.get("anchors", []))]
    news = [(q, s) for q, s in proposals if not line or not shares_anchor(q, line.get("anchors", []))]
    for question, source in news:
        anchors = anchor_terms(question, generic)
        if anchors and not in_cooldown(anchors, state, cycle):
            queue_proposal(state, cycle, question, source, anchors)
    if line and not line.get("anchors") and (state.get("queue") or stream_questions or hire_questions):
        # A line with nothing to anchor it (the fixed fallback) gives way as
        # soon as the world has a subject of its own.
        close_line(line, cycle, "superseded by a resident question")
        closed.append({"id": line["id"], "reason": line["closed_reason"]})
        line = None
    if line:
        last = line["hops"][-1]["question"]
        candidate, source = (steps[0] if steps else ("", ""))
        if not candidate:
            followup = str(followup_for(line) if followup_for else "").strip()
            if followup:
                candidate, source = followup, "finding-followup"
        if candidate and candidate.lower() != last.lower() and len(line["hops"]) < HOP_CAP:
            line["hops"].append({"cycle": cycle, "question": candidate[:300], "source": source})
            return _result(candidate, source, line, closed=closed)
        if candidate and candidate.lower() != last.lower():
            line["cap_reached_cycle"] = line.get("cap_reached_cycle") or cycle
        return _result(last, "carried:" + line["id"], line, closed=closed)
    # No open line: the next root is the oldest queued resident subject, then a
    # resident's own hiring question, then the fixed fallback.
    queue = state.get("queue", [])
    while queue:
        item = queue.pop(0)
        if in_cooldown(item.get("anchors", []), state, cycle):
            continue
        line = new_line(cycle, item["question"], item.get("anchors", []), "queued:" + str(item.get("source", "")))
        state["lines"].append(line)
        return _result(item["question"], item.get("source", "resident"), line, opened=True, closed=closed)
    # Then what the public web is saying today: a sourced current event the
    # residents can confirm from a second outlet, offered in rotation.
    for question, source in (stream_questions or []):
        anchors = anchor_terms(question, generic)
        if not anchors or in_cooldown(anchors, state, cycle):
            continue
        if any(shares_anchor(question, line.get("anchors", [])) for line in state.get("lines", []) if line.get("status") == "open"):
            continue
        line = new_line(cycle, question, anchors, source)
        state["lines"].append(line)
        return _result(question, source, line, opened=True, closed=closed)
    used = set(state.get("used_hire_questions", []))
    for agent_id, question in (hire_questions or []):
        if agent_id in used:
            continue
        anchors = anchor_terms(question, generic)
        state.setdefault("used_hire_questions", []).append(agent_id)
        if not anchors or in_cooldown(anchors, state, cycle):
            continue
        line = new_line(cycle, question, anchors, "hire:" + str(agent_id))
        state["lines"].append(line)
        return _result(question, "hire:" + str(agent_id), line, opened=True, closed=closed)
    line = new_line(cycle, fallback, [], "fallback")
    state["lines"].append(line)
    return _result(fallback, "fixed-fallback", line, opened=True, closed=closed)


def note_outcome(state, cycle, accepted_on_line, room_ids=()):
    """After the cycle's research: a room founded on the line wins it; a cycle
    without a new accepted finding counts toward abandonment."""
    line = open_line(state)
    if not line:
        return []
    room_ids = [room for room in (room_ids or []) if room]
    if room_ids:
        line["rooms"] = list(dict.fromkeys(list(line.get("rooms", [])) + room_ids))
        line["findings"] = int(line.get("findings", 0)) + int(accepted_on_line or 0)
        close_line(line, cycle, "room founded on the line")
        return [{"id": line["id"], "reason": line["closed_reason"], "rooms": room_ids}]
    if accepted_on_line:
        line["findings"] = int(line.get("findings", 0)) + int(accepted_on_line)
        line["empty_cycles"] = 0
        return []
    line["empty_cycles"] = int(line.get("empty_cycles", 0)) + 1
    if line["empty_cycles"] >= EMPTY_CYCLES_CAP:
        close_line(line, cycle, f"no new accepted finding in {EMPTY_CYCLES_CAP} cycles")
        return [{"id": line["id"], "reason": line["closed_reason"]}]
    return []


def public_view(state, limit=12):
    """What the site shows: each line's root, anchors, hops, and how it ended; the queue's subjects."""
    lines = []
    for line in state.get("lines", [])[-limit:]:
        lines.append({key: line.get(key) for key in ("id", "root", "anchors", "opened_cycle", "origin", "status", "hops",
                                                        "findings", "empty_cycles", "rooms", "closed_cycle", "closed_reason")})
    return {"hop_cap": HOP_CAP, "empty_cycles_cap": EMPTY_CYCLES_CAP, "cooldown_cycles": COOLDOWN_CYCLES,
            "open": next((line["id"] for line in lines if line.get("status") == "open"), None),
            "lines": lines,
            "queue": [{"question": item.get("question"), "source": item.get("source"), "cycle": item.get("cycle")}
                      for item in state.get("queue", [])]}
