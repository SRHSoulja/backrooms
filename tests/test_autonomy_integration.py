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


FAKE_BROKER = """#!/usr/bin/env python3
import json, sys
from pathlib import Path
tool, value = sys.argv[1], sys.argv[2]
log = Path(__file__).resolve().parents[1] / "state/broker-calls.jsonl"
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a") as handle:
    handle.write(json.dumps({"tool": tool, "value": value}) + "\\n")
if tool == "public-search":
    print(json.dumps({"tool": "public-search", "query": value, "status": "completed", "source": "https://search.example/",
                      "results": [{"title": "A2A spec", "url": "https://spec.example/a2a"}],
                      "contract": {"capability": "public-web-read"}}))
elif tool == "wikipedia-summary":
    if "no-wiki" in value:
        print(json.dumps({"tool": "wikipedia-summary", "query": value, "status": "no-match", "source": "https://en.wikipedia.org/", "contract": {}}))
    else:
        print(json.dumps({"tool": "wikipedia-summary", "query": value, "title": "Agent card", "url": "https://en.wikipedia.org/wiki/Agent_card", "status": "completed",
                          "excerpt": "An agent card is a public discovery document. It publishes an Agent Card for discovery.",
                          "contract": {"capability": "public-text-read", "untrusted_content": True}}))
elif tool == "arxiv-summary":
    print(json.dumps({"tool": "arxiv-summary", "query": value, "title": "Agent cards", "url": "https://arxiv.org/abs/2401.00001v1", "status": "completed",
                      "excerpt": "Agent cards. We show that an agent card is a public discovery document. It publishes an Agent Card for discovery.",
                      "contract": {"capability": "public-text-read", "untrusted_content": True}}))
elif tool == "github-readme":
    print(json.dumps({"tool": "github-readme", "query": value, "title": "acme/cards", "url": "https://github.com/acme/cards", "status": "completed",
                      "excerpt": "acme/cards: discovery cards. It publishes an Agent Card for discovery.",
                      "contract": {"capability": "public-text-read", "untrusted_content": True}}))
elif tool == "public-text":
    print(json.dumps({"tool": "public-text", "url": value, "status": "completed",
                      "excerpt": "The Agent2Agent protocol is an open standard that lets agents exchange tasks. It publishes an Agent Card for discovery.",
                      "contract": {"capability": "public-text-read", "untrusted_content": True}}))
else:
    print(json.dumps({"tool": tool, "status": "rejected", "reason": "fake broker supports search and text only", "contract": {}}))
"""

EXTRACTION = {"claim": "The A2A protocol publishes an Agent Card for discovery.",
              "quote": "It publishes an Agent Card for discovery.", "confidence": 0.8}
JUDGMENT = {"relation": "supports", "reason": "both describe agent card discovery"}
POST_TOOL = {**{"action": "STAY", "room": "atrium", "target": "", "proposal": "", "request": "", "code": "",
               "reason": "evidence observed", "self_summary": "I fetched the spec.", "message_to": "", "message": ""}}


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
        try:
            prompt = json.loads(self.server.last_body)["messages"][-1]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            prompt = ""
        if "Extract one cautious" in prompt:
            reply = EXTRACTION
        elif "Two findings were extracted" in prompt:
            reply = JUDGMENT
        elif "post-tool decision" in prompt:
            reply = POST_TOOL
        else:
            reply = self.server.decision
        content = json.dumps(reply)
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
        (self.root / "scripts/tool_broker.py").write_text(FAKE_BROKER)
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

    def run_autonomy(self, cycle=7, question=""):
        completed = subprocess.run([sys.executable, str(self.root / "scripts/local_autonomy.py"),
                                    "--base-url", self.base_url, "--cycle", str(cycle), "--question", question],
                                   cwd=self.root, capture_output=True, text=True, timeout=90)
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

    def test_explore_turn_keeps_the_query_clean_and_files_a_verified_finding(self):
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        registry["agents"].append({"id": "local-002", "name": "Second Resident", "role": "archivist",
                                   "purpose": "p", "question": "q", "room": "relay", "status": "active-local",
                                   "capabilities": ["bounded-questioning"], "interviewed_at": "2026-09-01T00:00:00+00:00"})
        (self.root / "state/local-agents.json").write_text(json.dumps(registry))
        self.server.decision = {**BASE_DECISION, "action": "EXPLORE", "target": "agent card discovery no-wiki", "reason": "lead"}
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        output = json.loads(completed.stdout)
        calls = [json.loads(line) for line in (self.root / "state/broker-calls.jsonl").read_text().splitlines()]
        self.assertEqual([call["value"] for call in calls if call["tool"] == "public-search"],
                         ["agent card discovery no-wiki", "agent card discovery no-wiki"])
        self.assertEqual(sum(call["tool"] == "wikipedia-summary" for call in calls), 2)
        self.assertEqual(sum(call["tool"] == "public-text" for call in calls), 2)
        # turn 0 and 1 (encyclopedia family, no article) fall back to web fetches
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        tool = registry["agents"][0]["last_tool"]
        self.assertEqual((tool["query"], tool["source"], tool["verified"]), ("agent card discovery no-wiki", "https://spec.example/a2a", True))
        self.assertEqual(len(tool["source_hash"]), 64)
        ledger = [json.loads(line) for line in (self.root / "state/findings.jsonl").read_text().splitlines()]
        self.assertEqual([item["status"] for item in ledger], ["unreviewed", "unreviewed"])
        self.assertEqual(ledger[0]["quote_match"], "quote-exact")
        first = next(item for item in output["decisions"] if item["id"] == "local-001")
        self.assertTrue(first["finding_id"].startswith("finding-"))
        self.assertEqual(first["action"], "explore")
        self.assertEqual(first["decision_source"], "model")
        self.assertIsNone(first["fallback_reason"])
        world = json.loads((self.root / "state/world.json").read_text())
        kinds = [event["kind"] for event in world["events"]]
        self.assertIn("finding-filed", kinds)
        self.assertIn("tool-used", kinds)
        self.assertEqual(output["corroborations"], [])

    def test_encyclopedic_summary_is_preferred_when_it_matches(self):
        self.server.decision = {**BASE_DECISION, "action": "EXPLORE", "target": "agent card discovery", "reason": "lead"}
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        calls = [json.loads(line) for line in (self.root / "state/broker-calls.jsonl").read_text().splitlines()]
        self.assertEqual([call["tool"] for call in calls], ["public-search", "wikipedia-summary"])
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        tool = registry["agents"][0]["last_tool"]
        self.assertEqual((tool["tool"], tool["source"], tool["verified"]), ("wikipedia-summary", "https://en.wikipedia.org/wiki/Agent_card", True))
        ledger = [json.loads(line) for line in (self.root / "state/findings.jsonl").read_text().splitlines()]
        self.assertEqual(ledger[0]["url"], "https://en.wikipedia.org/wiki/Agent_card")
        self.assertEqual(ledger[0]["status"], "unreviewed")

    def test_shared_council_question_yields_a_judged_pair_and_an_evidence_room(self):
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        for index in range(2, 5):
            registry["agents"].append({"id": f"local-00{index}", "name": f"Resident {index}", "role": "researcher",
                                       "purpose": "p", "question": "q", "room": "atrium", "status": "active-local",
                                       "capabilities": ["bounded-questioning"], "interviewed_at": "2026-09-01T00:00:00+00:00"})
        (self.root / "state/local-agents.json").write_text(json.dumps(registry))
        self.server.decision = {**BASE_DECISION, "action": "EXPLORE", "target": "agent card discovery", "reason": "lead"}
        question = "How do public agent discovery cards enable interoperability between agents?"
        completed = self.run_autonomy(question=question)
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        output = json.loads(completed.stdout)
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        assignments = [agent["research_assignment"] for agent in registry["agents"]]
        self.assertEqual([item["origin"] for item in assignments],
                         ["council-question", "resident-target", "council-question", "resident-target"])
        self.assertEqual([item["source_preference"] for item in assignments],
                         ["encyclopedia", "encyclopedia", "papers", "papers"])
        self.assertEqual(assignments[0]["query"], "agent discovery cards interoperability agents")
        sources = [item["decision_source"] for item in sorted(output["decisions"], key=lambda item: item["id"])]
        self.assertEqual(sources, ["scheduler", "model", "scheduler", "model"])
        decision_prompts = [body for body in self.server.bodies if "hireling_decision" in body]
        self.assertEqual(len(decision_prompts), 2)
        ledger = [json.loads(line) for line in (self.root / "state/findings.jsonl").read_text().splitlines()]
        council_domains = {item["url"].split("/")[2] for item in ledger if item["topic"] == assignments[0]["query"]}
        self.assertEqual(council_domains, {"en.wikipedia.org", "arxiv.org"})
        self.assertEqual(output["corroborations"][0]["relation"], "supports")
        self.assertEqual([item["action"] for item in output["construction"]], ["build"])
        self.assertEqual(output["construction"][0]["corroboration"], output["corroborations"][0]["id"])
        world = json.loads((self.root / "state/world.json").read_text())
        self.assertEqual(len(world["rooms"]), 4)
        new_room = world["rooms"][-1]
        self.assertEqual(new_room["founded_by"], ["local-001", "local-003"])
        self.assertEqual(new_room["founded_via"], "evidence-ledger")
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        standing = {agent["id"]: agent["standing"] for agent in registry["agents"]}
        self.assertGreaterEqual(standing["local-001"]["corroborated"], 1)
        self.assertGreaterEqual(standing["local-001"]["score"], 5.0)
        self.assertEqual(len(new_room["artifacts"]), 2)
        self.assertTrue(any(link["to"] == new_room["id"] and link["from"] == "atrium" for link in world["connections"]))
        kinds = [event["kind"] for event in world["events"]]
        self.assertIn("findings-corroborated", kinds)
        self.assertIn("room-built-from-evidence", kinds)

    def test_completed_task_is_printed_and_pinned_with_real_content(self):
        (self.root / "state/frontier.json").write_text(json.dumps({
            "open_questions": [], "findings": [], "contradictions": [], "activity": [], "leads": [],
            "tasks": [{"id": "question-task-9", "agent": None, "room": None,
                       "request": "Which specifications define agent discovery documents?", "status": "open"}]}))
        self.server.decision = {**BASE_DECISION, "action": "EXPLORE", "target": "agent card discovery", "reason": "lead"}
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        frontier = json.loads((self.root / "state/frontier.json").read_text())
        self.assertEqual(frontier["tasks"][0]["status"], "completed")
        self.assertTrue(frontier["tasks"][0]["evidence"].startswith("finding-"))
        jobs = json.loads((self.root / "state/printer-queue.json").read_text())["jobs"]
        self.assertEqual(jobs[-1]["title"], "Completed frontier task")
        self.assertIn("Which specifications define agent discovery documents?", jobs[-1]["preview"])
        self.assertIn("Finding: The A2A protocol publishes an Agent Card for discovery.", jobs[-1]["preview"])
        printed = (self.root / "state/printed" / f"{jobs[-1]['id']}.txt").read_text()
        self.assertIn("Source: https://en.wikipedia.org/wiki/Agent_card", printed)
        board = json.loads((self.root / "state/whiteboard.json").read_text())["entries"]
        self.assertEqual(board[-1]["title"], "Completed task")
        self.assertIn("Finding:", board[-1]["body"])

    def test_frontier_question_and_outside_lead_reach_the_prompt(self):
        (self.root / "state/frontier.json").write_text(json.dumps({
            "open_questions": [{"id": "frontier-question-3", "cycle": 3, "source": "council",
                                "question": "Which two public sources describe agent card discovery?", "status": "open"}],
            "findings": [], "contradictions": [], "tasks": [], "activity": [],
            "leads": [{"id": "lead-codex-1", "source": "codex-review", "question_id": "frontier-question-3",
                       "text": "Outside review says compare the two card formats.", "status": "unverified", "cycle": 3}]}))
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        self.assertTrue(any("describe agent card discovery" in body for body in self.server.bodies))
        self.assertTrue(any("Outside review says compare" in body for body in self.server.bodies))
        self.assertTrue(any("untrusted_outside_leads" in body for body in self.server.bodies))

    def test_physical_need_request_is_classified_at_intake(self):
        self.server.decision = {**BASE_DECISION, "request": "clean water and a place to sleep"}
        completed = self.run_autonomy()
        self.assertEqual(completed.returncode, 0, completed.stderr[-1500:])
        registry = json.loads((self.root / "state/local-agents.json").read_text())
        agent = registry["agents"][0]
        self.assertEqual(agent["request_status"], "closed")
        self.assertEqual(agent["request_artifact"]["kind"], "model-confusion")

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
