import json
import tempfile
import unittest
from pathlib import Path

from scripts.storage import atomic_write_json


class StorageTests(unittest.TestCase):
    def test_atomic_json_write_replaces_complete_document(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.json"
            atomic_write_json(path, {"cycle": 1, "rooms": ["atrium"]})
            self.assertEqual(json.loads(path.read_text())["cycle"], 1)
            atomic_write_json(path, {"cycle": 2, "rooms": ["atrium", "relay"]})
            self.assertEqual(json.loads(path.read_text())["cycle"], 2)
            self.assertEqual(list(path.parent.glob(".*state.json.*")), [])


if __name__ == "__main__":
    unittest.main()
