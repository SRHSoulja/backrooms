import json
import unittest
from pathlib import Path

from scripts import tool_broker
from scripts.tool_broker import TOOL_CONTRACTS


class ToolContractTests(unittest.TestCase):
    def test_public_catalog_matches_broker_contracts(self):
        catalog = json.loads(Path("docs/tool-catalog.json").read_text())
        public = {item["name"]: {key: value for key, value in item.items() if key != "name"}
                  for item in catalog["tools"]}
        self.assertEqual(public, TOOL_CONTRACTS)

    def test_public_search_extracts_bounded_results(self):
        original = tool_broker.fetch
        try:
            tool_broker.fetch = lambda url: '<a class="result__a" href="https://example.org">Example</a>'
            result = tool_broker.public_search("public dataset")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["results"][0]["url"], "https://example.org")
        finally:
            tool_broker.fetch = original


if __name__ == "__main__":
    unittest.main()
