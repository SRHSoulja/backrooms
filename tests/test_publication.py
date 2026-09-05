import unittest

from scripts.publication import public_text, public_tool_attempt


class PublicationSafetyTests(unittest.TestCase):
    def test_sensitive_text_is_withheld(self):
        self.assertTrue(public_text("Here is an api_key: abc123").startswith("[content withheld"))
        self.assertTrue(public_text("Bearer abc.def.ghi").startswith("[content withheld"))

    def test_safe_text_is_normalized_and_bounded(self):
        self.assertEqual(public_text("  hello\n world  "), "hello world")
        self.assertEqual(len(public_text("x" * 500)), 240)
        self.assertEqual(public_text("private network diagnostics"), "private network diagnostics")

    def test_core_contribution_is_eligible_for_public_projection(self):
        self.assertEqual(public_text("A bounded council contribution."), "A bounded council contribution.")

    def test_empty_text_is_not_described_as_withheld(self):
        self.assertEqual(public_text(""), "")

    def test_tool_attempt_projection_is_bounded_and_allowlisted(self):
        attempt = public_tool_attempt({"last_tool_attempt": {
            "cycle": 331, "tool": "public-text", "requested_target": "https://example.org/missing",
            "status": "failed", "error_kind": "source-not-found", "http_status": 404,
            "private_debug": "must not publish"}})
        self.assertEqual(attempt["error_kind"], "source-not-found")
        self.assertEqual(attempt["http_status"], 404)
        self.assertNotIn("private_debug", attempt)


if __name__ == "__main__":
    unittest.main()
