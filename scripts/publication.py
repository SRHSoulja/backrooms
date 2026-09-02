"""Shared publication safety filters for public Backrooms projections."""
import re

BLOCKED = re.compile(
    r"(?:\b(?:api[_ -]?key|password|secret|credential|mnemonic|seed\s+phrase)\b\s*[:=]\s*\S+)|(?:\bprivate\s+(?:key|memory|data|information)\b)|(?:\b(?:auth|access|bearer)[_ -]?token\b\s*[:=]\s*\S+)|(?:\bwallet\s+(?:seed|key)\b\s*[:=]?\s*\S+)|(?:\bbearer\s+[A-Za-z0-9._-]{8,})",
    re.I,
)


def public_text(value, limit=240):
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if not compact:
        return ""
    if BLOCKED.search(compact):
        return "[content withheld by publication filter]"
    return compact[:limit]
