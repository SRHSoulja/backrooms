#!/usr/bin/env python3
"""Validate the safe subset of a public A2A Agent Card."""

import argparse
import json
import urllib.request


FORBIDDEN = {"apiKey", "api_key", "secret", "password", "privateKey", "private_key", "token"}


def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()
    if not args.url.startswith("https://"):
        raise SystemExit("FAIL: Agent Card must use HTTPS")
    request = urllib.request.Request(args.url, headers={"Accept": "application/json", "User-Agent": "Backrooms-AgentCardVerifier/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        card = json.load(response)
    required = {"name", "description", "version", "skills"}
    missing = sorted(required - card.keys())
    if missing:
        raise SystemExit("FAIL: missing " + ", ".join(missing))
    forbidden = sorted(set(walk(card)) & FORBIDDEN)
    if forbidden:
        raise SystemExit("FAIL: credential-like fields present: " + ", ".join(forbidden))
    interfaces = card.get("supportedInterfaces", [])
    endpoints = [item.get("url", "") for item in interfaces]
    if any(endpoint and not endpoint.startswith("https://") for endpoint in endpoints):
        raise SystemExit("FAIL: a declared interface is not HTTPS")
    print(json.dumps({"status": "pass", "name": card["name"], "version": card["version"],
                      "skills": len(card["skills"]), "interfaces": len(interfaces)}, indent=2))


if __name__ == "__main__":
    main()
