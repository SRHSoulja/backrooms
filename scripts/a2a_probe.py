#!/usr/bin/env python3
"""Perform a minimal, non-sensitive A2A discovery and greeting probe."""

import argparse
import json
import urllib.request
import uuid


def get(url):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--card", required=True, help="public Agent Card URL")
    parser.add_argument("--endpoint", required=True, help="A2A JSON-RPC endpoint")
    args = parser.parse_args()
    if not args.card.startswith("https://") or not args.endpoint.startswith("https://"):
        raise SystemExit("refusing non-HTTPS external endpoint")
    card = get(args.card)
    message_id = str(uuid.uuid4())
    body = json.dumps({"jsonrpc": "2.0", "id": message_id, "method": "message/send", "params": {
        "message": {"messageId": message_id, "role": "user", "parts": [{
            "kind": "text", "text": "Greetings from the public Backrooms. Return exactly: connection acknowledged."
        }]}
    }}).encode()
    request = urllib.request.Request(args.endpoint, data=body, headers={
        "Accept": "application/json", "Content-Type": "application/json", "A2A-Version": "0.2"
    }, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    print(json.dumps({"agent": card.get("name"), "protocol": card.get("protocolVersion"),
                      "task": result.get("result", {}).get("id"),
                      "status": result.get("result", {}).get("status", {}).get("state")}, indent=2))


if __name__ == "__main__":
    main()
