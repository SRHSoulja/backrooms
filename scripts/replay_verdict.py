#!/usr/bin/env python3
"""Recompute the reproducible judge's scores for a corroboration record from the
quoted passages in the ledger, and say whether the recorded relation stands.

    python3 scripts/replay_verdict.py pair-52cb76c4a1ce55d78e39
    python3 scripts/replay_verdict.py --all --json

Requires the judge's dependencies (requirements-judge.txt) and
BACKROOMS_INFERENCE_JUDGE=1; the models download once into the cache.
"""

import argparse
import json
import os
from pathlib import Path

try:
    from scripts import inference_judge
    from scripts.corroboration import inference_stands, load_records
except ImportError:
    import inference_judge
    from corroboration import inference_stands, load_records

ROOT = Path(__file__).resolve().parents[1]


def findings_by_id(path):
    rows = {}
    for line in Path(path).read_text().splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("id"):
            rows[item["id"]] = item
    return rows


def replay(record, findings):
    ids = record.get("finding_ids") or []
    first, second = findings.get(ids[0]) if ids else None, findings.get(ids[1]) if len(ids) > 1 else None
    if not first or not second:
        return {"id": record.get("id"), "error": "findings missing from the ledger"}
    scores = inference_judge.judge_pair(first, second)
    stored = record.get("inference") or {}
    ok, reason = inference_stands({"relation": record.get("model_relation") or record.get("relation"), "inference": scores})
    return {"id": record.get("id"), "relation": record.get("relation"), "model_relation": record.get("model_relation"),
            "stored_support": stored.get("support"), "recomputed_support": (scores or {}).get("support"),
            "stored_contradiction": stored.get("contradiction"), "recomputed_contradiction": (scores or {}).get("contradiction"),
            "matches_stored": (stored.get("support") == (scores or {}).get("support")) if stored else None,
            "model_relation_stands": ok, "reason": reason, "model": (scores or {}).get("model"), "revision": (scores or {}).get("revision")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pair_id", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--corroborations", default=str(ROOT / "state/corroborations.jsonl"))
    parser.add_argument("--findings", default=str(ROOT / "state/findings.jsonl"))
    args = parser.parse_args()
    os.environ.setdefault("BACKROOMS_INFERENCE_JUDGE", "1")
    if not inference_judge.available():
        raise SystemExit("inference judge unavailable: " + inference_judge.status().get("reason", ""))
    findings = findings_by_id(args.findings)
    records = load_records(args.corroborations)
    if not args.all:
        records = [item for item in records if item.get("id") == args.pair_id]
        if not records:
            raise SystemExit(f"no record {args.pair_id}")
    results = [replay(record, findings) for record in records if record.get("judge") != "term-gate"]
    if args.json:
        print(json.dumps(results, indent=1))
        return
    for item in results:
        if item.get("error"):
            print(item["id"], item["error"])
            continue
        print(f"{item['id']} {item['relation']:<11} model={item['model_relation']:<11} support={item['recomputed_support']} "
              f"contradiction={item['recomputed_contradiction']} stands={item['model_relation_stands']} {item['reason']}")


if __name__ == "__main__":
    main()
