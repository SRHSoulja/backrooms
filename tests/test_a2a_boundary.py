import unittest

from scripts.a2a_server import INTAKE_VERSION, safe_summary


class A2ABoundaryTests(unittest.TestCase):
    def test_safety_disclaimer_is_not_mistaken_for_a_secret(self):
        text = "I do not request credentials, private memory, private data, or write access."
        self.assertEqual(safe_summary(text), text)

    def test_secret_shaped_assignment_is_withheld(self):
        text = "API_KEY=TEST_ONLY_NOT_A_REAL_SECRET"
        self.assertIn("withheld", safe_summary(text))

    def test_filter_version_is_explicit(self):
        self.assertEqual(INTAKE_VERSION, "2-narrow-secret-patterns")
