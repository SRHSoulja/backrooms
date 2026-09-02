"""Pure validation rules for bounded council question proposals."""

import re

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
