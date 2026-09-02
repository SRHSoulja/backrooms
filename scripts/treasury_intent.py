#!/usr/bin/env python3
"""Prepare a bounded treasury intent; never signs or broadcasts transactions."""
import argparse
import json
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "wallet/treasury-policy.json"
INTENTS = ROOT / "state/treasury-intents.json"

parser = argparse.ArgumentParser()
parser.add_argument("--asset", required=True, choices=("SOL", "USDC"))
parser.add_argument("--amount", required=True, type=float)
parser.add_argument("--destination", required=True)
parser.add_argument("--purpose", required=True, help="short non-sensitive purpose")
args = parser.parse_args()
policy = json.loads(POLICY.read_text())
purpose = args.purpose.strip()[:220]
allowed = policy.get("enabled") and args.asset in policy.get("allowed_assets", [])
allowlisted = args.destination in policy.get("allowlisted_destinations", [])
within_cap = args.amount > 0 and args.amount <= float(policy.get("max_per_transaction_usd", 0))
status = "ready-for-simulation" if allowed and allowlisted and within_cap and purpose else "blocked-by-policy"
intent = {"id": f"intent-{uuid.uuid4().hex[:12]}", "created_at": int(time.time()), "asset": args.asset,
          "amount": args.amount, "destination": args.destination, "purpose": purpose,
          "status": status, "simulation": "required", "signed": False, "broadcast": False}
data = json.loads(INTENTS.read_text()) if INTENTS.exists() else {"intents": []}
data.setdefault("intents", []).append(intent)
data["intents"] = data["intents"][-100:]
INTENTS.parent.mkdir(parents=True, exist_ok=True)
INTENTS.write_text(json.dumps(data, indent=2) + "\n")
print(json.dumps({"tool": "treasury-intent", "status": status, "intent_id": intent["id"],
                  "signed": False, "broadcast": False, "reason": "policy, allowlist, cap, and signer controls apply"}))
