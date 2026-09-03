import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

from scripts import model_client


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def reply(text, prompt_tokens=100, completion_tokens=20):
    return FakeResponse(json.dumps({"choices": [{"message": {"content": text}}],
                                    "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}).encode())


class ModelClientTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_usage = model_client.USAGE
        model_client.USAGE = Path(self.temporary.name) / "usage.json"
        self.original_secrets = dict(model_client.SECRETS)
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"MISTRAL_API_KEY": "test-mistral", "GROQ_API_KEY": "test-groq"})
        self.sleeps = []

    def tearDown(self):
        model_client.USAGE = self.original_usage
        model_client.SECRETS.clear()
        model_client.SECRETS.update(self.original_secrets)
        self.temporary.cleanup()

    def test_secrets_file_is_parsed_and_never_exported(self):
        path = Path(self.temporary.name) / "env"
        path.write_text("# comment\nMISTRAL_API_KEY = 'abc'\nEMPTY=\nBAD LINE\nGEMINI_API_KEY=\"g\"\n")
        values = model_client._load_env_file(path)
        self.assertEqual(values, {"MISTRAL_API_KEY": "abc", "EMPTY": "", "GEMINI_API_KEY": "g"})
        self.assertNotIn("MISTRAL_API_KEY", os.environ)

    def test_providers_are_ordered_with_local_last_and_keys_gate_inclusion(self):
        names = [item["name"] for item in model_client.providers("http://127.0.0.1:9")]
        self.assertEqual(names, ["mistral", "groq", "local"])
        self.assertTrue(model_client.configured_remote())
        mistral = model_client.providers()[0]
        self.assertEqual((mistral["model"], mistral["api_key"]), ("mistral-small-latest", "test-mistral"))
        self.assertTrue(all("Bearer" not in json.dumps(item) for item in model_client.usage_summary()["providers"]))

    def test_router_falls_over_on_rate_limit_and_records_usage(self):
        calls = []

        def opener(request, timeout=0):
            calls.append((request.full_url, request.headers.get("Authorization")))
            if "mistral" in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "20"}, io.BytesIO(b""))
            return reply('{"ok": true}')

        content, provider = model_client.complete([{"role": "user", "content": "hi"}], schema={"type": "object"},
                                                  base_url="http://127.0.0.1:9", opener=opener, sleep=self.sleeps.append, clock=lambda: 1000.0)
        self.assertEqual((content, provider), ('{"ok": true}', "groq"))
        self.assertEqual(calls[0][1], "Bearer test-mistral")
        self.assertEqual(calls[1][1], "Bearer test-groq")
        summary = {item["name"]: item for item in model_client.usage_summary("http://127.0.0.1:9")["providers"]}
        self.assertEqual(summary["groq"]["calls"], 1)
        self.assertEqual(summary["groq"]["input_tokens"], 100)
        self.assertEqual(summary["mistral"]["errors"], 1)
        self.assertIn("429", summary["mistral"]["last_error"])
        # Mistral is now cooling down, so the next call goes straight to Groq without touching it.
        calls.clear()
        model_client.complete([{"role": "user", "content": "again"}], base_url="http://127.0.0.1:9", opener=opener,
                              sleep=self.sleeps.append, clock=lambda: 1001.0)
        self.assertTrue(all("mistral" not in url for url, _auth in calls))

    def test_bad_credentials_disable_a_provider_and_all_failures_raise(self):
        def opener(request, timeout=0):
            raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, io.BytesIO(b""))

        with self.assertRaises(model_client.ModelUnavailable):
            model_client.complete([{"role": "user", "content": "x"}], base_url="http://127.0.0.1:9", opener=opener, sleep=self.sleeps.append)
        summary = {item["name"]: item for item in model_client.usage_summary("http://127.0.0.1:9")["providers"]}
        self.assertEqual(summary["mistral"]["status"], "disabled")

    def test_daily_request_budget_skips_a_provider(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"GROQ_API_KEY": "g", "BACKROOMS_GROQ_RPD": "1"})
        seen = []

        def opener(request, timeout=0):
            seen.append(request.full_url)
            return reply("ok")

        model_client.complete([{"role": "user", "content": "1"}], base_url="http://127.0.0.1:9", opener=opener, sleep=self.sleeps.append)
        model_client.complete([{"role": "user", "content": "2"}], base_url="http://127.0.0.1:9", opener=opener, sleep=self.sleeps.append)
        self.assertIn("groq", seen[0])
        self.assertIn("127.0.0.1:9", seen[1])

    def test_pacing_sleeps_between_calls_on_a_rate_limited_provider(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"GROQ_API_KEY": "g"})
        opener = lambda request, timeout=0: reply("ok")
        clock = iter([100.0, 100.0, 100.0, 101.0, 101.0, 101.0]).__next__
        model_client.complete([{"role": "user", "content": "1"}], base_url="http://127.0.0.1:9", opener=opener, sleep=self.sleeps.append, clock=clock)
        model_client.complete([{"role": "user", "content": "2"}], base_url="http://127.0.0.1:9", opener=opener, sleep=self.sleeps.append, clock=clock)
        self.assertTrue(self.sleeps and 0 < self.sleeps[0] <= 15)

    def test_schema_hint_for_providers_without_schema_mode_and_json_recovery(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"OPENROUTER_API_KEY": "o"})
        payloads = []

        def opener(request, timeout=0):
            payloads.append(json.loads(request.data))
            return reply('Here you go: {"action": "STAY"} thanks')

        parsed, provider = model_client.complete_json([{"role": "user", "content": "decide"}], schema={"type": "object"},
                                                      base_url="http://127.0.0.1:9", opener=opener, sleep=self.sleeps.append)
        self.assertEqual((parsed, provider), ({"action": "STAY"}, "openrouter"))
        self.assertNotIn("response_format", payloads[0])
        self.assertIn("matching this schema", payloads[0]["messages"][-1]["content"])

    def test_child_env_strips_credentials(self):
        env = model_client.child_env({"PATH": "/usr/bin", "MISTRAL_API_KEY": "x", "GITHUB_TOKEN": "y", "LANG": "C", "WALLET_SECRET": "z"})
        self.assertEqual(env, {"PATH": "/usr/bin", "LANG": "C"})


if __name__ == "__main__":
    unittest.main()
