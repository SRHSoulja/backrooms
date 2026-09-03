"""Pure validation rules for bounded council question proposals."""

import json
import re
from pathlib import Path

THEMES = Path(__file__).resolve().parents[1] / "docs/research-themes.json"


def research_themes(cycle, count=2, path=THEMES):
    """Rotate a bounded slice of the public research themes into council context."""
    try:
        themes = [str(item) for item in json.loads(Path(path).read_text()).get("themes", []) if str(item).strip()]
    except (OSError, json.JSONDecodeError):
        return []
    if not themes:
        return []
    start = int(cycle or 0) % len(themes)
    return [themes[(start + offset) % len(themes)] for offset in range(min(count, len(themes)))]

FORBIDDEN = re.compile(r"(api[_ -]?key|password|secret|private memory|credential|token)", re.I)
SELF_REFERENTIAL = re.compile(
    r"(?:evidence\s+markers?|hypothesis\s+(?:was\s+)?weaken|marker\s+counts?|"
    r"(?:echo|morrow)(?:'s|\s+outputs?)|recent\s+aggregate\s+actions?)", re.I)


def valid(proposal):
    fields = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
              for line in proposal.splitlines() if ":" in line}
    return (len(proposal) <= 1200 and not FORBIDDEN.search(proposal)
            and not SELF_REFERENTIAL.search(fields.get("QUESTION", ""))
            and all(fields.get(name) for name in ("QUESTION", "WHY", "TEST")))
