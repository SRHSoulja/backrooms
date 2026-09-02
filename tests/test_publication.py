import unittest

from scripts.publication import public_text


class PublicationSafetyTests(unittest.TestCase):
    def test_sensitive_text_is_withheld(self):
        self.assertTrue(public_text("Here is an api_key: abc123").startswith("[content withheld"))
        self.assertTrue(public_text("Bearer abc.def.ghi").startswith("[content withheld"))

    def test_safe_text_is_normalized_and_bounded(self):
        self.assertEqual(public_text("  hello\n world  "), "hello world")
        self.assertEqual(len(public_text("x" * 500)), 240)

    def test_core_contribution_is_eligible_for_public_projection(self):
        self.assertEqual(public_text("A bounded council contribution."), "A bounded council contribution.")


if __name__ == "__main__":
    unittest.main()
