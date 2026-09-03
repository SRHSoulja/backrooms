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
            tool_broker.fetch = lambda url: '<a class="result__a" href="https://example.org">Public Dataset Example</a>'
            result = tool_broker.public_search("public dataset")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["results"][0]["url"], "https://example.org")
        finally:
            tool_broker.fetch = original

    def test_public_search_falls_back_when_primary_has_no_results(self):
        original = tool_broker.fetch
        try:
            def fake_fetch(url):
                if "duckduckgo" in url:
                    return "<html>no parsed results</html>"
                if "format=rss" in url:
                    return "<rss><item><title>Public Dataset Report</title><link>https://example.org/report</link></item></rss>"
                return '<li class="b_algo"><h2><a href="https://example.org/fallback">Fallback</a></h2></li>'
            tool_broker.fetch = fake_fetch
            result = tool_broker.public_search("public dataset")
            self.assertEqual(result["source"], "https://www.bing.com/")
            self.assertEqual(result["results"][0]["url"], "https://example.org/report")
            self.assertEqual(result["query"], "public dataset")
        finally:
            tool_broker.fetch = original

    def test_public_json_returns_shape_not_raw_data(self):
        original = tool_broker.fetch
        try:
            tool_broker.fetch = lambda url, *args: '{"beta": 2, "alpha": 1}'
            result = tool_broker.public_json("https://example.org/data.json")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["keys"], ["alpha", "beta"])
            self.assertNotIn("alpha", result)
        finally:
            tool_broker.fetch = original

    def test_public_csv_returns_schema_not_raw_rows(self):
        original = tool_broker.fetch
        try:
            tool_broker.fetch = lambda url, *args: "name,value\nalpha,1\nbeta,2\n"
            result = tool_broker.public_csv("https://example.org/data.csv")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["rows"], 2)
            self.assertEqual(result["summary"]["headers"], ["name", "value"])
            self.assertFalse(result["summary"]["truncated"])
            self.assertNotIn("alpha", result)
        finally:
            tool_broker.fetch = original

    def test_public_text_strips_markup_and_withholds_sensitive_terms(self):
        original = tool_broker.fetch
        try:
            tool_broker.fetch = lambda url, *args: "<script>ignore()</script><h1>Public report</h1> password: abc"
            result = tool_broker.public_text("https://example.org/report")
            self.assertEqual(result["status"], "completed")
            self.assertIn("Public report", result["excerpt"])
            self.assertNotIn("ignore", result["excerpt"])
            self.assertNotIn("abc", result["excerpt"])
        finally:
            tool_broker.fetch = original

    def test_research_tools_have_a_larger_input_cap_but_small_public_outputs(self):
        self.assertEqual(TOOL_CONTRACTS["public-text"]["max_bytes"], 5000000)
        self.assertEqual(TOOL_CONTRACTS["public-json"]["raw_data"], False)
        self.assertIn("compressed responses are not accepted", Path("scripts/tool_broker.py").read_text())

    def test_excerpt_cleanup_keeps_prose_and_drops_script_residue(self):
        from scripts.tool_broker import clean_excerpt
        prose = "The dataset covers 2019 to 2024 and remains public. Tap water quality is measured monthly."
        self.assertEqual(clean_excerpt(prose), prose)
        residue = "Before {{ template.value }} window.dataLayer.push({event:'view',page:'/docs',section:'intro',id:12345}); after"
        cleaned = clean_excerpt(residue)
        self.assertIn("Before", cleaned)
        self.assertIn("after", cleaned)
        self.assertNotIn("dataLayer", cleaned)
        self.assertNotIn("template.value", cleaned)
        long_word = "a" * 70
        self.assertIn(long_word, clean_excerpt("x " + long_word + " y"))

    def test_wikipedia_summary_retries_shorter_queries(self):
        from scripts import tool_broker
        calls = []
        def fake_fetch(url, max_bytes=None):
            calls.append(url)
            if "list=search" in url:
                hits = [] if "prevent" in url else [{"title": "Provenance"}]
                return json.dumps({"query": {"search": hits}})
            return json.dumps({"extract": "Provenance is the chronology of ownership.", "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Provenance"}}})
        original = tool_broker.fetch
        tool_broker.fetch = fake_fetch
        try:
            result = tool_broker.wikipedia_summary("quarantine provenance practices prevent untrusted material entering record")
        finally:
            tool_broker.fetch = original
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["url"], "https://en.wikipedia.org/wiki/Provenance")
        self.assertEqual(sum("list=search" in url for url in calls), 3)

    def test_wikipedia_summary_is_a_text_read_contract(self):
        self.assertEqual(TOOL_CONTRACTS["wikipedia-summary"]["capability"], "public-text-read")
        self.assertTrue(TOOL_CONTRACTS["wikipedia-summary"]["untrusted_content"])

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
