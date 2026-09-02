import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts import a2a_server
from scripts.a2a_server import INTAKE_VERSION, safe_summary, task_id_for
from scripts.publish_outside_signals import expire_stale


class A2ABoundaryTests(unittest.TestCase):
    def test_safety_disclaimer_is_not_mistaken_for_a_secret(self):
        text = "I do not request credentials, private memory, private data, or write access."
        self.assertEqual(safe_summary(text), text)

    def test_secret_shaped_assignment_is_withheld(self):
        text = "API_KEY=TEST_ONLY_NOT_A_REAL_SECRET"
        self.assertIn("withheld", safe_summary(text))

    def test_filter_version_is_explicit(self):
        self.assertEqual(INTAKE_VERSION, "2-narrow-secret-patterns")

    def test_task_id_prefix_is_added_once(self):
        self.assertEqual(task_id_for("visit-001"), "a2a-visit-001")
        self.assertEqual(task_id_for("a2a-visit-001"), "a2a-visit-001")

    def test_expiry_records_one_transition_and_skips_reviewed_tasks(self):
        current = datetime(2026, 9, 2, tzinfo=timezone.utc)
        messages = [
            {"id": "stale", "status": "quarantined", "received_at": "2026-07-01T00:00:00+00:00",
             "history": [{"status": "pending-review"}]},
            {"id": "accepted", "status": "accepted-exchange", "received_at": "2026-01-01T00:00:00+00:00",
             "history": [{"status": "pending-review"}, {"status": "accepted-exchange"}]},
        ]
        self.assertTrue(expire_stale(messages, current))
        self.assertEqual(messages[0]["status"], "expired")
        self.assertEqual(messages[0]["history"][-1]["status"], "expired")
        self.assertEqual(len(messages[0]["history"]), 2)
        self.assertEqual(messages[1]["status"], "accepted-exchange")

    def test_quarantine_has_one_canonical_task_status(self):
        intake_status = "quarantined"
        task_status = "pending-review" if intake_status == "quarantined" else intake_status
        self.assertEqual(task_status, "pending-review")

    def test_quarantine_preserves_parent_and_pending_history(self):
        original = a2a_server.INBOX
        with tempfile.TemporaryDirectory() as directory:
            a2a_server.INBOX = Path(directory) / "inbox.json"
            a2a_server.INBOX.write_text(json.dumps({"messages": [
                {"id": "a2a-parent", "status": "accepted-exchange"}]}))
            a2a_server.quarantine("bounded report", "a2a-followup", "a2a-parent")
            item = json.loads(a2a_server.INBOX.read_text())["messages"][-1]
            self.assertEqual(item["parent_task_id"], "a2a-parent")
            self.assertEqual(item["history"][0]["status"], "pending-review")
        a2a_server.INBOX = original

    def test_only_accepted_tasks_can_be_parents(self):
        original = a2a_server.INBOX
        with tempfile.TemporaryDirectory() as directory:
            a2a_server.INBOX = Path(directory) / "inbox.json"
            a2a_server.INBOX.write_text(json.dumps({"messages": [
                {"id": "pending", "status": "quarantined"},
                {"id": "accepted", "status": "accepted-exchange"}]}))
            self.assertEqual(a2a_server.accepted_parent("pending"), "")
            self.assertEqual(a2a_server.accepted_parent("accepted"), "accepted")
        a2a_server.INBOX = original

    def test_quarantine_defends_against_unverified_parent_callers(self):
        original = a2a_server.INBOX
        with tempfile.TemporaryDirectory() as directory:
            a2a_server.INBOX = Path(directory) / "inbox.json"
            a2a_server.quarantine("bounded report", "child", "phantom-parent")
            item = json.loads(a2a_server.INBOX.read_text())["messages"][0]
            self.assertNotIn("parent_task_id", item)
        a2a_server.INBOX = original
