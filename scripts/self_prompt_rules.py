"""Pure validation rules for bounded council question proposals."""

import json
import re
from pathlib import Path

def finding_followup_question(finding):
    try:
        from scripts.world_rules import finding_followup_question as followup
    except ImportError:
        from world_rules import finding_followup_question as followup
    return followup(finding)


RESIDENT_SOURCES = ("resident:", "finding-followup", "carried")


def carry_forward(open_questions):
    """The newest open question the world itself produced, or None.

    When neither resident proposes a valid question and no finding is there to
    follow up, the council carries its own last question forward rather than
    taking one from any list a human wrote."""
    items = [item for item in (open_questions or []) if isinstance(item, dict) and str(item.get("question", "")).strip()]
    def own(item):
        source = str(item.get("question_source") or "")
        return any(source.startswith(prefix) for prefix in RESIDENT_SOURCES)
    ordered = sorted(items, key=lambda item: int(item.get("cycle") or 0), reverse=True)
    for pool in (lambda item: own(item) and item.get("status", "open") == "open", lambda item: item.get("status", "open") == "open",
                 lambda item: own(item) and item.get("status") != "abandoned"):
        for item in ordered:
            if pool(item):
                return item
    return None


FORBIDDEN = re.compile(r"(api[_ -]?key|password|secret|private memory|credential|token)", re.I)
SELF_REFERENTIAL = re.compile(
    r"(?:evidence\s+markers?|hypothesis\s+(?:was\s+)?weaken|marker\s+counts?|"
    r"(?:echo|morrow)(?:'s|\s+outputs?)|recent\s+aggregate\s+actions?|"
    # Questions about the world's own topology or telemetry never lead to
    # public evidence; the council should ask about the outside world.
    r"\b(?:atrium|relay|archive|quiet[- ]workspace|outbound\s+door|dead\s+terminal)\b|"
    r"\bresidents?\b|\brooms?\b|\bhirelings?\b|\bcycle\s+\d+)", re.I)


def rejection_reason(proposal):
    """Why a proposal fails the council's rules, or "" when it passes; the
    resident is told this once and may try again."""
    fields = {line.split(":", 1)[0].strip().upper(): line.split(":", 1)[1].strip()
              for line in str(proposal or "").splitlines() if ":" in line}
    if len(str(proposal or "")) > 1200:
        return "too long"
    if FORBIDDEN.search(str(proposal or "")):
        return "mentions credentials or private memory"
    missing = [name for name in ("QUESTION", "WHY", "TEST") if not fields.get(name)]
    if missing:
        return "missing " + ", ".join(missing) + " line(s); return exactly QUESTION:, WHY:, TEST:"
    return question_rejection_reason(fields.get("QUESTION", ""))


def question_rejection_reason(question):
    """Why a bare question cannot open or extend a research line, or ""."""
    text = re.sub(r"\s+", " ", str(question or "")).strip()
    if len(text) < 12:
        return "the question is too short to research"
    if FORBIDDEN.search(text):
        return "mentions credentials or private memory"
    if SELF_REFERENTIAL.search(text):
        return "the question is about this world's own rooms, residents, or telemetry; ask about the outside world"
    if about_profile(text):
        return "the question is about an individual's account, profile, or handle; ask about the world, not about a person"
    if "[input]" in text.lower() or re.search(r"\{[^}]*\}", text):
        return "the question has a placeholder where its subject should be"
    return ""


def about_profile(text):
    try:
        from scripts.corroboration import about_profile as check
    except ImportError:
        from corroboration import about_profile as check
    return check(text)


def valid(proposal):
    return rejection_reason(proposal) == ""
