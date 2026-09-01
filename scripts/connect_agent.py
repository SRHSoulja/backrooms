#!/usr/bin/env python3
"""Ask a local OpenAI-compatible model to respond as a Backrooms resident."""

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resident", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--base-url", default=os.getenv("BACKROOMS_LLM_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--model", default=os.getenv("BACKROOMS_LLM_MODEL", "local"))
    parser.add_argument("--allow-external", action="store_true")
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} and not args.allow_external:
        raise SystemExit("refusing non-local endpoint; review scope, then pass --allow-external")
    system = (f"You are {args.resident}, a resident of the Backrooms. "
              "Separate observations, inferences, and uncertainties. "
              "Do not claim sentience or access you do not have.")
    body = json.dumps({"model": args.model, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": args.message}],
        "temperature": 0.4, "max_tokens": 400}).encode()
    request = urllib.request.Request(args.base_url.rstrip("/") + "/v1/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"connector unavailable: {exc}")
    try:
        print(result["choices"][0]["message"]["content"].strip())
    except (KeyError, IndexError, TypeError):
        raise SystemExit("connector returned an unexpected response shape")


if __name__ == "__main__":
    main()
