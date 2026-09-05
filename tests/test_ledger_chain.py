import json
import tempfile
import unittest
from pathlib import Path

from scripts import ledger_chain


class LedgerChainTests(unittest.TestCase):
    def test_events_chain_and_edits_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            # a legacy line without a hash is linked by its raw text
            path.write_text(json.dumps({"id": "legacy", "kind": "old"}) + "\n")
            first = ledger_chain.append_event(path, {"id": "e1", "kind": "line-opened", "text": "one"})
            second = ledger_chain.append_event(path, {"id": "e2", "kind": "line-closed", "text": "two"})
            self.assertEqual(first["prev"], ledger_chain.raw_hash(path.read_text().splitlines()[0]))
            self.assertEqual(second["prev"], first["hash"])
            self.assertEqual(ledger_chain.verify(path), (True, 3, ""))
            self.assertEqual(ledger_chain.head(path), {"count": 3, "head": second["hash"]})
            lines = path.read_text().splitlines()
            tampered = json.loads(lines[1]); tampered["text"] = "edited"
            lines[1] = json.dumps(tampered, separators=(",", ":"))
            path.write_text("\n".join(lines) + "\n")
            ok, count, problem = ledger_chain.verify(path)
            self.assertEqual((ok, count), (False, 2))
            self.assertIn("does not match its own hash", problem)
            self.assertEqual(ledger_chain.verify(Path(directory) / "missing.jsonl"), (True, 0, ""))
