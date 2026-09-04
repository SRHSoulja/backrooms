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

    def test_public_search_falls_back_to_wikipedia_search_when_the_engine_blocks(self):
        original = tool_broker.fetch
        try:
            def fake_fetch(url, max_bytes=None, user_agent=None):
                if "duckduckgo" in url:
                    return "<html>anomaly: no parsed results</html>"
                if "en.wikipedia.org/w/api.php" in url:
                    return json.dumps({"query": {"search": [{"title": "Public dataset"}, {"title": "Unrelated thing"}]}})
                raise AssertionError("unexpected fetch " + url)
            tool_broker.fetch = fake_fetch
            result = tool_broker.public_search("public dataset")
            self.assertEqual(result["source"], "https://en.wikipedia.org/")
            self.assertEqual(result["results"][0]["url"], "https://en.wikipedia.org/wiki/Public_dataset")
            self.assertEqual([item["title"] for item in result["results"]], ["Public dataset"])
            self.assertEqual(result["query"], "public dataset")
        finally:
            tool_broker.fetch = original

    def test_public_search_drops_results_that_match_only_the_first_word(self):
        original = tool_broker.fetch
        try:
            tool_broker.fetch = lambda url, max_bytes=None, user_agent=None: (
                '<a class="result__a" href="https://example.org/wall">WALL Definition</a>'
                '<a class="result__a" href="https://example.org/wsj">The Wall Street Journal - Dow Jones</a>') if "duckduckgo" in url else "{}"
            result = tool_broker.public_search("wall street journal dow jones company")
            self.assertEqual([item["url"] for item in result["results"]], ["https://example.org/wsj"])
        finally:
            tool_broker.fetch = original

    def test_openalex_summary_returns_the_best_abstract_with_provenance(self):
        original = tool_broker.fetch
        try:
            payload = {"results": [
                {"title": "Inborn errors of immunity", "doi": "https://doi.org/10.1/immune", "primary_location": {"landing_page_url": "https://doi.org/10.1/immune"},
                 "abstract_inverted_index": {"Errors": [0], "of": [1], "immunity": [2]}},
                {"title": "Sampling error in opinion polls", "doi": "https://doi.org/10.1/polls", "primary_location": {"landing_page_url": "https://journals.example/polls"},
                 "abstract_inverted_index": {"Opinion": [0], "polls": [1], "carry": [2], "sampling": [3], "error": [4]}}]}
            tool_broker.fetch = lambda url, max_bytes=None, user_agent=None: json.dumps(payload)
            result = tool_broker.openalex_summary("opinion polls sampling error")
            self.assertEqual((result["status"], result["url"]), ("completed", "https://journals.example/polls"))
            self.assertIn("Opinion polls carry sampling error", result["excerpt"])
            tool_broker.fetch = lambda url, max_bytes=None, user_agent=None: json.dumps({"results": []})
            self.assertEqual(tool_broker.openalex_summary("opinion polls sampling error")["status"], "no-match")
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
                hits = [] if "prevent" in url else [
                    {"title": "Quarantine", "snippet": "isolation of people during an epidemic"},
                    {"title": "Provenance", "snippet": "the chronology of ownership and custody of a record, used to judge untrusted material"}]
                return json.dumps({"query": {"search": hits}})
            assert "Provenance" in url, url
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

    def test_arxiv_summary_picks_the_best_matching_abstract(self):
        from scripts import tool_broker
        atom = ("<feed xmlns='http://www.w3.org/2005/Atom'>"
                "<entry><id>http://arxiv.org/abs/1111.1111v1</id><title>Bread baking dynamics</title><summary>Yeast and ovens.</summary></entry>"
                "<entry><id>http://arxiv.org/abs/2222.2222v2</id><title>Agent discovery cards for interoperability</title>"
                "<summary>We study how agents publish discovery documents to interoperate.</summary></entry></feed>")
        original = tool_broker.fetch
        tool_broker.fetch = lambda url, max_bytes=None: atom
        try:
            result = tool_broker.arxiv_summary("agent discovery cards interoperability")
        finally:
            tool_broker.fetch = original
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["url"], "https://arxiv.org/abs/2222.2222v2")
        self.assertIn("publish discovery documents", result["excerpt"])

    def test_github_readme_returns_repository_prose(self):
        from scripts import tool_broker
        def fake_fetch(url, max_bytes=None):
            if "api.github.com" in url:
                return json.dumps({"items": [{"full_name": "acme/agent-cards", "description": "Discovery cards for agents",
                                              "html_url": "https://github.com/acme/agent-cards"}]})
            if "raw.githubusercontent.com" in url:
                assert url.endswith("/HEAD/README.md"), url
                return "# Agent cards\n\nThis library publishes a [discovery document](docs/x.md) for every agent.\n```py\nprint(1)\n```\n"
            raise AssertionError(url)
        original = tool_broker.fetch
        tool_broker.fetch = fake_fetch
        try:
            result = tool_broker.github_readme("agent discovery cards")
        finally:
            tool_broker.fetch = original
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["url"], "https://github.com/acme/agent-cards")
        self.assertIn("publishes a discovery document for every agent", result["excerpt"])
        self.assertNotIn("print(1)", result["excerpt"])
        self.assertNotIn("](", result["excerpt"])

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
