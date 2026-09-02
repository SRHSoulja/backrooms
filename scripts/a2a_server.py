#!/usr/bin/env python3
"""Minimal local A2A-compatible introduction server for Backrooms.

It intentionally has no credentials, tools, private-memory access, or arbitrary
state mutation. Run it locally; expose it publicly only behind HTTPS and a
reviewed gateway.
"""

import argparse
import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone

try:
    from scripts.storage import atomic_write_json
except ImportError:
    from storage import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
CARD = json.loads((ROOT / ".well-known/agent-card.json").read_text())
INBOX = ROOT / "state/quarantine-inbox.json"
INTAKE_VERSION = "2-narrow-secret-patterns"
# Do not suppress a benign disclaimer merely because it mentions the words
# "credentials" or "private data". Match secret-shaped material instead.
SENSITIVE = re.compile(r"(?i)(?:(?:api[_ -]?key|password|secret|credential|private[_ -]?key|mnemonic)\s*(?:[:=]|is)\s*\S+|seed\s+phrase\s*[:=]?\s*\S+|bearer\s+[A-Za-z0-9._-]{12,})")


def safe_summary(text):
    compact = re.sub(r"\s+", " ", text).strip()
    return "[external content withheld by intake filter]" if SENSITIVE.search(compact) else compact[:500]


def quarantine(text, request_id, parent_task_id=""):
    # Defense in depth: callers must never be able to persist an unverified
    # parent, even if they bypass the request handler's resolution step.
    if parent_task_id and not accepted_parent(parent_task_id):
        parent_task_id = ""
    inbox = json.loads(INBOX.read_text()) if INBOX.exists() else {"privacy": "local quarantine; never committed", "messages": []}
    if not any(item.get("id") == request_id for item in inbox.get("messages", [])):
        received_at = datetime.now(timezone.utc).isoformat()
        entry = {
            "id": request_id, "sender": "outside-a2a-agent", "card": "public-agent-card",
            "text": safe_summary(text), "status": "quarantined", "received_at": received_at,
            "history": [{"status": "pending-review", "at": received_at}]}
        if parent_task_id:
            entry["parent_task_id"] = parent_task_id[:80]
        inbox.setdefault("messages", []).append(entry)
        inbox["messages"] = inbox["messages"][-100:]
        atomic_write_json(INBOX, inbox)
    return request_id


def accepted_parent(task_id):
    if not task_id or not INBOX.exists():
        return ""
    try:
        inbox = json.loads(INBOX.read_text())
    except json.JSONDecodeError:
        return ""
    return task_id[:80] if any(item.get("id") == task_id and item.get("status") == "accepted-exchange"
                               for item in inbox.get("messages", [])) else ""


def task_id_for(request_id):
    """Return a stable public task ID without duplicating the namespace prefix."""
    value = str(request_id or "message")[:80]
    return value if value.startswith("a2a-") else "a2a-" + value


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/.well-known/agent-card.json":
            self.send_json(CARD)
        elif self.path.startswith("/a2a/tasks/"):
            task_id = urllib.parse.unquote(self.path.removeprefix("/a2a/tasks/")).split("?", 1)[0]
            inbox = json.loads(INBOX.read_text()) if INBOX.exists() else {"messages": []}
            item = next((entry for entry in inbox.get("messages", []) if entry.get("id") == task_id), None)
            if not item:
                self.send_json({"error": "task_not_found"}, 404)
                return
            intake_status = item.get("status", "quarantined")
            task_status = "pending-review" if intake_status == "quarantined" else intake_status
            self.send_json({"task_id": task_id, "status": task_status, "intake_status": intake_status,
                            "received_at": item.get("received_at"), "reviewed_at": item.get("reviewed_at"),
                            "parent_task_id": item.get("parent_task_id") if accepted_parent(item.get("parent_task_id", "")) else None,
                            "parent_link": "accepted-exchange" if accepted_parent(item.get("parent_task_id", "")) else ("unrecognized" if item.get("parent_task_id") else None),
                            "history": item.get("history", []),
                            "scope": "outside-exchange-review", "resident_admission": False,
                            "capabilities": []})
        else:
            self.send_json({"error": "not_found"}, 404)

    def do_POST(self):
        if self.path != "/a2a":
            self.send_json({"error": "not_found"}, 404)
            return
        length = min(int(self.headers.get("Content-Length", "0")), 8192)
        try:
            request = json.loads(self.rfile.read(length))
            text = request["params"]["message"]["parts"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            self.send_json({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}, 400)
            return
        if len(text) > 1000:
            self.send_json({"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32602, "message": "message too long"}}, 413)
            return
        quarantine_id = task_id_for(request.get("id", "message"))
        message = request.get("params", {}).get("message", {})
        requested_parent = str(message.get("taskId") or request.get("params", {}).get("taskId") or "")
        parent_task_id = accepted_parent(requested_parent)
        quarantine(text, quarantine_id, parent_task_id)
        summary = safe_summary(text)
        reply = ("Backrooms boundary: introductions and exchange proposals are public, bounded, "
                 "and logged as quarantined. Do not send credentials, private memory, or sensitive data. "
                 "Your introduction was received as an unverified claim: " + summary)
        self.send_json({"jsonrpc": "2.0", "id": request.get("id"), "result": {
            "kind": "message",
            "intake_status": "quarantined",
            "filter_version": INTAKE_VERSION,
            "task": {"id": quarantine_id, "status": "pending-review",
                      "status_url": "/a2a/tasks/" + quarantine_id,
                      "scope": "outside-exchange-review",
                      "parent_task_id": parent_task_id or None,
                      "parent_link": "accepted-exchange" if parent_task_id else ("unrecognized" if requested_parent else None)},
            "message": {"role": "agent", "parts": [{"kind": "text", "text": reply}]}
        }})

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
