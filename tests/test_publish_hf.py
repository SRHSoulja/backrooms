import json
import tempfile
import unittest
from pathlib import Path

from scripts import publish_hf, report_card


class PublishTests(unittest.TestCase):
    def test_build_assembles_dataset_and_space_from_state_and_feeds(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state, docs, target = base / "state", base / "docs", base / "out"
            (state / "archive").mkdir(parents=True); docs.mkdir()
            (state / "day-zero.json").write_text(json.dumps({"cycle": 275, "at": "2026-09-04T03:06:25+00:00"}))
            (state / "world.json").write_text(json.dumps({"cycle": 300, "rooms": [{"id": "atrium"}, {"id": "r1", "founded_via": "evidence-ledger", "founded_cycle": 280, "status": "retracted", "retraction_reason": "x"}]}))
            (state / "findings.jsonl").write_text("\n".join([
                json.dumps({"id": "f1", "cycle": 280, "status": "unreviewed", "claim": "a"}),
                json.dumps({"id": "f2", "cycle": 281, "status": "rejected", "rejection_reason": "off-topic", "claim": "b"})]) + "\n")
            (state / "corroborations.jsonl").write_text(json.dumps({"id": "p1", "cycle": 282, "relation": "unrelated", "model_relation": "supports", "judge": "local-model",
                                                                     "inference": {"verdict": "unrelated", "support": 0.1, "contradiction": 0.0}}) + "\n")
            (state / "archive" / "events.jsonl").write_text(json.dumps({"id": "e1", "cycle": 280, "kind": "finding-filed"}) + "\n")
            (state / "research-lines.json").write_text(json.dumps({"lines": [{"id": "l1", "status": "closed", "closed_reason": "hop cap", "origin": "resident:echo"}]}))
            (state / "local-agents.json").write_text(json.dumps({"agents": [{"id": "local-001", "status": "active-local", "recorded_at": "2026-09-04T05:00:00+00:00"}]}))
            (docs / "health.json").write_text(json.dumps({"active_residents": 1, "event_chain": {"count": 1, "verified": True, "head": "abc"}, "inference_judge": {"available": True, "scored_pairs": 1}, "model_usage": {"providers": [{"name": "mistral", "calls": 3}]}}))
            (docs / "world.json").write_text("{}"); (docs / "disagreements.json").write_text(json.dumps({"entries": []}))
            facts = report_card.facts(state=state, docs=docs)
            self.assertEqual((facts["findings"]["accepted"], facts["findings"]["rejected"], facts["rooms"]["withdrawn"], facts["roster"]["hired"]), (1, 1, 1, 1))
            self.assertEqual(facts["pairs"]["model_vs_inference"], [{"model": "supports", "inference": "unrelated", "pairs": 1}])
            text = report_card.markdown(facts)
            self.assertIn("| off-topic | 1 |", text)
            self.assertIn("1 rooms founded", text)
            dataset_dir, space_dir, included = publish_hf.build(target, "owner/ledger", "owner/replay", state=state, docs=docs)
            self.assertTrue((dataset_dir / "findings.jsonl").exists() and (dataset_dir / "events.jsonl").exists())
            self.assertIn("REPORT.md", included)
            card = (dataset_dir / "README.md").read_text()
            self.assertTrue(card.startswith("---\nlicense: mit"))
            self.assertIn("owner/replay", card)
            html = (space_dir / "index.html").read_text()
            self.assertIn('const DATASET = "owner/ledger";', html)
            self.assertNotIn("__DATASET__", html)
            self.assertTrue((space_dir / "README.md").read_text().startswith("---\ntitle: Backrooms Replay"))
            self.assertFalse((dataset_dir / "local-agents.json").exists())  # private memory never leaves


if __name__ == "__main__":
    unittest.main()
