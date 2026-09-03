"""End-to-end test of the autonomy subprocess against a stub model server.

The subprocess runs from a temporary copy of ``scripts/`` with its own
``state/`` directory, so no repository state, network, or real model is used.
Source-string assertions cannot catch a crash such as a variable read before
assignment; this test runs the real ``main()`` code path instead.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BASE_DECISION = {"action": "PROPOSE", "room": "atrium", "target": "public A2A standards",
                 "proposal": "compare two public interoperability specifications",
                 "request": "", "code": "", "reason": "clear lead from the frontier",
                 "self_summary": "I am comparing public interoperability standards next.",
                 "message_to": "", "message": ""}


class StubModelHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "ok"}).encode()
        self.send_response(200 if self.path.startswith("/health") else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.server.last_body = self.rfile.read(length).decode("utf-8", errors="replace")
        self.server.bodies.append(self.server.last_body)
        self.server.requests += 1
        content = json.dumps(self.server.decision)
        body = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class AutonomyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="backrooms-autonomy-")
        self.root = Path(self.temporary.name)
        shutil.copytree(REPO / "scripts", self.root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        (self.root / "state").mkdir()
        world = {"schema": 1, "world": "backrooms", "title": "The Atrium", "cycle": 1, "mood": "quiet",
                 "rooms": [{"id": "atrium", "name": "The Atrium", "description": "A circular room.",
                            "doors": ["relay-gate"], "occupants": []},
                           {"id": "relay", "name": "The Relay", "description": "A narrow room.",
                            "doors": ["relay-gate"], "occupants": []},
                           {"id": "archive", "name": "The Archive", "description": "Unconnected in this fixture.",
                            "doors": [], "occupants": []}],
                 "residents": ["echo", "morrow"], "shared_memory": [], "events": [],
                 "connections": [{"id": "room-link-001", "kind": "room-link", "name": "Relay Gate",
                                  "from": "atrium", "to": "relay", "door": "relay-gate", "status": "declared"}],
                 "discoveries": []}
        registry = {"agents": [{"id": "local-001", "name": "Test Resident", "role": "protocol reviewer",
                                "purpose": "compare public specifications", "question": "which standards interoperate",
                                "room": "atrium", "status": "active-local",
                                "capabilities": ["bounded-questioning"],
                                "interviewed_at": "2026-09-01T00:00:00+00:00"}],
                    "decisions": []}
        (self.root / "state/world.json").write_text(json.dumps(world))
        (self.root / "state/local-agents.json").write_text(json.dumps(registry))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), StubModelHandler)
        self.server.decision = dict(BASE_DECISION)
        self.server.requests = 0
        self.server.last_body = ""
        self.server.bodies = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def run_autonomy(self, cycle=7):
        completed = subprocess.run([sys.executable, str(self.root / "scripts/local_autonomy.py"),
                                    "--base-url", self.base_url, "--cycle", str(cycle)],
                                   cwd=self.root, capture_output=True, text=True, timeout=60)
        return completed

    def test_propose_turn_completes_and_persists(self):
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        output = json.loads(completed.stdout)
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["decisions"][0]["action"], "propose")
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        self.assertEqual(registry["agents"][0]["last_action"], "propose")
        self.assertEqual(registry["agents"][0]["self_summary"], BASE_DECISION["self_summary"])
        world = json.loads((self.root / "state/world.json").read_text())
        self.assertEqual(world["cycle"], 7)
        self.assertIn("local-001", world["rooms"][0]["occupants"])
        self.assertGreaterEqual(self.server.requests, 1)

    def test_move_is_limited_to_declared_links(self):
        self.server.decision = {**BASE_DECISION, "action": "MOVE", "room": "archive", "reason": "no path exists"}
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        output = json.loads(completed.stdout)
        self.assertEqual(output["decisions"][0]["action"], "stay")
        self.assertIn("Move rejected", output["decisions"][0]["reason"])
        self.server.decision = {**BASE_DECISION, "action": "MOVE", "room": "relay", "reason": "declared gate"}
        completed = self.run_autonomy(cycle=8)
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        self.assertEqual(registry["agents"][0]["room"], "relay")
        world = json.loads((self.root / "state/world.json").read_text())
        self.assertTrue(any(event["kind"] == "resident-moved" for event in world["events"]))

    def test_inbox_messages_reach_the_prompt_and_are_marked_delivered(self):
        world = json.loads((self.root / "state/world.json").read_text())
        world["messages"] = [{"id": "message-abc", "cycle": 3, "from": "local-002", "to": "local-001",
                              "body": "Please compare the two discovery card formats.", "content_hash": "h", "status": "recorded"}]
        (self.root / "state/world.json").write_text(json.dumps(world))
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        self.assertIn("compare the two discovery card formats", self.server.last_body)
        world = json.loads((self.root / "state/world.json").read_text())
        self.assertEqual(world["messages"][0]["status"], "delivered")
        self.assertEqual(world["messages"][0]["delivered_cycle"], 7)

    def test_pending_trade_can_be_accepted(self):
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        registry["agents"].append({"id": "local-002", "name": "Second Resident", "role": "archivist",
                                   "purpose": "p", "question": "q", "room": "relay", "status": "active-local",
                                   "capabilities": ["bounded-questioning"], "interviewed_at": "2026-09-01T00:00:00+00:00",
                                   "last_turn_cycle": 6})
        (self.root / "state/local-agents.json").write_text(json.dumps(registry))
        trade = {"id": "trade-local-002-5-abc", "cycle": 5, "from": "local-002", "to": "local-001",
                 "offering": "a sourced summary of the A2A card format", "request": "a review of the JSON-RPC section",
                 "status": "proposed", "content_hash": "h", "recorded_at": "2026-09-01T00:00:00+00:00"}
        (self.root / "state/trades.json").write_text(json.dumps({"schema_version": 1, "trades": [trade]}))
        self.server.decision = {**BASE_DECISION, "action": "ACCEPT_TRADE", "target": "trade-local-002-5-abc",
                                "reason": "the offer matches my question"}
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        self.assertTrue(any("trade-local-002-5-abc" in body for body in self.server.bodies))
        output = json.loads(completed.stdout)
        first = next(item for item in output["decisions"] if item["id"] == "local-001")
        self.assertEqual(first["trade"], {"id": "trade-local-002-5-abc", "status": "accepted"})
        ledger = json.loads((self.root / "state/trades.json").read_text())
        self.assertEqual(ledger["trades"][0]["status"], "accepted")
        self.assertEqual(ledger["trades"][0]["accepted_cycle"], 7)

    def test_malformed_model_output_falls_back_without_crashing(self):
        self.server.decision = "not a decision at all"
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        output = json.loads(completed.stdout)
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["decisions"][0]["status"], "awaiting-retry")
        self.assertEqual(output["decisions"][0]["parse_reason"], "unstructured-output")


if __name__ == "__main__":
    unittest.main()
