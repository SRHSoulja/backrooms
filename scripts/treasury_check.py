#!/usr/bin/env python3
"""Read-only Solana treasury check; never loads or requests a private key."""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = "H2YvsxLQqbTVbJBxE6vXxpwHWWms89vCRzLHFhPHZA9S"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
RPC = "https://api.mainnet.solana.com"


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json", "User-Agent": "Backrooms-Treasury-Check/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if "error" in result:
        raise RuntimeError("rpc error")
    return result["result"]


try:
    sol = rpc("getBalance", [ADDRESS])["value"] / 1_000_000_000
    accounts = rpc("getTokenAccountsByOwner", [ADDRESS, {"mint": USDC_MINT}, {"encoding": "jsonParsed"}])["value"]
    usdc = sum(float(account["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmountString"] or 0) for account in accounts)
    snapshot = {"status": "online", "sol": sol, "usdc": usdc, "usdc_mint": USDC_MINT,
                "work_signal": "funds-available-for-human-review" if usdc or sol else "awaiting-funding",
                "signing": "disabled", "checked_at": datetime.now(timezone.utc).isoformat(),
                "privacy": "Public balances only; no private key or transaction authority used."}
except Exception as error:
    snapshot = {"status": "unavailable", "work_signal": "balance-check-failed", "error": type(error).__name__,
                "checked_at": datetime.now(timezone.utc).isoformat(), "privacy": "No private key was accessed."}
(ROOT / "docs/treasury.json").write_text(json.dumps(snapshot, indent=2) + "\n")
print(json.dumps(snapshot, indent=2))
