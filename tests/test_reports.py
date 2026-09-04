import unittest

from scripts import reports
from scripts.journal import verify_entry


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.findings = [
            {"id": "finding-a", "agent": "local-001", "cycle": 298, "status": "unreviewed", "topic": "roskomnadzor github block russia",
             "claim": "Russia's regulator Roskomnadzor blocked access to GitHub in December 2014.", "quote": "blocked access to GitHub",
             "url": "https://techcrunch.com/2014/12/03/github-russia/", "content_hash": "abc123def456"},
            {"id": "finding-b", "agent": "local-007", "cycle": 301, "status": "unreviewed", "topic": "roskomnadzor github block russia",
             "claim": "Roskomnadzor blocked GitHub over pages describing suicide methods.", "quote": "blocked GitHub",
             "url": "https://meduza.io/en/feature/2015/08/13/github", "content_hash": "0011223344"},
            {"id": "finding-c", "agent": "local-009", "cycle": 302, "status": "rejected", "rejection_reason": "off-topic", "topic": "roskomnadzor github block russia",
             "claim": "Quasar spectra show emission lines.", "url": "https://arxiv.org/abs/1", "content_hash": "ff"},
            {"id": "finding-z", "agent": "local-002", "cycle": 290, "status": "unreviewed", "topic": "opinion polls sampling",
             "claim": "Opinion polls carry sampling error.", "url": "https://example.org/polls", "content_hash": "ee"}]
        self.pairs = [{"id": "pair-1", "finding_ids": ["finding-a", "finding-b"], "relation": "supports", "shared_claim": "Roskomnadzor blocked GitHub in December 2014.", "domains": ["techcrunch.com", "meduza.io"]}]
        self.world = {"rooms": [{"id": "roskomnadzor-blocked-github", "name": "Roskomnadzor Blocked GitHub", "founded_via": "evidence-ledger", "artifacts": ["finding-a", "finding-b"], "growth_topic": "Roskomnadzor blocked GitHub in December 2014.", "status": "open"}]}

    def test_report_gathers_only_the_topic_and_is_fully_traceable(self):
        title, body, digest = reports.compile_report("roskomnadzor github block russia", self.findings, self.pairs, self.world,
                                                     questions=[{"question": "Did Roskomnadzor block GitHub?"}], agent_id="local-001", cycle=310)
        self.assertEqual(title, "Report: roskomnadzor github block russia")
        self.assertEqual(digest["counts"]["accepted_findings"], 2)
        self.assertEqual(digest["counts"]["rejected_findings"], 1)
        self.assertEqual((digest["counts"]["supports"], digest["counts"]["rooms_built"], digest["counts"]["domains"]), (1, 1, 2))
        self.assertIn("finding-a", body); self.assertIn("meduza.io", body); self.assertIn("sha256 abc123def456", body)
        self.assertIn("SUPPORTS [pair-1]", body); self.assertIn("ROOM roskomnadzor-blocked-github", body)
        self.assertNotIn("Opinion polls", body)
        self.assertIn("off-topic 1", body)

    def test_narrative_must_verify_against_the_digest(self):
        _title, _body, digest = reports.compile_report("roskomnadzor github block russia", self.findings, self.pairs, self.world)
        self.assertEqual(verify_entry("Two residents, local-001 and local-007, found the block described on two domains; one pair supports it.", digest)[0], True)
        self.assertFalse(verify_entry("It was confirmed by 7 sources.", digest)[0])
        self.assertFalse(verify_entry("local-099 confirmed it.", digest)[0])


if __name__ == "__main__":
    unittest.main()
