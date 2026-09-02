import copy
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
        local_autonomy.WHITEBOARD = Path(self.archive_dir.name) / "whiteboard.json"
        local_autonomy.PRINTER_QUEUE = Path(self.archive_dir.name) / "printer-queue.json"
        local_autonomy.PRINTED = Path(self.archive_dir.name) / "printed"
        local_autonomy.NOTES = Path(self.archive_dir.name) / "notes"

    def tearDown(self):
        local_autonomy.ARCHIVE = self.original_archive
        local_autonomy.WHITEBOARD = self.original_whiteboard
        local_autonomy.PRINTER_QUEUE = self.original_printer_queue
        local_autonomy.PRINTED = self.original_printed
        local_autonomy.NOTES = self.original_notes
        local_autonomy.ANALYSIS_ARCHIVE = self.original_analysis_archive
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
        self.assertIn('tool.get("source", tool.get("url", ""))', source)
        self.assertIn('summary.get("items", summary.get("rows", 0))', source)

    def test_analyze_requires_workbench_and_data_only_code(self):
        text = "ACTION: ANALYZE\nROOM: atrium\nTARGET: summarize values\nPROPOSAL: NONE\nREQUEST: NONE\nCODE: print(sum(range(3)))\nREASON: test"
        denied = local_autonomy.parse(text, {"room": "atrium", "capabilities": []}, ["atrium"])
        allowed = local_autonomy.parse(text, {"room": "atrium", "capabilities": ["bounded-workbench"]}, ["atrium"])
        self.assertIsNone(denied)
        self.assertEqual(allowed["action"], "ANALYZE")
        self.assertIn("sum", allowed["code"])

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
        self.assertEqual(local_autonomy.workbench_bootstrap(agent, decision), decision)

    def test_interview_prompt_can_use_prior_research_metadata(self):
        source = Path("scripts/local_autonomy.py").read_text()
        self.assertIn('A prior approved work record is available', source)
        self.assertIn('"summary"', source)
        self.assertIn('"analysis"', source)
        self.assertIn('"artifact_id"', source)
        self.assertIn('Shared analysis ledger', source)
        self.assertIn('"verified": tool["tool"] != "public-search"', source)
        self.assertIn('Use ANALYZE when your bounded-workbench role', source)
        self.assertIn('prefer a tiny local health check', source)


if __name__ == "__main__":
    unittest.main()
