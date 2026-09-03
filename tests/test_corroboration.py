import tempfile
import unittest
from pathlib import Path

from scripts.corroboration import (append_record, candidate_pairs, corroboration_index, growth_candidates,
                                   load_records, make_record, pair_id)


def finding(identifier, url, claim, topic="agent interoperability standards", status="unreviewed"):
    return {"id": identifier, "url": url, "claim": claim, "quote": claim, "topic": topic, "status": status}


class CorroborationTests(unittest.TestCase):
    def test_pairs_need_distinct_domains_and_shared_claim_vocabulary(self):
        findings = [
            finding("f1", "https://a.example/one", "The A2A protocol publishes an agent card for discovery."),
            finding("f2", "https://b.example/two", "Agent cards enable discovery in the A2A protocol."),
            finding("f3", "https://a.example/three", "The A2A protocol publishes an agent card for discovery."),
            finding("f4", "https://c.example/four", "Bread rises because yeast produces carbon dioxide.", topic="baking"),
            finding("f5", "https://d.example/five", "Rejected rows never pair.", status="rejected"),
        ]
        pairs = candidate_pairs(findings)
        ids = [(first["id"], second["id"]) for first, second, _identifier, _score in pairs]
        self.assertIn(("f1", "f2"), ids)
        self.assertNotIn(("f1", "f3"), ids)
        self.assertFalse(any("f4" in pair or "f5" in pair for pair in ids))
        self.assertEqual(pair_id("f1", "f2"), pair_id("f2", "f1"))
        judged = {pair_id("f1", "f2")}
        self.assertNotIn(("f1", "f2"), [(a["id"], b["id"]) for a, b, _i, _s in candidate_pairs(findings, judged)])

    def test_records_are_appended_once_and_indexed_by_support(self):
        first = finding("f1", "https://a.example/one", "The A2A protocol publishes an agent card for discovery.")
        second = finding("f2", "https://b.example/two", "Agent cards enable discovery in the A2A protocol.")
        record = make_record(first, second, pair_id("f1", "f2"), "supports", "same fact", 5, 0.5)
        self.assertEqual(record["domains"], ["a.example", "b.example"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corroborations.jsonl"
            self.assertTrue(append_record(path, record))
            self.assertFalse(append_record(path, record))
            self.assertEqual(len(load_records(path)), 1)
        index = corroboration_index([record, make_record(first, second, "pair-x", "contradicts", "", 5)])
        self.assertEqual(index["f1"], {"a.example", "b.example"})
        self.assertEqual(index["f2"], {"a.example", "b.example"})

    def test_growth_candidates_skip_topics_already_covered_by_a_room(self):
        first = finding("f1", "https://a.example/one", "The A2A protocol publishes an agent card for discovery.")
        second = finding("f2", "https://b.example/two", "Agent cards enable discovery in the A2A protocol.")
        support = make_record(first, second, "pair-1", "supports", "", 5)
        conflict = make_record(first, second, "pair-2", "contradicts", "", 5)
        by_id = {"f1": first, "f2": second}
        self.assertEqual([record["id"] for record, _pair in growth_candidates([support, conflict], by_id, [])], ["pair-1"])
        self.assertEqual(growth_candidates([support], by_id, [support["topic"]]), [])
        self.assertEqual(growth_candidates([support], {"f1": first}, []), [])


if __name__ == "__main__":
    unittest.main()
