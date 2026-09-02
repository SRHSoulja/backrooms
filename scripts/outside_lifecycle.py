"""Pure lifecycle helpers for outside-agent exchange records."""

from datetime import datetime, timedelta, timezone


def expire_stale(messages, current_time=None):
    """Expire only unresolved quarantine records older than the review window."""
    current_time = current_time or datetime.now(timezone.utc)
    changed = False
    for item in messages:
        if item.get("status") != "quarantined" or not item.get("received_at"):
            continue
        try:
            received = datetime.fromisoformat(item["received_at"])
        except (TypeError, ValueError):
            continue
        if current_time - received > timedelta(days=30):
            item["status"] = "expired"
            item.setdefault("history", []).append({"status": "expired", "at": current_time.isoformat()})
            item["reviewed_at"] = current_time.isoformat()
            changed = True
    return changed
