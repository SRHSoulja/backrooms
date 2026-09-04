import tempfile
import unittest
from pathlib import Path

from scripts.corroboration import (append_record, candidate_pairs, claims_overlap, corroboration_index, definition_source,
                                   founding_pair_stands, growth_candidates, judge_verdict, judgment_schema, load_records,
                                   make_record, on_topic, pair_id)


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

    def test_same_question_findings_are_paired_first_whatever_their_wording(self):
        findings = [
            finding("f1", "https://en.wikipedia.org/wiki/X", "advertising american cloud commerce consumer corporation electronics email software", topic="agent interoperability protocols"),
            finding("f2", "https://arxiv.org/abs/1", "we propose a protocol for agent interoperability", topic="agent interoperability protocols"),
            finding("f3", "https://a.example/one", "The A2A protocol publishes an agent card for discovery.", topic="other"),
            finding("f4", "https://b.example/two", "Agent cards enable discovery in the A2A protocol.", topic="another"),
        ]
        pairs = candidate_pairs(findings, limit=10)
        self.assertEqual((pairs[0][0]["id"], pairs[0][1]["id"], pairs[0][3]), ("f1", "f2", 1.0))
        self.assertTrue(all(score < 1.0 for _a, _b, _i, score in pairs[1:]))

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

    def test_claims_with_no_shared_vocabulary_are_never_sent_to_the_model(self):
        launch = {"id": "f-launch", "claim": "Cite This For Me was launched in October 2010 to help students create citations.",
                  "url": "https://www.citethisforme.com/", "status": "accepted"}
        redaction = {"id": "f-redact", "claim": "Redaction is the process of removing sensitive information from a document.",
                     "url": "https://en.wikipedia.org/wiki/Redaction", "status": "accepted"}
        self.assertEqual(claims_overlap(launch, redaction), set())
        founded = {"id": "f-founded", "claim": "The citation tool Cite This For Me was founded in 2010.",
                   "url": "https://example.org/history", "status": "accepted"}
        self.assertTrue(claims_overlap(launch, founded))

    def test_supports_needs_a_shared_fact_grounded_in_both_claims(self):
        launch = {"id": "f-launch", "claim": "Cite This For Me was launched in October 2010 to help students create citations.",
                  "url": "https://www.citethisforme.com/"}
        redaction = {"id": "f-redact", "claim": "Redaction is the process of removing sensitive information from a document.",
                     "url": "https://en.wikipedia.org/wiki/Redaction"}
        lenient = judge_verdict(launch, redaction, {"relation": "supports", "shared_claim": "Both concern citing sanitized reports.",
                                                    "reason": "same theme"})
        self.assertEqual((lenient["relation"], lenient["model_relation"]), ("unrelated", "supports"))
        self.assertTrue(lenient["reason"].startswith("shared fact not grounded"))
        founded = {"id": "f-founded", "claim": "The citation tool Cite This For Me was founded in 2010.",
                   "url": "https://example.org/history"}
        grounded = judge_verdict(launch, founded, {"relation": "supports", "shared_claim": "Cite This For Me started in 2010.",
                                                   "reason": "same launch year"})
        self.assertEqual((grounded["relation"], grounded["shared_claim"]), ("supports", "Cite This For Me started in 2010."))
        record = make_record(launch, founded, "pair-g", grounded["relation"], grounded["reason"], 9, 0.4,
                             shared_claim=grounded["shared_claim"], model_relation=grounded["model_relation"])
        self.assertEqual(record["topic"], "Cite This For Me started in 2010.")
        self.assertEqual(record["judge"], "local-model")
        self.assertIn("shared_claim", judgment_schema()["required"])
        contradicts = judge_verdict(launch, founded, {"relation": "contradicts", "shared_claim": "", "reason": "dates differ"})
        self.assertEqual((contradicts["relation"], contradicts["shared_claim"]), ("contradicts", ""))

    def test_dictionary_definitions_never_corroborate_and_off_topic_facts_do_not_grow_rooms(self):
        cambridge = {"id": "f-cam", "topic": "corroboration journalism scientific", "status": "accepted",
                     "claim": "The preposition under can indicate a position below or lower than something else.",
                     "url": "https://dictionary.cambridge.org/dictionary/english/under"}
        dictionary = {"id": "f-dict", "topic": "corroboration journalism scientific", "status": "accepted",
                      "claim": "The word under can function as a preposition indicating a position beneath something.",
                      "url": "https://www.dictionary.com/browse/under"}
        self.assertTrue(definition_source(cambridge) and definition_source(dictionary))
        self.assertEqual(candidate_pairs([cambridge, dictionary]), [])
        shared = "The preposition under indicates a position below something."
        self.assertFalse(on_topic(shared, cambridge, dictionary))
        verdict = judge_verdict(cambridge, dictionary, {"relation": "supports", "shared_claim": shared, "reason": "same definition"})
        self.assertEqual((verdict["relation"], verdict["model_relation"]), ("unrelated", "supports"))
        record = {"id": "pair-dud", "finding_ids": ["f-cam", "f-dict"], "shared_claim": shared, "relation": "supports"}
        ok, reason = founding_pair_stands(record, cambridge, dictionary)
        self.assertFalse(ok)
        self.assertEqual(reason, "a founding finding is a dictionary definition")
        journalism = {"id": "f-j", "topic": "corroboration journalism scientific", "status": "accepted",
                      "claim": "Journalism standards require two independent sources before a claim is published.",
                      "url": "https://example.org/standards"}
        science = {"id": "f-s", "topic": "corroboration journalism scientific", "status": "accepted",
                   "claim": "Scientific review treats a result as corroborated when independent groups reproduce it.",
                   "url": "https://example.net/review"}
        fact = "Independent sources are required before a claim counts as corroborated in journalism and science."
        self.assertTrue(on_topic(fact, journalism, science))
        ok, reason = founding_pair_stands({"id": "pair-ok", "finding_ids": ["f-j", "f-s"], "shared_claim": fact}, journalism, science)
        self.assertTrue(ok, reason)
        self.assertEqual(founding_pair_stands(None, journalism, science)[0], False)


if __name__ == "__main__":
    unittest.main()
