#!/usr/bin/env python3
"""Diagnose one model provider without printing anything secret: list the
models the key can see, show which one the router would choose, and make one
tiny chat call with it, reporting the HTTP status and the provider's message.

    python3 scripts/provider_probe.py gemini
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

try:
    from scripts import model_client
except ImportError:
    import model_client

REDACT = re.compile(r"[A-Za-z0-9_\-]{24,}")


def clean(text):
    return REDACT.sub("[redacted]", str(text or ""))[:600]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("provider")
    args = parser.parse_args()
    provider = next((item for item in model_client.providers() if item["name"] == args.provider), None)
    if provider is None:
        print(json.dumps({"provider": args.provider, "configured": False, "reason": "no key or not in the provider order"}))
        return 1
    report = {"provider": provider["name"], "configured_model": provider["model"], "base_url": provider["base_url"]}
    try:
        listed = model_client._list_models(provider)
        names = [str(item).split("/")[-1] for item in listed]
        report["models_listed"] = len(names)
        report["models"] = names[:60]
        report["chosen"] = model_client.choose_gemini_model(listed, provider["model"]) if provider.get("resolve_model") else provider["model"]
    except urllib.error.HTTPError as error:
        report["listing_error"] = {"status": error.code, "body": clean(error.read().decode("utf-8", "replace"))}
        report["chosen"] = provider["model"]
    except Exception as error:  # noqa: BLE001
        report["listing_error"] = {"type": type(error).__name__, "detail": clean(error)}
        report["chosen"] = provider["model"]
    trial = {**provider, "model": report["chosen"]}
    try:
        content, prompt_tokens, completion_tokens, limits = model_client._request(
            trial, [{"role": "user", "content": "Reply with the single word: ready"}], 0.0, 64, None, "probe", 60)
        report["chat"] = {"ok": True, "model": trial["model"], "reply": clean(content)[:40], "tokens": [prompt_tokens, completion_tokens], "limits": limits}
    except urllib.error.HTTPError as error:
        report["chat"] = {"ok": False, "model": trial["model"], "status": error.code, "body": clean(error.read().decode("utf-8", "replace"))}
    except Exception as error:  # noqa: BLE001
        report["chat"] = {"ok": False, "model": trial["model"], "type": type(error).__name__, "detail": clean(error)}
    print(json.dumps(report, indent=1))
    return 0 if report.get("chat", {}).get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
