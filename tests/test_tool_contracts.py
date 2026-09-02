import json
import unittest
from pathlib import Path

from scripts.tool_broker import TOOL_CONTRACTS


class ToolContractTests(unittest.TestCase):
    def test_public_catalog_matches_broker_contracts(self):
        catalog = json.loads(Path("docs/tool-catalog.json").read_text())
        public = {item["name"]: {key: value for key, value in item.items() if key != "name"}
                  for item in catalog["tools"]}
        self.assertEqual(public, TOOL_CONTRACTS)


if __name__ == "__main__":
    unittest.main()
