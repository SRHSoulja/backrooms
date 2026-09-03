import tempfile
import unittest
from pathlib import Path

from scripts import code_proposal, code_view, code_sandbox


class CodeToolTests(unittest.TestCase):
    def test_sandbox_uses_networkless_isolation_and_bounded_data(self):
        result = code_sandbox.run("print(len(data))", "public excerpt")
        self.assertEqual(result["status"], "completed", result)
        self.assertIn(result["isolation"], {"bubblewrap-unshare-all", "language-isolated-fallback"})
        self.assertTrue(result["isolation_detail"])
        self.assertIn("14", result["output"])

    def test_sandbox_falls_back_explicitly_when_bubblewrap_is_unavailable(self):
        original_probe = code_sandbox._BWRAP_PROBE
        original_which = code_sandbox.shutil.which
        try:
            code_sandbox._BWRAP_PROBE = None
            code_sandbox.shutil.which = lambda _name: None
            result = code_sandbox.run("print(len(data))", "public excerpt")
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["isolation"], "language-isolated-fallback")
            self.assertEqual(result["isolation_detail"], "bwrap-not-installed")
            self.assertIn("14", result["output"])
        finally:
            code_sandbox._BWRAP_PROBE = original_probe
            code_sandbox.shutil.which = original_which

    def test_bubblewrap_prefix_binds_only_existing_roots(self):
        prefix = code_sandbox.bwrap_prefix()
        self.assertEqual(prefix[:2], ["bwrap", "--unshare-all"])
        bound = [prefix[index + 1] for index, item in enumerate(prefix) if item == "--ro-bind"]
        self.assertTrue(all(Path(root).exists() for root in bound))
        self.assertNotIn("--share-net", prefix)

    def test_only_known_residents_proposals_are_publishable(self):
        records = [{"id": "p1", "resident": "test-resident"}, {"id": "p2", "resident": "tool-request"},
                   {"id": "p3", "resident": "local-004"}, {"id": "p4", "resident": "echo"}]
        kept = code_proposal.publishable(records, {"local-004", "echo", "morrow"})
        self.assertEqual([item["id"] for item in kept], ["p3", "p4"])

    def test_code_view_rejects_private_paths(self):
        result = code_view.run("../.env")
        self.assertEqual(result["status"], "rejected")

    def test_code_view_redacts_sensitive_lines(self):
        source = code_view.public_text(Path("scripts/tool_broker.py"))
        self.assertNotIn("API_KEY=", source)
        self.assertIn("redacted", source.lower())

    def test_code_proposal_rejects_secret_and_never_applies(self):
        original = code_proposal.ARCHIVE
        with tempfile.TemporaryDirectory() as directory:
            code_proposal.ARCHIVE = Path(directory) / "proposals.json"
            patch = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+API_KEY=not-a-real-key"
            reason = code_proposal.validate(patch)
            self.assertEqual(reason, "secret-like content detected")
            item = code_proposal.archive(patch, "rejected", reason, "test-resident")
            self.assertEqual(item["status"], "rejected")
            self.assertFalse((Path("README.md")).read_text().startswith("API_KEY="))
        code_proposal.ARCHIVE = original
