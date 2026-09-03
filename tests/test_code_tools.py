import tempfile
import unittest
from pathlib import Path

from scripts import code_proposal, code_view, code_sandbox


class CodeToolTests(unittest.TestCase):
    def test_sandbox_uses_networkless_isolation_and_bounded_data(self):
        result = code_sandbox.run("print(len(data))", "public excerpt")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["isolation"], "bubblewrap-unshare-all")
        self.assertIn("14", result["output"])

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
