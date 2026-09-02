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

    def test_public_json_returns_shape_not_raw_data(self):
        original = tool_broker.fetch
        try:
            tool_broker.fetch = lambda url: '{"beta": 2, "alpha": 1}'
            result = tool_broker.public_json("https://example.org/data.json")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["keys"], ["alpha", "beta"])
            self.assertNotIn("alpha", result)
        finally:
            tool_broker.fetch = original

    def test_public_csv_returns_schema_not_raw_rows(self):
        original = tool_broker.fetch
        try:
            tool_broker.fetch = lambda url: "name,value\nalpha,1\nbeta,2\n"
            result = tool_broker.public_csv("https://example.org/data.csv")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["rows"], 2)
            self.assertEqual(result["summary"]["headers"], ["name", "value"])
            self.assertNotIn("alpha", result)
        finally:
            tool_broker.fetch = original

    def test_local_code_sandbox_is_contracted(self):
        self.assertEqual(TOOL_CONTRACTS["local-code-sandbox"]["network"], "none")
        self.assertEqual(TOOL_CONTRACTS["local-code-sandbox"]["timeout_seconds"], 5)

    def test_restricted_code_executor_runs_data_expression(self):
        from scripts.code_sandbox import run
        result = run("print(sum(range(10)))")
        self.assertEqual(result["status"], "completed")
        self.assertIn("45", result["output"])

    def test_restricted_code_executor_rejects_imports(self):
        from scripts.code_sandbox import run
        self.assertEqual(run("import os") ["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
