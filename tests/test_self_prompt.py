import unittest

from scripts.self_prompt_rules import valid


class SelfPromptTests(unittest.TestCase):
    def test_rejects_self_referential_marker_loop(self):
        proposal = ("QUESTION: Why did Echo's evidence markers decrease after the hypothesis weakened?\n"
                    "WHY: The metric changed.\nTEST: Count markers again.")
        self.assertFalse(valid(proposal))

    def test_accepts_public_frontier_question(self):
        proposal = ("QUESTION: Which public finding should we verify next?\n"
                    "WHY: It may explain the newest room candidate.\n"
                    "TEST: Compare two independent public sources.")
        self.assertTrue(valid(proposal))
