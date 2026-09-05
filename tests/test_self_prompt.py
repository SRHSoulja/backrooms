import unittest
from pathlib import Path

from scripts.self_prompt_rules import carry_forward, rejection_reason, valid


class SelfPromptTests(unittest.TestCase):
    def test_council_context_is_built_from_accepted_findings_open_questions_and_leads(self):
        import json
        import tempfile
        from pathlib import Path
        from scripts import roundtable
        original = (roundtable.FINDINGS, roundtable.FRONTIER)
        with tempfile.TemporaryDirectory() as directory:
            roundtable.FINDINGS = Path(directory) / "findings.jsonl"
            roundtable.FRONTIER = Path(directory) / "frontier.json"
            roundtable.FINDINGS.write_text("\n".join([
                json.dumps({"id": "finding-1", "topic": "t", "claim": "accepted claim", "quote": "q", "url": "https://a.example/1",
                            "confidence": 0.7, "relates_to": ["atrium"], "status": "unreviewed"}),
                json.dumps({"id": "finding-2", "topic": "t", "claim": "rejected claim", "quote": "q", "url": "https://b.example/2",
                            "confidence": 0.7, "relates_to": ["atrium"], "status": "rejected"})]) + "\n")
            roundtable.FRONTIER.write_text(json.dumps({
                "open_questions": [{"id": "q1", "question": "open one", "status": "open"},
                                   {"id": "q2", "question": "closed one", "status": "closed"}],
                "contradictions": [{"id": "c1", "topic": "t", "finding_ids": ["finding-1", "finding-3"], "reason": "r", "status": "open"}],
                "leads": [{"question_id": "q1", "text": "outside review text", "status": "unverified"}]}))
            try:
                context = roundtable.bounded_context({"title": "The Atrium", "cycle": 9, "shared_memory": [], "events": []})
            finally:
                roundtable.FINDINGS, roundtable.FRONTIER = original
        self.assertEqual([item["claim"] for item in context["verified_findings"]], ["accepted claim"])
        self.assertEqual(context["verified_findings"][0]["url"], "https://a.example/1")
        self.assertEqual(context["verified_findings"][0]["room"], "atrium")
        self.assertEqual([item["question"] for item in context["frontier_questions"]], ["open one"])
        self.assertEqual(context["open_contradictions"][0]["reason"], "r")
        self.assertEqual(context["untrusted_outside_leads"][0]["text"], "outside review text")

    def test_rejects_self_referential_marker_loop(self):
        proposal = ("QUESTION: Why did Echo's evidence markers decrease after the hypothesis weakened?\n"
                    "WHY: The metric changed.\nTEST: Count markers again.")
        self.assertFalse(valid(proposal))

    def test_rejects_questions_about_the_world_itself(self):
        for question in ("How does the behavior of residents in the Atrium compare to those in the Relay?",
                         "Why did the resident move from Archive to Quiet-Workspace?",
                         "What unexplained pattern in the current rooms deserves an experiment?",
                         "Are the anomalies at cycle 146 consistent?"):
            proposal = f"QUESTION: {question}\nWHY: curiosity.\nTEST: look."
            self.assertFalse(valid(proposal), question)
        proposal = ("QUESTION: What do public sources say about persistent memory designs for autonomous agents?\n"
                    "WHY: It is a research theme.\nTEST: Compare two independent public sources.")
        self.assertTrue(valid(proposal))

    def test_rejects_questions_about_an_individuals_account(self):
        from scripts.self_prompt_rules import rejection_reason
        for question in ("Does the GitHub profile **Roscomnadzor27** have any publicly documented affiliation with Roskomnadzor?",
                         "Does the GitHub profile 'roscom' (Ross Cameron) have any publicly visible contributions to seismic repositories?",
                         "What does the user @someone on Twitter say about the outage?"):
            proposal = f"QUESTION: {question}\nWHY: curiosity.\nTEST: look."
            self.assertIn("individual's account, profile, or handle", rejection_reason(proposal), question)
        proposal = ("QUESTION: Which GitHub repositories does Roskomnadzor's official organization publish, according to public sources?\n"
                    "WHY: It is a public organization.\nTEST: Compare two independent public sources.")
        self.assertTrue(valid(proposal))

    def test_accepts_public_frontier_question(self):
        proposal = ("QUESTION: Which public finding should we verify next?\n"
                    "WHY: It may explain the newest room candidate.\n"
                    "TEST: Compare two independent public sources.")
        self.assertTrue(valid(proposal))
