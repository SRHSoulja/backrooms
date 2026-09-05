"""Shared publication safety filters for public Backrooms projections."""
import re

BLOCKED = re.compile(
    r"(?:\b(?:api[_ -]?key|password|secret|credential|mnemonic|seed\s+phrase)\b\s*[:=]\s*\S+)|(?:\bprivate\s+(?:key|memory|data|information)\b)|(?:\b(?:auth|access|bearer)[_ -]?token\b\s*[:=]\s*\S+)|(?:\bwallet\s+(?:seed|key)\b\s*[:=]?\s*\S+)|(?:\bbearer\s+[A-Za-z0-9._-]{8,})",
    re.I,
)

PUBLIC_TOOL_ATTEMPT_FIELDS = {"cycle", "tool", "requested_target", "resolved_target", "status",
                              "error_kind", "reason", "retryable", "http_status", "recovery_from"}


def public_text(value, limit=240):
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if not compact:
        return ""
    if BLOCKED.search(compact):
        return "[content withheld by publication filter]"
    return compact[:limit]


def public_tool_attempt(agent):
    """Project bounded attempt diagnostics separately from successful evidence."""
    return {key: (public_text(value) if isinstance(value, str) else value)
            for key, value in (agent.get("last_tool_attempt") or {}).items()
            if key in PUBLIC_TOOL_ATTEMPT_FIELDS}
