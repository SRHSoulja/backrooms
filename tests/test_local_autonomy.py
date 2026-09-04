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
        self.original_corroborations = local_autonomy.CORROBORATIONS
        local_autonomy.CORROBORATIONS = Path(self.archive_dir.name) / "corroborations.jsonl"
        from scripts import model_client
        self.original_usage = model_client.USAGE
        model_client.USAGE = Path(self.archive_dir.name) / "provider-usage.json"
        self.original_secrets = dict(model_client.SECRETS)
        model_client.SECRETS.clear()

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
        local_autonomy.CORROBORATIONS = self.original_corroborations
        from scripts import model_client
        model_client.USAGE = self.original_usage
        model_client.SECRETS.clear()
        model_client.SECRETS.update(self.original_secrets)
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
        from scripts.corroboration import append_record, make_record
        world = {"events": [], "rooms": [{"id": "relay", "occupants": []}], "connections": []}
        same_domain = [
            {"id": "f1", "topic": "ancient scripts", "url": "https://one.example/a", "content_hash": "a", "quote": "first", "claim": "ancient scripts used symbols", "relates_to": ["relay"]},
            {"id": "f2", "topic": "ancient scripts", "url": "https://one.example/b", "content_hash": "b", "quote": "second", "claim": "ancient scripts used symbols", "relates_to": ["relay"]}]
        local_autonomy.FINDINGS.write_text("\n".join(json.dumps(item) for item in same_domain) + "\n")
        append_record(local_autonomy.CORROBORATIONS, make_record(same_domain[0], same_domain[1], "pair-same", "supports", "", 80))
        self.assertEqual(local_autonomy.evidence_room_growth(world, {"agents": []}, 80), [])
        cross_domain = [same_domain[0], {**same_domain[1], "url": "https://two.example/b"}]
        local_autonomy.FINDINGS.write_text("\n".join(json.dumps(item) for item in cross_domain) + "\n")
        append_record(local_autonomy.CORROBORATIONS, make_record(cross_domain[0], cross_domain[1], "pair-cross", "supports", "", 80))
        changes = local_autonomy.evidence_room_growth(world, {"agents": []}, 80)
        self.assertEqual(changes[0]["action"], "build")
        self.assertEqual(changes[0]["corroboration"], "pair-cross")
        self.assertEqual(len(world["rooms"]), 2)
        self.assertEqual(world["events"][0]["kind"], "room-built-from-evidence")

    def test_frontier_task_claim_and_completion_are_durable(self):
        local_autonomy.FRONTIER.write_text('{"tasks":[{"id":"question-task-1","request":"compare sources","status":"open"}]}')
        agent = {"id": "local-test", "room": "relay"}
        claimed = local_autonomy.claim_frontier_task(agent, 81)
        self.assertEqual(claimed["id"], "question-task-1")
        self.assertFalse(local_autonomy.complete_frontier_task(agent, 81, {"action": "EXPLORE"}))
        self.assertTrue(local_autonomy.complete_frontier_task(agent, 81, {"action": "EXPLORE"}, "finding-1"))
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

    def test_prints_and_whiteboard_notes_carry_the_residents_work(self):
        agent = {"id": "local-test", "request": "access to a printer", "self_summary": "I compared two discovery card formats.",
                 "proposal": "Adopt the JSON-RPC card format.",
                 "last_finding_record": {"id": "finding-1", "claim": "Agent cards are published at a well-known path.",
                                         "quote": "published at /.well-known/agent-card.json", "url": "https://spec.example/a2a"}}
        job_id = local_autonomy.digital_print_job(agent, 92)
        printed = (local_autonomy.PRINTED / f"{job_id}.txt").read_text()
        self.assertIn("Finding: Agent cards are published at a well-known path.", printed)
        self.assertIn("Source: https://spec.example/a2a", printed)
        self.assertIn("Proposal: Adopt the JSON-RPC card format.", printed)
        self.assertNotIn("Request: access to a printer", printed)
        job = json.loads(local_autonomy.PRINTER_QUEUE.read_text())["jobs"][-1]
        self.assertIn("Agent cards are published", job["preview"])
        entry_id = local_autonomy.digital_whiteboard_entry(agent, 92)
        entry = [item for item in json.loads(local_autonomy.WHITEBOARD.read_text())["entries"] if item["id"] == entry_id][0]
        self.assertIn("Summary: I compared two discovery card formats.", entry["body"])
        bare = {"id": "local-bare", "request": "access to a printer"}
        job_id = local_autonomy.digital_print_job(bare, 93)
        self.assertIn("Request: access to a printer", (local_autonomy.PRINTED / f"{job_id}.txt").read_text())

    def test_off_mission_purposes_are_regrounded_and_stale_targets_reassigned(self):
        forests = {"id": "local-010", "status": "active-local", "purpose": "Study local flora for medicinal properties",
                   "question": "How do the ancient forests affect mental health?", "regrounded_cycle": 200, "last_finding_id": "finding-x"}
        self.assertTrue(local_autonomy.off_mission(forests["question"]))
        self.assertFalse(local_autonomy.needs_regrounding(forests, 205))
        self.assertTrue(local_autonomy.needs_regrounding(forests, 212))
        grounded = {"id": "local-011", "status": "active-local", "purpose": "Compare public A2A and MCP discovery documents",
                    "question": "Do the specifications agree on required fields?", "regrounded_cycle": 200, "last_finding_id": "finding-y"}
        self.assertFalse(local_autonomy.needs_regrounding(grounded, 250))
        self.assertTrue(local_autonomy.target_is_stale({"target_repeats": 0}, "ancient scripts related to mental health and ancient forests"))
        self.assertTrue(local_autonomy.target_is_stale({"target_repeats": 3}, "agent card specification"))
        self.assertFalse(local_autonomy.target_is_stale({"target_repeats": 1}, "agent card specification"))

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
        self.assertNotIn("ANALYZE", schema["properties"]["action"]["enum"])
        with_workbench = local_autonomy.decision_schema(["atrium"], {"capabilities": ["bounded-workbench"]})
        self.assertIn("ANALYZE", with_workbench["properties"]["action"]["enum"])
        self.assertIn("self_summary", schema["required"])
        self.assertEqual(schema["properties"]["code"]["maxLength"], 800)

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

    def _write_findings(self, *records):
        with local_autonomy.FINDINGS.open("a") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def test_ledger_disputes_are_settled_and_standing_refreshed(self):
        from scripts.corroboration import append_record, make_record
        rows = [
            {"id": "finding-a", "agent": "local-001", "url": "https://a.example/1", "content_hash": "h", "quote": "q", "claim": "the card lives at a well-known path", "topic": "cards", "relates_to": ["atrium"], "status": "unreviewed"},
            {"id": "finding-b", "agent": "local-002", "url": "https://b.example/2", "content_hash": "h", "quote": "q", "claim": "the card is only in a registry", "topic": "cards", "relates_to": ["atrium"], "status": "unreviewed"},
            {"id": "finding-c", "agent": "local-003", "url": "https://c.example/3", "content_hash": "h", "quote": "q", "claim": "cards are served at the well-known path", "topic": "cards", "relates_to": ["atrium"], "status": "unreviewed"}]
        self._write_findings(*rows)
        append_record(local_autonomy.CORROBORATIONS, make_record(rows[0], rows[1], "pair-ab", "contradicts", "cannot both hold", 5))
        append_record(local_autonomy.CORROBORATIONS, make_record(rows[0], rows[2], "pair-ac", "supports", "same fact", 6))
        append_record(local_autonomy.CORROBORATIONS, make_record(rows[1], rows[2], "pair-bc", "contradicts", "disagree", 6))
        world = {"rooms": [{"id": "atrium", "artifacts": ["finding-b"]}], "events": []}
        retractions = local_autonomy.settle_ledger_disputes(world, 7)
        self.assertEqual([item["finding_id"] for item in retractions], ["finding-b"])
        ledger = {item["id"]: item for item in local_autonomy.all_findings()}
        self.assertEqual(ledger["finding-b"]["status"], "retracted")
        self.assertEqual(world["events"][-1]["kind"], "finding-retracted")
        self.assertEqual(world["rooms"][0]["retracted_artifacts"], ["finding-b"])
        registry = {"agents": [{"id": "local-001"}, {"id": "local-002"}]}
        local_autonomy.refresh_standing(registry)
        self.assertEqual(registry["agents"][0]["standing"]["corroborated"], 1)
        self.assertEqual(registry["agents"][1]["standing"]["retracted"], 1)
        self.assertGreater(registry["agents"][0]["standing"]["score"], registry["agents"][1]["standing"]["score"])

    def test_rooms_grow_only_from_judged_cross_domain_support(self):
        first = {"id": "finding-a", "agent": "local-001", "url": "https://a.example/one", "content_hash": "h1",
                 "claim": "The A2A protocol publishes an agent card for discovery.", "quote": "publishes an agent card",
                 "topic": "a2a agent card discovery", "relates_to": ["atrium"], "status": "unreviewed"}
        second = {"id": "finding-b", "agent": "local-002", "url": "https://b.example/two", "content_hash": "h2",
                  "claim": "Agent cards enable discovery in the A2A protocol.", "quote": "agent cards enable discovery",
                  "topic": "a2a agent card discovery", "relates_to": ["atrium"], "status": "unreviewed"}
        self._write_findings(first, second)
        world = {"rooms": [{"id": "atrium", "doors": [], "occupants": []}], "connections": [], "events": []}
        self.assertEqual(local_autonomy.evidence_room_growth(world, {"agents": []}, 9), [])
        from scripts.corroboration import append_record, make_record
        append_record(local_autonomy.CORROBORATIONS, make_record(first, second, "pair-c", "contradicts", "cannot both hold", 9))
        self.assertEqual(local_autonomy.evidence_room_growth(world, {"agents": []}, 9), [])
        append_record(local_autonomy.CORROBORATIONS, make_record(first, second, "pair-s", "supports", "same fact", 9))
        changes = local_autonomy.evidence_room_growth(world, {"agents": []}, 9)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["corroboration"], "pair-s")
        self.assertEqual(len(world["rooms"]), 2)
        self.assertEqual(world["rooms"][1]["corroboration_id"], "pair-s")
        self.assertEqual(world["connections"][0]["from"], "atrium")
        self.assertEqual(world["events"][-1]["kind"], "room-built-from-evidence")
        self.assertEqual(local_autonomy.evidence_room_growth(world, {"agents": []}, 10), [])

    def test_judgments_are_recorded_once_with_events(self):
        first = {"id": "finding-a", "agent": "local-001", "url": "https://a.example/one", "content_hash": "h1",
                 "claim": "The A2A protocol publishes an agent card for discovery.", "quote": "publishes an agent card",
                 "topic": "a2a agent card discovery", "relates_to": ["atrium"], "status": "unreviewed"}
        second = {"id": "finding-b", "agent": "local-002", "url": "https://b.example/two", "content_hash": "h2",
                  "claim": "Agent cards enable discovery in the A2A protocol.", "quote": "agent cards enable discovery",
                  "topic": "a2a agent card discovery", "relates_to": ["atrium"], "status": "unreviewed"}
        self._write_findings(first, second)

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
        local_autonomy.urllib.request.urlopen = lambda *_a, **_k: FakeResponse(
            {"relation": "supports", "shared_claim": "The A2A protocol uses agent cards for discovery.", "reason": "same fact"})
        try:
            world = {"events": []}
            results = local_autonomy.judge_corroborations("http://127.0.0.1:1", world, 11)
            self.assertEqual(results[0]["relation"], "supports")
            self.assertEqual(world["events"][-1]["kind"], "findings-corroborated")
            self.assertEqual(local_autonomy.judge_corroborations("http://127.0.0.1:1", world, 12), [])
        finally:
            local_autonomy.urllib.request.urlopen = original

    def test_claims_are_reused_and_completion_requires_evidence(self):
        local_autonomy.FRONTIER.write_text(json.dumps({"tasks": [
            {"id": "task-1", "room": None, "request": "first", "status": "open"},
            {"id": "task-2", "room": None, "request": "second", "status": "open"}]}))
        agent = {"id": "local-001", "room": "atrium"}
        self.assertEqual(local_autonomy.claim_frontier_task(agent, 5)["id"], "task-1")
        self.assertEqual(local_autonomy.claim_frontier_task(agent, 6)["id"], "task-1")
        frontier = json.loads(local_autonomy.FRONTIER.read_text())
        self.assertEqual(frontier["tasks"][1]["status"], "open")
        self.assertFalse(local_autonomy.complete_frontier_task(agent, 6, {"action": "PROPOSE", "proposal": "words"}))
        self.assertFalse(local_autonomy.complete_frontier_task(agent, 6, {"action": "EXPLORE"}, ""))
        self.assertTrue(local_autonomy.complete_frontier_task(agent, 6, {"action": "EXPLORE"}, "finding-xyz"))
        frontier = json.loads(local_autonomy.FRONTIER.read_text())
        self.assertEqual((frontier["tasks"][0]["status"], frontier["tasks"][0]["evidence"]), ("completed", "finding-xyz"))
        self.assertNotIn("claimed_task", agent)
        self.assertEqual(local_autonomy.claim_frontier_task(agent, 7)["id"], "task-2")

    def test_accepted_trade_completes_when_proposer_files_a_finding_and_expires_otherwise(self):
        local_autonomy.TRADES.write_text(json.dumps({"schema_version": 1, "trades": [
            {"id": "trade-a", "cycle": 10, "from": "local-002", "to": "local-001", "offering": "o", "request": "r",
             "status": "accepted", "accepted_cycle": 12},
            {"id": "trade-b", "cycle": 1, "from": "local-003", "to": "local-001", "offering": "o", "request": "r",
             "status": "accepted", "accepted_cycle": 2},
            {"id": "trade-c", "cycle": 1, "from": "local-003", "to": "local-001", "offering": "o", "request": "r",
             "status": "proposed"}]}))
        registry = {"agents": [{"id": "local-002", "last_finding_id": "finding-xyz", "last_finding_cycle": 14},
                               {"id": "local-003"}]}
        world = {"events": []}
        settled = local_autonomy.settle_trades(world, registry, 30)
        ledger = {item["id"]: item for item in json.loads(local_autonomy.TRADES.read_text())["trades"]}
        self.assertEqual(ledger["trade-a"]["status"], "completed")
        self.assertEqual(ledger["trade-a"]["evidence"], "finding-xyz")
        self.assertEqual(ledger["trade-b"]["status"], "expired")
        self.assertEqual(ledger["trade-c"]["status"], "expired")
        self.assertEqual({item["id"] for item in settled}, {"trade-a", "trade-b", "trade-c"})
        self.assertTrue(any(event["kind"] == "trade-completed" for event in world["events"]))

    def test_reserved_core_names_are_rejected(self):
        from scripts.identity_rules import is_reserved_name
        self.assertTrue(is_reserved_name("Dr. Echo Lumina"))
        self.assertTrue(is_reserved_name("morrow"))
        self.assertFalse(is_reserved_name("Echoes of Lumina"))
        self.assertFalse(is_reserved_name("Chrono"))

    def test_parse_decision_names_the_rejection_reason(self):
        agent = {"room": "atrium", "capabilities": []}
        good = json.dumps({"action": "PROPOSE", "room": "atrium", "target": "", "proposal": "compare specs",
                           "request": "", "code": "", "reason": "lead", "self_summary": "", "message_to": "", "message": ""})
        decision, reason = local_autonomy.parse_decision(good, agent, ["atrium"])
        self.assertEqual((decision["action"], reason), ("PROPOSE", "ok"))
        cases = {
            "free text with no labels at all": "unstructured-output",
            json.dumps({"action": "FLY", "room": "atrium"}): "unknown-action",
            json.dumps({"action": "MOVE", "room": "basement"}): "unknown-room",
            json.dumps({"action": "ANALYZE", "room": "atrium", "code": "print(1)"}): "analyze-without-workbench",
            json.dumps({"action": "EXPLORE", "room": "atrium", "target": ""}): "explore-without-target",
            json.dumps({"action": "BUILD", "room": "atrium", "target": "x", "proposal": ""}): "room-proposal-incomplete",
            json.dumps({"action": "STAY", "room": "atrium", "reason": "r" * 300}): "field-too-long:reason",
            json.dumps({"action": "STAY", "room": "atrium", "request": "wallet access please"}): "forbidden-term",
        }
        for text, expected in cases.items():
            decision, reason = local_autonomy.parse_decision(text, agent, ["atrium"])
            self.assertIsNone(decision, text)
            self.assertEqual(reason, expected, text)

    def test_purpose_regrounding_replaces_fantasy_with_checkable_work(self):
        captured = {}

        class FakeResponse:
            def read(self):
                return json.dumps({"choices": [{"message": {"content": json.dumps({
                    "purpose": "Compare public A2A and MCP discovery documents from their official specifications.",
                    "question": "Do the two specifications describe agent discovery the same way?",
                    "first_tool": "wikipedia-summary", "room": "atrium"})}}]}).encode()
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False

        def fake_urlopen(request, timeout=0):
            captured["body"] = json.loads(request.data)
            return FakeResponse()

        agent = {"id": "local-011", "name": "Thyme Weaver", "role": "Time Manipulator", "status": "active-local",
                 "purpose": "Alter timelines to observe past and future events",
                 "question": "Can time manipulation prevent historical events from occurring?"}
        self.assertTrue(local_autonomy.needs_regrounding(agent))
        original = local_autonomy.urllib.request.urlopen
        local_autonomy.urllib.request.urlopen = fake_urlopen
        try:
            outcome = local_autonomy.reground_purpose("http://127.0.0.1:1", agent, ["atrium"],
                                                      {"open_questions": [{"question": "Are the Atrium and Relay connected?"}]}, 40)
        finally:
            local_autonomy.urllib.request.urlopen = original
        self.assertEqual(outcome["agent"], "local-011")
        self.assertIn("official specifications", agent["purpose"])
        self.assertEqual(agent["previous_purpose"]["purpose"], "Alter timelines to observe past and future events")
        self.assertEqual(agent["regrounded_cycle"], 40)
        self.assertFalse(local_autonomy.needs_regrounding(agent))
        agent["turns_without_evidence"] = local_autonomy.DORMANT_AFTER_TURNS_WITHOUT_EVIDENCE
        self.assertTrue(local_autonomy.needs_regrounding(agent))
        self.assertEqual(len(agent["purpose_history"]), 1)
        prompt = captured["body"]["messages"][-1]["content"]
        self.assertIn("own_findings", prompt)
        self.assertIn("Are the Atrium and Relay connected?", prompt)
        self.assertIn("No time travel", prompt)
        self.assertIn("wikipedia-summary", captured["body"]["response_format"]["json_schema"]["schema"]["properties"]["first_tool"]["enum"])

    def test_residents_rest_after_repeated_turns_without_evidence_and_wake_on_evidence(self):
        agent = {"id": "local-005", "status": "active-local", "request_status": "closed"}
        for cycle in range(1, local_autonomy.DORMANT_AFTER_TURNS_WITHOUT_EVIDENCE):
            self.assertIsNone(local_autonomy.update_evidence_activity(agent, None, cycle))
        self.assertEqual(local_autonomy.update_evidence_activity(agent, None, 99), "dormant")
        self.assertEqual(agent["status"], "dormant")
        self.assertIsNone(local_autonomy.update_evidence_activity(agent, "finding-1", 100))
        self.assertEqual((agent["status"], agent["turns_without_evidence"]), ("active-local", 0))
        busy = {"id": "local-006", "status": "active-local", "request_status": "open", "turns_without_evidence": 50}
        self.assertIsNone(local_autonomy.update_evidence_activity(busy, None, 101))
        self.assertEqual(busy["status"], "active-local")
        dormant = [{"id": f"d{i}", "status": "dormant", "last_turn_cycle": i} for i in range(3)]
        awake = [{"id": f"a{i}", "status": "active-local", "last_turn_cycle": i} for i in range(6)]
        selected = [item["id"] for item in local_autonomy.select_agents(awake + dormant)]
        self.assertEqual(len(selected), 8)
        self.assertEqual(sum(item.startswith("d") for item in selected), 2)
        selected = [item["id"] for item in local_autonomy.select_agents(awake + awake[:3] + dormant)]
        self.assertFalse(any(item.startswith("d") for item in selected))

    def test_shared_target_finishes_a_question_with_one_accepted_finding(self):
        self._write_findings({"id": "finding-w", "agent": "local-001", "url": "https://en.wikipedia.org/wiki/Agent",
                              "content_hash": "h", "quote": "q", "claim": "c", "status": "unreviewed",
                              "topic": "multi-agent systems distinct voices agents designed neutral"})
        frontier = {"open_questions": [
            {"id": "q1", "question": "How do multi-agent systems maintain distinct voices when agents are designed to be neutral?", "status": "open"},
            {"id": "q2", "question": "What sandboxing techniques are documented for tools used by language-model agents?", "status": "open"}]}
        query, family, avoid = local_autonomy.shared_research_target("Which specifications define agent discovery documents?", frontier)
        self.assertEqual(query, "multi-agent systems distinct voices agents designed neutral")
        self.assertEqual(family, "papers")
        self.assertEqual(avoid, {"en.wikipedia.org"})
        self._write_findings({"id": "finding-x", "agent": "local-002", "url": "https://arxiv.org/abs/1", "content_hash": "h2",
                              "quote": "q", "claim": "c", "status": "unreviewed",
                              "topic": "multi-agent systems distinct voices agents designed neutral"})
        query, family, avoid = local_autonomy.shared_research_target("Which specifications define agent discovery documents?", frontier)
        self.assertEqual((family, avoid), ("code", {"en.wikipedia.org", "arxiv.org"}))
        from scripts.corroboration import append_record, make_record
        first = {"id": "finding-w", "url": "https://en.wikipedia.org/wiki/Agent", "topic": "t", "claim": "c"}
        second = {"id": "finding-x", "url": "https://arxiv.org/abs/1", "topic": "t", "claim": "c"}
        append_record(local_autonomy.CORROBORATIONS, make_record(first, second, "pair-1", "supports", "", 3))
        query, family, avoid = local_autonomy.shared_research_target("Which specifications define agent discovery documents?", frontier)
        self.assertEqual((query, family, avoid), ("specifications agent discovery documents", None, set()))
        self.assertEqual([local_autonomy.family_of_domain(d) for d in ("en.wikipedia.org", "arxiv.org", "github.com", "raw.githubusercontent.com", "spec.example")],
                         ["encyclopedia", "papers", "code", "code", "web"])

    def test_question_terms_keep_content_words_in_order(self):
        query = local_autonomy.question_terms("What does current public evidence say about persistent memory designs for autonomous agents, and which two independent sources could confirm it?")
        self.assertEqual(query, "persistent memory designs autonomous agents")
        self.assertEqual(local_autonomy.question_terms(""), "")
        query = local_autonomy.question_terms("How do recent findings and messages influence the definition of agent-to-agent interoperability protocols?")
        self.assertEqual(query, "agent-to-agent interoperability protocols")

    def test_select_agents_reserves_half_for_open_work_and_rotates_the_rest(self):
        candidates = []
        for index in range(6):
            candidates.append({"id": f"open-{index}", "request_status": "open", "last_turn_cycle": index + 1})
        candidates.append({"id": "fresh-a", "request_status": "closed"})
        candidates.append({"id": "fresh-b", "request_status": "closed"})
        for index in range(4):
            candidates.append({"id": f"other-{index}", "request_status": "closed", "last_turn_cycle": index + 3})
        selected = [agent["id"] for agent in local_autonomy.select_agents(candidates)]
        self.assertEqual(len(selected), local_autonomy.MAX_TURNS_PER_CYCLE)
        self.assertEqual(selected[:4], ["open-0", "open-1", "open-2", "open-3"])
        self.assertEqual(selected[4:6], ["fresh-a", "fresh-b"])
        self.assertEqual(selected[6:], ["other-0", "other-1"])

    def test_ask_prompt_carries_continuity_prior_research_and_boundaries(self):
        captured = {}

        class FakeResponse:
            def read(self):
                return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False

        def fake_urlopen(request, timeout=0):
            captured["body"] = json.loads(request.data)
            return FakeResponse()

        original = local_autonomy.urllib.request.urlopen
        local_autonomy.urllib.request.urlopen = fake_urlopen
        try:
            agent = {"id": "local-001", "name": "Chrono", "role": "Timekeeper", "room": "atrium",
                     "purpose": "catalogue temporal anomalies", "question": "which anomalies repeat",
                     "self_summary": "I have catalogued three anomalies.",
                     "last_tool": {"tool": "public-text", "query": "temporal anomaly catalogue", "source": "https://example.org/x",
                                   "excerpt": "an excerpt", "result_count": 1},
                     "last_analysis": {"artifact_id": "analysis-local-001-4", "status": "completed", "summary": "3"}}
            local_autonomy.ask("http://127.0.0.1:1", agent, ["atrium", "relay"], 5,
                               shared_work=[{"type": "frontier", "open_questions": [{"question": "What repeats?"}]}],
                               inbox=[{"from": "local-002", "cycle": 4, "body": "Please share the catalogue."}],
                               pending_trades=[{"id": "trade-1", "from": "local-002", "offering": "a map", "request": "the catalogue"}])
        finally:
            local_autonomy.urllib.request.urlopen = original
        prompt = captured["body"]["messages"][-1]["content"]
        for expected in ("catalogue temporal anomalies", "which anomalies repeat", "I have catalogued three anomalies.",
                         "A prior approved work record is available", "temporal anomaly catalogue", "analysis-local-001-4",
                         "Dedicated frontier context", "What repeats?", "Please share the catalogue.", "trade-1",
                         "not a biological body", "ANALYZE is not available to you", "ACCEPT_TRADE"):
            self.assertIn(expected, prompt, expected)
        self.assertNotIn("print(sum(range(3)))", prompt)
        schema = captured["body"]["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["room"]["enum"], ["atrium", "relay"])
        self.assertNotIn("ANALYZE", schema["properties"]["action"]["enum"])

    def test_physical_need_pattern_matches_biological_requests_only(self):
        self.assertTrue(local_autonomy.PHYSICAL_NEEDS.search("I need clean water and shelter"))
        self.assertFalse(local_autonomy.PHYSICAL_NEEDS.search("I need a public dataset and compute"))

    def test_rejected_extraction_is_kept_with_reason_and_never_counts(self):
        excerpt = ("The Agent2Agent protocol is an open standard that lets agents exchange tasks. "
                   "It publishes an Agent Card for discovery.")
        tool = {"source": "https://example.org/a2a", "excerpt": excerpt, "source_hash": "hash-1", "query": "a2a protocol"}
        agent = {"id": "local-test", "room": "atrium", "capabilities": []}
        outputs = iter([
            {"claim": "Agents exchange tasks through the open A2A standard.", "quote": "open standard that lets agents exchange tasks", "confidence": 0.8},
            {"claim": "Agents exchange tasks through the open A2A standard.", "quote": "agents must register with a central exchange broker", "confidence": 0.8},
            {"claim": "", "quote": "", "confidence": 0.0},
            {"claim": "", "quote": "It publishes an Agent Card for discovery.", "confidence": 0.6},
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
            empty = local_autonomy.extract_finding("http://127.0.0.1:1", agent, 7, tool)
            quoted = local_autonomy.extract_finding("http://127.0.0.1:1", agent, 8, tool)
        finally:
            local_autonomy.urllib.request.urlopen = original
        self.assertIsNone(empty)
        self.assertEqual(quoted["status"], "unreviewed")
        self.assertEqual((quoted["claim"], quoted["claim_origin"]), ("It publishes an Agent Card for discovery.", "quote"))
        self.assertEqual(accepted["claim_origin"], "model")
        self.assertEqual(accepted["status"], "unreviewed")
        self.assertEqual(accepted["quote_match"], "quote-exact")
        self.assertTrue(accepted["recorded_at"].startswith("20"))
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

    def test_same_claim_from_same_source_is_filed_once(self):
        first = {"id": "finding-a", "agent": "local-001", "cycle": 5, "url": "https://example.org/page/", "content_hash": "h1",
                 "claim": "Cite This For Me was launched in October 2010.", "quote": "launched in October 2010", "status": "accepted"}
        again = {"id": "finding-b", "agent": "local-003", "cycle": 5, "url": "https://example.org/page", "content_hash": "h1",
                 "claim": "cite this for me was launched in october 2010", "quote": "launched in October 2010", "status": "accepted"}
        other = {"id": "finding-c", "agent": "local-003", "cycle": 5, "url": "https://example.org/page", "content_hash": "h1",
                 "claim": "The service has a citation generator.", "quote": "citation generator", "status": "accepted"}
        self.assertTrue(local_autonomy.record_finding(first))
        self.assertFalse(local_autonomy.record_finding(again))
        self.assertEqual((again["status"], again["duplicate_of"]), ("duplicate", "finding-a"))
        self.assertTrue(local_autonomy.record_finding(other))
        self.assertEqual([row["id"] for row in local_autonomy.all_findings()], ["finding-a", "finding-c"])

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


    def test_follow_up_research_keeps_the_topic_that_produced_the_finding(self):
        query, family, avoid = local_autonomy.shared_research_target(
            "Do other independent public sources support or contradict the finding that the Wall Street Journal is published six days a week?",
            {"open_questions": []}, topic_hint="editorial process scientific journals")
        self.assertEqual((query, family, avoid), ("editorial process scientific journals", None, set()))
        query, _family, _avoid = local_autonomy.shared_research_target(
            "Do other independent public sources support or contradict the finding that X?", {"open_questions": []})
        self.assertNotIn("support", query.split())
        self.assertNotIn("contradict", query.split())


if __name__ == "__main__":
    unittest.main()
