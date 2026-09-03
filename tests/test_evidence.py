import unittest

from scripts.evidence import claim_grounded, classify_finding, is_accepted, quote_support


EXCERPT = ("The Agent2Agent (A2A) protocol is an open standard that enables AI agents to communicate "
           "and collaborate across different frameworks and vendors. It uses JSON-RPC 2.0 over HTTP(S) "
           "and exposes an Agent Card at /.well-known/agent-card.json for discovery.")


class EvidenceRuleTests(unittest.TestCase):
    def test_exact_quote_is_supported(self):
        supported, score, mode = quote_support("uses JSON-RPC 2.0 over HTTP(S)", EXCERPT)
        self.assertTrue(supported)
        self.assertEqual((score, mode), (1.0, "exact"))

    def test_typographic_punctuation_and_case_do_not_break_exact_match(self):
        supported, _score, mode = quote_support("The Agent2Agent (A2A) Protocol Is An Open Standard", EXCERPT)
        self.assertTrue(supported)
        self.assertEqual(mode, "exact")

    def test_lightly_paraphrased_quote_is_fuzzy_supported(self):
        quote = "an open standard that enables AI agents to communicate and collaborate across frameworks and vendors"
        supported, score, mode = quote_support(quote, EXCERPT)
        self.assertTrue(supported)
        self.assertEqual(mode, "fuzzy")
        self.assertGreaterEqual(score, 0.85)

    def test_invented_quote_is_rejected(self):
        supported, score, mode = quote_support("agents must pay a subscription fee to use the registry", EXCERPT)
        self.assertFalse(supported)
        self.assertLess(score, 0.85)
        self.assertEqual(mode, "unsupported")

    def test_short_inexact_quote_is_not_guessed(self):
        supported, _score, mode = quote_support("open protocol", EXCERPT)
        self.assertFalse(supported)
        self.assertEqual(mode, "too-short")

    def test_imperative_claim_is_not_evidence(self):
        grounded, reason = claim_grounded("Explore the A2A protocol documentation next.", "the A2A protocol is an open standard")
        self.assertFalse(grounded)
        self.assertEqual(reason, "imperative-claim")

    def test_classification_keeps_rejected_reason(self):
        status, reason, _score = classify_finding("A2A agents communicate using JSON-RPC 2.0 over HTTP(S).",
                                                  "uses JSON-RPC 2.0 over HTTP(S)", EXCERPT, 0.7)
        self.assertEqual(status, "unreviewed")
        status, reason, _score = classify_finding("A2A agents communicate using JSON-RPC 2.0 over HTTP(S).",
                                                  "agents communicate using JSON-RPC over carrier pigeons and HTTP", EXCERPT, 0.7)
        self.assertEqual(status, "rejected")
        self.assertTrue(reason.startswith("quote-"), reason)
        status, reason, _score = classify_finding("A2A agents communicate using JSON-RPC 2.0 over HTTP(S).",
                                                  "agents pay a registry subscription fee", EXCERPT, 0.7)
        self.assertEqual((status, reason), ("rejected", "claim-not-grounded-in-quote"))
        self.assertEqual(classify_finding("claim", "quote", EXCERPT, 1.5)[0], "rejected")

    def test_rejected_rows_never_count_as_evidence(self):
        self.assertTrue(is_accepted({"status": "unreviewed"}))
        self.assertTrue(is_accepted({}))
        self.assertFalse(is_accepted({"status": "rejected"}))


if __name__ == "__main__":
    unittest.main()
