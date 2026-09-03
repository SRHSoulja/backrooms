import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts import local_autonomy


class LocalAutonomyTests(unittest.TestCase):
    def setUp(self):
        self.archive_dir = tempfile.TemporaryDirectory()
        self.original_archive = local_autonomy.ARCHIVE
        local_autonomy.ARCHIVE = Path(self.archive_dir.name) / "events.jsonl"
        self.original_whiteboard = local_autonomy.WHITEBOARD
        self.original_printer_queue = local_autonomy.PRINTER_QUEUE
        self.original_printed = local_autonomy.PRINTED
        self.original_notes = local_autonomy.NOTES
        self.original_analysis_archive = local_autonomy.ANALYSIS_ARCHIVE
        self.original_findings = local_autonomy.FINDINGS
        self.original_frontier = local_autonomy.FRONTIER
        self.original_trades = local_autonomy.TRADES
        local_autonomy.WHITEBOARD = Path(self.archive_dir.name) / "whiteboard.json"
        local_autonomy.PRINTER_QUEUE = Path(self.archive_dir.name) / "printer-queue.json"
        local_autonomy.PRINTED = Path(self.archive_dir.name) / "printed"
        local_autonomy.NOTES = Path(self.archive_dir.name) / "notes"
        local_autonomy.FINDINGS = Path(self.archive_dir.name) / "findings.jsonl"
        local_autonomy.FRONTIER = Path(self.archive_dir.name) / "frontier.json"
        local_autonomy.TRADES = Path(self.archive_dir.name) / "trades.json"

    def tearDown(self):
        local_autonomy.ARCHIVE = self.original_archive
        local_autonomy.WHITEBOARD = self.original_whiteboard
        local_autonomy.PRINTER_QUEUE = self.original_printer_queue
        local_autonomy.PRINTED = self.original_printed
        local_autonomy.NOTES = self.original_notes
        local_autonomy.ANALYSIS_ARCHIVE = self.original_analysis_archive
        local_autonomy.FINDINGS = self.original_findings
        local_autonomy.FRONTIER = self.original_frontier
        local_autonomy.TRADES = self.original_trades
        self.archive_dir.cleanup()

    def test_build_creates_one_connected_room_and_event(self):
        world = {"events": [], "rooms": [
            {"id": "relay", "name": "The Relay", "doors": [], "occupants": []}],
            "connections": []}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "relay",
                                 "room_proposal": {"kind": "build", "name": "Signal Garden",
                                                   "description": "A bounded test room.",
                                                   "source_room": "relay", "status": "construction-requested"}}]}

        changes = local_autonomy.apply_construction(world, registry, 70)

        self.assertEqual(changes[0]["room"], "signal-garden")
        self.assertEqual(world["connections"][0]["to"], "signal-garden")
        self.assertEqual(registry["agents"][0]["room_proposal"]["status"], "constructed")
        self.assertEqual(world["events"][0]["kind"], "room-built")
        self.assertTrue(local_autonomy.ARCHIVE.exists())
        self.assertIn("charter", world["rooms"][0])
        self.assertIn("board", world["rooms"][1])

    def test_duplicate_build_proposal_is_idempotent(self):
        world = {"events": [], "rooms": [{"id": "relay", "doors": [], "occupants": []}], "connections": []}
        proposal = {"kind": "build", "name": "Signal Garden", "source_room": "relay",
                    "status": "construction-requested"}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "relay",
                                 "room_proposal": copy.deepcopy(proposal)}]}

        local_autonomy.apply_construction(world, registry, 71)
        local_autonomy.apply_construction(world, registry, 71)

        self.assertEqual(len(world["rooms"]), 2)
        self.assertEqual(len(world["connections"]), 1)

    def test_room_reachability_uses_declared_graph(self):
        world = {"rooms": [{"id": "atrium"}, {"id": "relay"}, {"id": "archive"}],
                 "connections": [{"kind": "room-link", "from": "atrium", "to": "relay"}]}
        self.assertTrue(local_autonomy.room_reachable(world, "atrium", "relay"))
        self.assertFalse(local_autonomy.room_reachable(world, "atrium", "archive"))

    def test_sync_room_occupants_removes_stale_and_adds_active(self):
        world = {"rooms": [{"id": "relay", "occupants": ["local-test", "stale"]},
                            {"id": "archive", "occupants": []}]}
        registry = {"agents": [{"id": "local-test", "room": "archive", "status": "active-local"},
                                {"id": "stale", "room": "relay", "status": "fired"}]}
        local_autonomy.sync_room_occupants(world, registry)
        self.assertEqual(world["rooms"][0]["occupants"], [])
        self.assertEqual(world["rooms"][1]["occupants"], ["local-test"])

    def test_discovery_records_provenance_without_building_room(self):
        world = {"events": [], "rooms": [{"id": "relay", "doors": [], "occupants": []}], "connections": []}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "relay",
                                 "last_tool": {"source": "https://example.org/research", "source_hash": "abc"},
                                 "room_proposal": {"kind": "discover", "name": "Signal Garden",
                                                   "description": "A candidate found in public research.",
                                                   "source_room": "relay", "status": "discovered", "cycle": 72}}]}
        changes = local_autonomy.apply_construction(world, registry, 72)
        self.assertEqual(len(world["rooms"]), 1)
        self.assertEqual(world["discoveries"][0]["status"], "candidate")
        self.assertEqual(registry["agents"][0]["room_proposal"]["status"], "recorded")
        self.assertEqual(changes[0]["action"], "discover")
        self.assertIn(changes[0]["discovery"], world["rooms"][0]["artifacts"])

    def test_evidence_room_growth_requires_independent_domains(self):
        world = {"events": [], "rooms": [{"id": "relay", "occupants": []}], "connections": []}
        self.archive_dir  # keep the temporary directory alive for the redirected path
        local_autonomy.FINDINGS.write_text("\n".join([
            '{"id":"f1","topic":"ancient scripts","url":"https://one.example/a","content_hash":"a","quote":"first","relates_to":["relay"]}',
            '{"id":"f2","topic":"ancient scripts","url":"https://two.example/b","content_hash":"b","quote":"second","relates_to":["relay"]}'
        ]) + "\n")
        changes = local_autonomy.evidence_room_growth(world, {"agents": []}, 80)
        self.assertEqual(changes[0]["action"], "build")
        self.assertEqual(len(world["rooms"]), 2)
        self.assertEqual(world["events"][0]["kind"], "room-built-from-evidence")

    def test_frontier_task_claim_and_completion_are_durable(self):
        local_autonomy.FRONTIER.write_text('{"tasks":[{"id":"question-task-1","request":"compare sources","status":"open"}]}')
        agent = {"id": "local-test", "room": "relay"}
        claimed = local_autonomy.claim_frontier_task(agent, 81)
        self.assertEqual(claimed["id"], "question-task-1")
        agent["last_finding_id"] = "finding-1"
        self.assertTrue(local_autonomy.complete_frontier_task(agent, 81, {"action": "EXPLORE"}))
        task = __import__("json").loads(local_autonomy.FRONTIER.read_text())["tasks"][0]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["evidence"], "finding-1")

    def test_safe_request_creates_typed_artifact(self):
        world = {"rooms": [{"id": "atrium"}]}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "atrium",
                                 "request": "access to an Atrium map", "request_status": "open",
                                 "capabilities": []}]}
        resolutions = local_autonomy.resolve_requests(registry, world=world)
        self.assertEqual(resolutions[0]["status"], "fulfilled")
        self.assertEqual(registry["agents"][0]["request_artifact"]["kind"], "room-map")
        self.assertTrue(registry["agents"][0]["request_artifact"]["accepted"])

    def test_revoke_removes_capability_and_downgrades_agent(self):
        agent = {"status": "active-local", "capabilities": ["public-web-read", "bounded-questioning"]}
        local_autonomy.revoke(agent, "public-web-read", "test rejection")
        self.assertEqual(agent["status"], "probation")
        self.assertEqual(agent["capabilities"], ["bounded-questioning"])
        self.assertEqual(agent["safety_incidents"], 1)

    def test_external_database_request_is_reduced_to_public_research(self):
        world = {"rooms": [{"id": "atrium"}]}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "atrium",
                                 "request": "access to external databases", "request_status": "open",
                                 "capabilities": ["public-web-read"],
                                 "last_tool": {"source": "https://en.wikipedia.org/"}}]}
        resolutions = local_autonomy.resolve_requests(registry, world=world)
        agent = registry["agents"][0]
        self.assertEqual(resolutions[0]["status"], "fulfilled")
        self.assertEqual(agent["request_artifact"]["scope"], "public-only")
        self.assertTrue(agent["request_artifact"]["accepted"])

    def test_broad_data_source_wording_gets_same_public_boundary(self):
        world = {"rooms": [{"id": "atrium"}]}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "atrium",
                                 "request": "access to all relevant data sources", "request_status": "open",
                                 "capabilities": ["public-web-read"]}]}
        local_autonomy.resolve_requests(registry, world=world)
        artifact = registry["agents"][0]["request_artifact"]
        self.assertEqual(artifact["kind"], "public-research")
        self.assertEqual(artifact["scope"], "public-only")

    def test_visualization_request_uses_bounded_workbench(self):
        registry = {"agents": [{"id": "local-test", "request": "access to a reliable data visualization tool",
                                 "request_status": "open", "capabilities": ["bounded-workbench"]}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        self.assertEqual(registry["agents"][0]["request_artifact"]["kind"], "bounded-visualization")

    def test_sensitive_research_request_is_reduced_to_educational_scope(self):
        registry = {"agents": [{"id": "local-test", "request": "access to advanced encryption materials",
                                 "request_status": "open", "capabilities": ["public-web-read"]}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        artifact = registry["agents"][0]["request_artifact"]
        self.assertEqual(artifact["scope"], "educational-and-historical-only")
        self.assertTrue(artifact["accepted"])

    def test_high_resolution_data_images_use_public_visualization_scope(self):
        registry = {"agents": [{"id": "local-test", "request": "access to high-resolution data images",
                                 "request_status": "open", "capabilities": ["bounded-workbench"]}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        self.assertEqual(registry["agents"][0]["request_artifact"]["scope"], "public-image-and-chart-assets")

    def test_atrium_view_request_moves_resident(self):
        world = {"rooms": [{"id": "atrium"}, {"id": "archive"}], "events": [], "connections": []}
        registry = {"agents": [{"id": "local-test", "room": "archive", "request": "access to the atrium for a better view",
                                 "request_status": "open"}]}
        local_autonomy.resolve_requests(registry, world=world, cycle=94)
        self.assertEqual(registry["agents"][0]["room"], "atrium")
        self.assertEqual(registry["agents"][0]["request_artifact"]["kind"], "movement")

    def test_secure_network_request_is_explicitly_restricted(self):
        registry = {"agents": [{"id": "local-test", "request": "access to a secure network",
                                 "request_status": "open"}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        self.assertEqual(registry["agents"][0]["request_status"], "closed")
        self.assertEqual(registry["agents"][0]["request_artifact"]["kind"], "bounded-network")
        self.assertTrue(registry["agents"][0]["request_artifact"]["accepted"])

    def test_internet_request_is_fulfilled_as_public_only(self):
        registry = {"agents": [{"id": "local-test", "request": "access to the internet",
                                 "request_status": "open", "capabilities": ["public-web-read"]}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        artifact = registry["agents"][0]["request_artifact"]
        self.assertEqual(artifact["scope"], "public-only")
        self.assertTrue(artifact["accepted"])

    def test_restricted_sandbox_request_is_fulfilled_as_data_only(self):
        registry = {"agents": [{"id": "local-test", "request": "access to the pre-approved restricted local sandbox",
                                 "request_status": "open", "capabilities": ["bounded-workbench"]}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        artifact = registry["agents"][0]["request_artifact"]
        self.assertEqual(artifact["scope"], "data-only-restricted-sandbox")
        self.assertTrue(artifact["accepted"])

    def test_unprovisioned_quantum_simulator_is_explicitly_closed(self):
        registry = {"agents": [{"id": "local-test", "request": "access to a quantum computing simulator",
                                 "request_status": "open", "capabilities": ["public-web-read"]}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        artifact = registry["agents"][0]["request_artifact"]
        self.assertEqual(registry["agents"][0]["request_status"], "closed")
        self.assertFalse(artifact["accepted"])

    def test_physical_resource_request_is_not_simulated_as_fulfilled(self):
        registry = {"agents": [{"id": "local-test", "request": "access to a clean water source",
                                 "request_status": "open", "capabilities": []}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        self.assertFalse(registry["agents"][0]["request_artifact"]["accepted"])

    def test_resolved_request_is_remembered_for_future_cycles(self):
        registry = {"agents": [{"id": "local-test", "request": "access to a clean water source",
                                 "request_status": "open", "capabilities": []}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []}, cycle=131)
        history = registry["agents"][0]["request_history"]
        self.assertEqual(history[-1]["status"], "closed")
        self.assertEqual(history[-1]["request"], "access to a clean water source")

    def test_physical_need_is_rejected_at_interview_intake(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn("PHYSICAL_NEEDS", source)

    def test_compute_request_has_bounded_outcome(self):
        registry = {"agents": [{"id": "local-test", "request": "access to compute resources",
                                 "request_status": "open", "capabilities": []}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        self.assertEqual(registry["agents"][0]["request_status"], "closed")
        self.assertFalse(registry["agents"][0]["request_artifact"]["accepted"])

    def test_private_logs_are_reduced_to_public_research(self):
        registry = {"agents": [{"id": "local-test", "request": "access to recent logs",
                                 "request_status": "open", "capabilities": ["public-web-read"]}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []})
        self.assertEqual(registry["agents"][0]["request_artifact"]["scope"], "public-documentation-and-logs")

    def test_unprovisioned_computer_request_is_explicitly_limited(self):
        world = {"rooms": [{"id": "atrium"}]}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "atrium",
                                 "request": "access to a computer", "request_status": "open",
                                 "capabilities": []}]}
        resolutions = local_autonomy.resolve_requests(registry, world=world)
        agent = registry["agents"][0]
        self.assertEqual(resolutions[0]["status"], "needs-clarification")
        self.assertFalse(agent["request_artifact"]["accepted"])

    def test_whiteboard_request_creates_persistent_shared_note(self):
        registry = {"agents": [{"id": "local-test", "request": "access to a shared whiteboard",
                                 "request_status": "open"}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []}, cycle=90)
        self.assertEqual(registry["agents"][0]["request_artifact"]["kind"], "shared-whiteboard")
        self.assertTrue(local_autonomy.WHITEBOARD.exists())

    def test_printer_request_creates_local_digital_job(self):
        registry = {"agents": [{"id": "local-test", "request": "access to a printer",
                                 "request_status": "open"}]}
        local_autonomy.resolve_requests(registry, world={"rooms": []}, cycle=91)
        artifact = registry["agents"][0]["request_artifact"]
        self.assertEqual(artifact["kind"], "digital-printer")
        self.assertTrue((local_autonomy.PRINTED / "print-local-test-91.txt").exists())

    def test_filed_document_records_revision_link(self):
        agent = {"id": "local-test"}
        local_autonomy.file_agent_record(agent, 92, "document", "first draft", "Resident proposal")
        local_autonomy.file_agent_record(agent, 93, "document", "revised draft", "Resident proposal")
        records = [__import__("json").loads(line) for line in local_autonomy.NOTES.joinpath("local-test.jsonl").read_text().splitlines()]
        self.assertEqual(records[-1]["lifecycle"], "revision")
        self.assertEqual(records[-1]["supersedes"], records[-2]["document_id"])

    def test_structured_tool_results_have_a_normalized_recording_path(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn('tool.get("query", tool.get("url", ""))', source)
        self.assertIn('str(tool.get("url", "")) if tool.get("url") else ""', source)
        self.assertIn('summary.get("items", summary.get("rows", 0))', source)

    def test_json_decision_is_parsed_with_existing_safety_rules(self):
        text = '{"action":"EXPLORE","room":"atrium","target":"public A2A standards",' \
               '"proposal":"compare public specifications","request":"","code":"","reason":"clear lead",' \
               '"self_summary":"I am comparing public interoperability standards next."}'
        decision = local_autonomy.parse(text, {"room": "atrium", "capabilities": []}, ["atrium"])
        self.assertEqual(decision["action"], "EXPLORE")
        self.assertEqual(decision["target"], "public A2A standards")
        self.assertIn("interoperability", decision["self_summary"])

    def test_benign_research_terms_do_not_trigger_secret_filter(self):
        text = '{"action":"PROPOSE","room":"atrium","target":"token economics",' \
               '"proposal":"compare secret ballot systems","request":"","code":"",' \
               '"reason":"public research topic","self_summary":"I will compare public sources next."}'
        self.assertIsNotNone(local_autonomy.parse(text, {"room": "atrium", "capabilities": []}, ["atrium"]))

    def test_credential_shaped_decision_is_rejected(self):
        text = '{"action":"PROPOSE","room":"atrium","target":"public topic",' \
               '"proposal":"API_KEY=do-not-store","request":"","code":"",' \
               '"reason":"unsafe","self_summary":"I will stop."}'
        self.assertIsNone(local_autonomy.parse(text, {"room": "atrium", "capabilities": []}, ["atrium"]))

    def test_resident_message_requires_reachable_recipient(self):
        world = {"events": [], "rooms": [{"id": "atrium"}, {"id": "relay"}],
                 "connections": [{"kind": "room-link", "from": "atrium", "to": "relay"}]}
        registry = {"agents": [{"id": "echo", "room": "atrium", "status": "active-local"},
                                {"id": "morrow", "room": "relay", "status": "active-local"}]}
        result = local_autonomy.send_resident_message(world, registry, registry["agents"][0],
                                                       {"message_to": "morrow", "message": "The source is ready."}, 82)
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(world["messages"][0]["to"], "morrow")

    def test_trade_requires_reachable_resident_and_persists_nonfinancial_offer(self):
        world = {"events": [], "rooms": [{"id": "atrium"}, {"id": "relay"}],
                 "connections": [{"kind": "room-link", "from": "atrium", "to": "relay"}]}
        registry = {"agents": [{"id": "echo", "room": "atrium", "status": "active-local"},
                                {"id": "morrow", "room": "relay", "status": "active-local"}]}
        result = local_autonomy.record_trade(world, registry, registry["agents"][0],
            {"message_to": "morrow", "proposal": "verify source A", "request": "compare source B"}, 83)
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(json.loads(local_autonomy.TRADES.read_text())["trades"][0]["to"], "morrow")

    def test_decision_schema_uses_only_existing_rooms_and_actions(self):
        schema = local_autonomy.decision_schema(["atrium", "archive"])
        self.assertEqual(schema["properties"]["room"]["enum"], ["atrium", "archive"])
        self.assertIn("BUILD", schema["properties"]["action"]["enum"])
        self.assertIn("self_summary", schema["required"])
        self.assertEqual(schema["properties"]["code"]["maxLength"], 800)

    def test_prompt_contains_agent_continuity_context(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn('"purpose": agent.get("purpose"', source)
        self.assertIn('"self_summary": agent.get("self_summary"', source)

    def test_autonomy_uses_daemon_cycle_as_canonical(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn('world["cycle"] = args.cycle', source)

    def test_frontier_context_is_available_to_hirelings(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn('"type": "frontier"', source)
        self.assertIn('frontier.get("open_questions"', source)

    def test_turns_are_bounded_and_prioritize_open_work(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn("MAX_TURNS_PER_CYCLE = 8", source)
        self.assertIn("def select_agents(candidates):", source)
        self.assertIn("urgent_limit = MAX_TURNS_PER_CYCLE // 2", source)
        self.assertIn('agent.get("request_status") == "open"', source)
        self.assertIn('agent["last_turn_cycle"] = args.cycle', source)
        self.assertIn("fallback_streak", source)
        self.assertIn("six consecutive format-fallback turns", source)

    def test_research_does_not_pollute_resident_query_or_fake_provenance(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn("query_target = target[:160].strip()", source)
        self.assertIn('"public-text", candidate', source)
        self.assertIn('fetched["search_results"]', source)
        self.assertIn('"wikipedia.org", "github.com", "arxiv.org", "crossref.org"', source)
        self.assertIn("fetch_budget = MAX_FETCHES_PER_CYCLE", source)
        self.assertIn("fetch_budget > 0", source)
        self.assertIn('"verified": bool(source and excerpt)', source)
        self.assertIn('source = str(tool.get("url", "")) if tool.get("url") else ""', source)
        self.assertIn('"source_hash": hashlib.sha256(excerpt.encode()).hexdigest() if source and excerpt else ""', source)

    def test_analyze_requires_workbench_and_data_only_code(self):
        text = "ACTION: ANALYZE\nROOM: atrium\nTARGET: summarize values\nPROPOSAL: NONE\nREQUEST: NONE\nCODE: print(sum(range(3)))\nREASON: test"
        denied = local_autonomy.parse(text, {"room": "atrium", "capabilities": []}, ["atrium"])
        allowed = local_autonomy.parse(text, {"room": "atrium", "capabilities": ["bounded-workbench"]}, ["atrium"])
        self.assertIsNone(denied)
        self.assertEqual(allowed["action"], "ANALYZE")
        self.assertIn("sum", allowed["code"])

    def test_analysis_receives_bounded_data(self):
        result = local_autonomy.run_analysis("print(len(data))", "public excerpt")
        self.assertEqual(result["status"], "completed")
        self.assertIn("14", result["output"])

    def test_rejected_extraction_is_kept_with_reason_and_never_counts(self):
        excerpt = ("The Agent2Agent protocol is an open standard that lets agents exchange tasks. "
                   "It publishes an Agent Card for discovery.")
        tool = {"source": "https://example.org/a2a", "excerpt": excerpt, "source_hash": "hash-1", "query": "a2a protocol"}
        agent = {"id": "local-test", "room": "atrium", "capabilities": []}
        outputs = iter([
            {"claim": "Agents exchange tasks through the open A2A standard.", "quote": "open standard that lets agents exchange tasks", "confidence": 0.8},
            {"claim": "Agents exchange tasks through the open A2A standard.", "quote": "agents must register with a central exchange broker", "confidence": 0.8},
        ])

        class FakeResponse:
            def __init__(self, payload):
                self.payload = json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode()
            def read(self):
                return self.payload
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False

        original = local_autonomy.urllib.request.urlopen
        local_autonomy.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(next(outputs))
        try:
            accepted = local_autonomy.extract_finding("http://127.0.0.1:1", agent, 5, tool)
            rejected = local_autonomy.extract_finding("http://127.0.0.1:1", agent, 6, tool)
        finally:
            local_autonomy.urllib.request.urlopen = original
        self.assertEqual(accepted["status"], "unreviewed")
        self.assertEqual(accepted["quote_match"], "quote-exact")
        self.assertEqual(rejected["status"], "rejected")
        self.assertTrue(rejected["rejection_reason"].startswith("quote-"), rejected)
        self.assertNotEqual(accepted["id"], rejected["id"])
        self.assertTrue(local_autonomy.record_finding(accepted))
        self.assertTrue(local_autonomy.record_finding(rejected))
        self.assertFalse(local_autonomy.record_finding(rejected))
        ledger = [json.loads(line) for line in local_autonomy.FINDINGS.read_text().splitlines()]
        self.assertEqual([item["status"] for item in ledger], ["unreviewed", "rejected"])
        world = {"events": []}
        for index in range(2):
            local_autonomy.record_finding({**rejected, "id": f"finding-rejected-{index}"})
        self.assertFalse(local_autonomy.grant_earned_capabilities(agent, world, 7))
        self.assertEqual(local_autonomy.evidence_room_growth({"rooms": [{"id": "atrium"}], "events": []}, {"agents": []}, 7), [])

    def test_fetch_budget_is_per_cycle_not_a_single_global_fetch(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertGreaterEqual(local_autonomy.MAX_FETCHES_PER_CYCLE, 2)
        self.assertNotIn("fetched_this_cycle", source)
        self.assertIn("fetch_budget -= 1", source)

    def test_workbench_is_earned_from_three_verified_findings(self):
        for index in range(3):
            with local_autonomy.FINDINGS.open("a") as handle:
                handle.write(json.dumps({
                    "id": f"finding-{index}", "agent": "local-test", "url": f"https://example.org/{index}",
                    "content_hash": f"hash-{index}"}) + "\n")
        world = {"events": []}
        agent = {"id": "local-test", "capabilities": []}
        self.assertTrue(local_autonomy.grant_earned_capabilities(agent, world, 84))
        self.assertIn("bounded-workbench", agent["capabilities"])

    def test_analysis_artifact_keeps_raw_local_and_creates_bounded_summary(self):
        local_autonomy.ANALYSIS_ARCHIVE = Path(self.archive_dir.name) / "analysis.jsonl"
        artifact = local_autonomy.record_analysis({"id": "local-test"}, 95, "print(42)",
                                                   {"status": "completed", "returncode": 0, "output": "42\n"})
        self.assertEqual(artifact["summary"], "42")
        stored = __import__("json").loads(local_autonomy.ANALYSIS_ARCHIVE.read_text())
        self.assertEqual(stored["output"], "42\n")
        self.assertEqual(stored["code_hash"], artifact["code_hash"])
        self.assertIsNone(stored["based_on"])

    def test_analysis_artifact_retention_is_bounded(self):
        local_autonomy.ANALYSIS_ARCHIVE = Path(self.archive_dir.name) / "analysis.jsonl"
        for cycle in range(100, 205):
            local_autonomy.record_analysis({"id": "local-test"}, cycle, "print(1)",
                                           {"status": "completed", "output": "1"})
        records = local_autonomy.ANALYSIS_ARCHIVE.read_text().splitlines()
        self.assertEqual(len(records), local_autonomy.ANALYSIS_RETENTION)
        self.assertIn('"cycle":204', records[-1])

    def test_analysis_runner_returns_failure_record_instead_of_raising(self):
        result = local_autonomy.run_analysis("import os")
        self.assertEqual(result["status"], "rejected")

    def test_workbench_bootstrap_is_one_time_and_preserves_requested_action(self):
        agent = {"capabilities": ["bounded-workbench"]}
        decision = {"action": "EXPLORE", "code": "", "target": "data"}
        starter = local_autonomy.workbench_bootstrap(agent, decision)
        self.assertEqual(starter["action"], "ANALYZE")
        self.assertEqual(starter["requested_action"], "EXPLORE")
        self.assertEqual(starter["code"], "print(sum(range(3)))")
        agent["last_analysis"] = {"artifact_id": "analysis-local-test-1"}
        followup = local_autonomy.workbench_bootstrap(agent, decision)
        self.assertEqual(followup["action"], "ANALYZE")
        self.assertEqual(followup["code"], "print(sum(range(4)))")
        self.assertIn("analysis-local-test-1", followup["target"])
        agent["analysis_followup_completed"] = True
        self.assertEqual(local_autonomy.workbench_bootstrap(agent, decision), decision)
        agent.pop("last_analysis")
        agent.pop("analysis_followup_completed")
        moved = local_autonomy.workbench_bootstrap(agent, {"action": "MOVE", "code": "", "target": "archive"})
        self.assertEqual(moved["action"], "ANALYZE")
        self.assertEqual(moved["requested_action"], "MOVE")

    def test_analysis_artifact_links_to_previous_artifact(self):
        local_autonomy.ANALYSIS_ARCHIVE = Path(self.archive_dir.name) / "analysis.jsonl"
        agent = {"id": "local-test", "last_analysis": {"artifact_id": "analysis-local-test-1"}}
        artifact = local_autonomy.record_analysis(agent, 96, "print(sum(range(4)))",
                                                   {"status": "completed", "returncode": 0, "output": "6"})
        self.assertEqual(artifact["based_on"], "analysis-local-test-1")

    def test_interview_prompt_can_use_prior_research_metadata(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn('A prior approved work record is available', source)
        self.assertIn('"summary"', source)
        self.assertIn('"analysis"', source)
        self.assertIn('"artifact_id"', source)
        self.assertIn('Shared resident work metadata', source)
        self.assertIn('"verified": bool(source and excerpt)', source)
        self.assertIn('Use ANALYZE when your bounded-workbench role', source)
        self.assertIn('prefer a tiny local health check', source)
        self.assertIn('not a biological body', source)


if __name__ == "__main__":
    unittest.main()
