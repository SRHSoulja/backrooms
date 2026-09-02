"""Shared publication safety filters for public Backrooms projections."""
import re

BLOCKED = re.compile(
    r"api[_ -]?key|password|secret|private\s+(?:key|memory|data|information)|credential|(?:auth|access|bearer)[_ -]?token|wallet\s+(?:seed|key)|seed phrase|mnemonic|bearer\s+[A-Za-z0-9._-]+",
    re.I,
)


def public_text(value, limit=240):
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if not compact or BLOCKED.search(compact):
        return "[content withheld by publication filter]"
    return compact[:limit]
