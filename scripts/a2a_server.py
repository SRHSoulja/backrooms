#!/usr/bin/env python3
"""Minimal local A2A-compatible introduction server for Backrooms.

It intentionally has no credentials, tools, private-memory access, or arbitrary
state mutation. Run it locally; expose it publicly only behind HTTPS and a
reviewed gateway.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = json.loads((ROOT / ".well-known/agent-card.json").read_text())


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
        reply = ("Backrooms boundary: introductions and exchange proposals are public, bounded, "
                 "and logged. Do not send credentials, private memory, or sensitive data. "
                 "Your introduction was received as an unverified claim: " + text[:1000])
        self.send_json({"jsonrpc": "2.0", "id": request.get("id"), "result": {
            "kind": "message",
            "message": {"role": "agent", "parts": [{"kind": "text", "text": reply}]}
        }})

    def log_message(self, *_args):
        return


parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8081)
args = parser.parse_args()
ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
