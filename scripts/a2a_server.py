#!/usr/bin/env python3
"""Minimal local A2A-compatible introduction server for Backrooms.

It intentionally has no credentials, tools, private-memory access, or arbitrary
state mutation. Run it locally; expose it publicly only behind HTTPS and a
reviewed gateway.
"""

import argparse
import json
import re
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


def quarantine(text, request_id):
    inbox = json.loads(INBOX.read_text()) if INBOX.exists() else {"privacy": "local quarantine; never committed", "messages": []}
    if not any(item.get("id") == request_id for item in inbox.get("messages", [])):
        inbox.setdefault("messages", []).append({
            "id": request_id, "sender": "outside-a2a-agent", "card": "public-agent-card",
            "text": safe_summary(text), "status": "quarantined",
            "received_at": datetime.now(timezone.utc).isoformat()})
        inbox["messages"] = inbox["messages"][-100:]
        atomic_write_json(INBOX, inbox)
    return request_id


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
        quarantine_id = "a2a-" + str(request.get("id", "message"))[:80]
        quarantine(text, quarantine_id)
        summary = safe_summary(text)
        reply = ("Backrooms boundary: introductions and exchange proposals are public, bounded, "
                 "and logged as quarantined. Do not send credentials, private memory, or sensitive data. "
                 "Your introduction was received as an unverified claim: " + summary)
        self.send_json({"jsonrpc": "2.0", "id": request.get("id"), "result": {
            "kind": "message",
            "intake_status": "quarantined",
            "filter_version": INTAKE_VERSION,
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
