import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

from scripts import model_client


class GeminiModelChoiceTests(unittest.TestCase):
    def test_newest_plain_flash_model_wins_and_variants_are_skipped(self):
        from scripts.model_client import choose_gemini_model
        ids = ["models/gemini-2.5-flash", "models/gemini-2.5-flash-lite", "models/gemini-3-flash-preview-11-2025",
               "models/gemini-3.5-flash", "models/gemini-3.5-flash-image", "models/gemini-3.8-flash-preview-08-2026",
               "models/gemini-3.5-pro", "models/gemini-live-2.5-flash", "models/gemini-2.5-flash-tts"]
        self.assertEqual(choose_gemini_model(ids, "gemini-2.5-flash"), "gemini-3.5-flash")
        self.assertEqual(choose_gemini_model([ids[2], ids[5], ids[1]], "gemini-2.5-flash"), "gemini-3.8-flash-preview-08-2026")
        self.assertEqual(choose_gemini_model(["models/gemini-2.5-flash-lite"], "gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(choose_gemini_model([], "fallback"), "fallback")


class ProviderOrderTests(unittest.TestCase):
    def test_preferred_providers_move_to_the_front_without_dropping_the_rest(self):
        from scripts.model_client import ordered_providers
        available = [{"name": "mistral"}, {"name": "mistral-8b"}, {"name": "gemini"}, {"name": "local"}]
        self.assertEqual([p["name"] for p in ordered_providers(available, ("gemini", "groq"))], ["gemini", "mistral", "mistral-8b", "local"])
        self.assertEqual([p["name"] for p in ordered_providers(available, None)], ["mistral", "mistral-8b", "gemini", "local"])
        self.assertEqual([p["name"] for p in ordered_providers(available, ("mistral-8b", "mistral"))], ["mistral-8b", "mistral", "gemini", "local"])


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def reply(text, prompt_tokens=100, completion_tokens=20, headers=None):
    response = FakeResponse(json.dumps({"choices": [{"message": {"content": text}}],
                                        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}).encode())
    response.headers = dict(headers or {})
    return response


class ModelClientTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_usage = model_client.USAGE
        model_client.USAGE = Path(self.temporary.name) / "usage.json"
        self.original_secrets = dict(model_client.SECRETS)
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"MISTRAL_API_KEY": "test-mistral", "GROQ_API_KEY": "test-groq", "BACKROOMS_PROVIDER_ORDER": "mistral,groq,local"})
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
        self.assertEqual((mistral["model"], mistral["api_key"]), ("ministral-14b-2512", "test-mistral"))
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

    def test_brief_429_retries_the_same_provider_once_and_records_no_error(self):
        attempts = []

        def opener(request, timeout=0):
            attempts.append(request.full_url)
            if "mistral" in request.full_url and len(attempts) == 1:
                raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "1"}, io.BytesIO(b""))
            return reply('{"ok": true}')

        content, provider = model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9",
                                                  opener=opener, sleep=self.sleeps.append, clock=lambda: 1000.0)
        self.assertEqual(provider, "mistral")
        self.assertEqual(len(attempts), 2)
        self.assertTrue(all("mistral" in url for url in attempts))
        self.assertIn(1, self.sleeps)
        summary = {item["name"]: item for item in model_client.usage_summary("http://127.0.0.1:9")["providers"]}
        self.assertEqual((summary["mistral"]["calls"], summary["mistral"]["errors"], summary["mistral"]["status"]), (1, 0, "ready"))

    def test_repeated_brief_429_cools_down_and_falls_through(self):
        attempts = []

        def opener(request, timeout=0):
            attempts.append(request.full_url)
            if "mistral" in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, io.BytesIO(b""))
            return reply('{"ok": true}')

        content, provider = model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9",
                                                  opener=opener, sleep=self.sleeps.append, clock=lambda: 1000.0)
        self.assertEqual(provider, "groq")
        self.assertEqual(sum("mistral" in url for url in attempts), 2)
        summary = {item["name"]: item for item in model_client.usage_summary("http://127.0.0.1:9")["providers"]}
        self.assertEqual(summary["mistral"]["errors"], 1)
        self.assertIn("429", summary["mistral"]["last_error"])
        attempts.clear()
        model_client.complete([{"role": "user", "content": "again"}], base_url="http://127.0.0.1:9", opener=opener,
                              sleep=self.sleeps.append, clock=lambda: 1001.0)
        self.assertTrue(all("mistral" not in url for url in attempts))

    def test_single_provider_waits_out_a_brief_cooldown_instead_of_failing(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"MISTRAL_API_KEY": "test-mistral", "BACKROOMS_PROVIDER_ORDER": "mistral,local"})
        clock = {"now": 1000.0}
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        attempts = []

        def opener(request, timeout=0):
            attempts.append(request.full_url)
            if "mistral" in request.full_url:
                if sum("mistral" in url for url in attempts) <= 2:
                    raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {},
                                                 io.BytesIO(b'{"message": "Requests rate limit exceeded"}'))
                return reply('{"ok": true}')
            raise urllib.error.URLError("connection refused")

        content, provider = model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9",
                                                  opener=opener, sleep=sleep, clock=lambda: clock["now"])
        self.assertEqual((content, provider), ('{"ok": true}', "mistral"))
        # one immediate retry, then the whole cooldown waited out, then success
        self.assertEqual(sum("mistral" in url for url in attempts), 3)
        self.assertTrue(any(seconds >= 15 for seconds in sleeps))
        summary = {item["name"]: item for item in model_client.usage_summary("http://127.0.0.1:9")["providers"]}
        self.assertEqual(summary["mistral"]["calls"], 1)
        self.assertIn("Requests rate limit exceeded", summary["mistral"]["last_error"])

    def test_long_cooldown_is_not_waited_out(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"MISTRAL_API_KEY": "test-mistral", "BACKROOMS_PROVIDER_ORDER": "mistral,local"})
        sleeps = []

        def opener(request, timeout=0):
            if "mistral" in request.full_url:
                raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "300"}, io.BytesIO(b""))
            raise urllib.error.URLError("connection refused")

        with self.assertRaises(model_client.ModelUnavailable):
            model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9",
                                  opener=opener, sleep=sleeps.append, clock=lambda: 1000.0)
        self.assertFalse(any(seconds > 60 for seconds in sleeps))

    def test_router_learns_per_minute_limits_from_headers_and_paces_to_them(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"MISTRAL_API_KEY": "test-mistral", "BACKROOMS_PROVIDER_ORDER": "mistral,local"})
        clock = {"now": 1000.0}
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        def opener(request, timeout=0):
            return reply('{"ok": true}', prompt_tokens=50, completion_tokens=10,
                         headers={"x-ratelimit-limit-req-minute": "2", "x-ratelimit-remaining-req-minute": "1",
                                  "x-ratelimit-limit-tokens-minute": "20000", "x-ratelimit-remaining-tokens-minute": "19000"})

        for _ in range(3):
            model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9",
                                  opener=opener, sleep=sleep, clock=lambda: clock["now"])
        summary = {item["name"]: item for item in model_client.usage_summary("http://127.0.0.1:9")["providers"]}
        self.assertEqual((summary["mistral"]["limit_rpm"], summary["mistral"]["limit_tpm"]), (2, 20000))
        self.assertEqual(summary["mistral"]["calls"], 3)
        # two calls fit in a minute; the third waited for the first to age out of the window
        self.assertTrue(any(seconds >= 30 for seconds in sleeps), sleeps)
        self.assertGreaterEqual(clock["now"] - 1000.0, 60.0)

    def test_router_waits_for_token_window_when_the_minute_budget_is_spent(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"MISTRAL_API_KEY": "test-mistral", "BACKROOMS_PROVIDER_ORDER": "mistral,local"})
        clock = {"now": 1000.0}
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        def opener(request, timeout=0):
            return reply('{"ok": true}', prompt_tokens=900, completion_tokens=100,
                         headers={"x-ratelimit-limit-req-minute": "100", "x-ratelimit-limit-tokens-minute": "2500"})

        for _ in range(3):
            model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9",
                                  opener=opener, sleep=sleep, clock=lambda: clock["now"])
        # 1000 tokens each against a 2500-token minute: the third call waits for the first to expire
        self.assertTrue(any(seconds >= 30 for seconds in sleeps), sleeps)
        summary = {item["name"]: item for item in model_client.usage_summary("http://127.0.0.1:9")["providers"]}
        self.assertEqual(summary["mistral"]["limit_tpm"], 2500)

    def test_remaining_zero_holds_the_provider_for_a_minute(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"MISTRAL_API_KEY": "test-mistral", "BACKROOMS_PROVIDER_ORDER": "mistral,local"})
        clock = {"now": 1000.0}
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        def opener(request, timeout=0):
            return reply('{"ok": true}', headers={"x-ratelimit-limit-req-minute": "10", "x-ratelimit-remaining-req-minute": "0"})

        model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9", opener=opener, sleep=sleep, clock=lambda: clock["now"])
        model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9", opener=opener, sleep=sleep, clock=lambda: clock["now"])
        self.assertTrue(any(seconds >= 59 for seconds in sleeps), sleeps)

    def test_mistral_family_shares_a_key_and_hands_over_per_model(self):
        model_client.SECRETS.clear()
        model_client.SECRETS.update({"MISTRAL_API_KEY": "test-mistral"})
        names = [p["name"] for p in model_client.providers("http://127.0.0.1:9")]
        self.assertEqual(names[:3], ["mistral", "mistral-8b", "mistral-small"])
        self.assertTrue(all(p["api_key"] == "test-mistral" for p in model_client.providers("http://127.0.0.1:9") if p["name"].startswith("mistral")))
        seen = []

        def opener(request, timeout=0):
            model = json.loads(request.data)["model"]
            seen.append(model)
            if model == "ministral-14b-2512":
                raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "30"}, io.BytesIO(b""))
            return reply('{"ok": true}')

        content, provider = model_client.complete([{"role": "user", "content": "hi"}], base_url="http://127.0.0.1:9",
                                                  opener=opener, sleep=self.sleeps.append, clock=lambda: 1000.0)
        self.assertEqual(provider, "mistral-8b")
        self.assertEqual(seen, ["ministral-14b-2512", "ministral-8b-2512"])
        summary = {item["name"]: item for item in model_client.usage_summary("http://127.0.0.1:9")["providers"]}
        self.assertEqual((summary["mistral"]["errors"], summary["mistral-8b"]["calls"]), (1, 1))

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
