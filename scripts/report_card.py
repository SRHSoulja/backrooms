#!/usr/bin/env python3
"""The living report: every number in it comes from the ledgers, none from a model.

    python3 scripts/report_card.py            # prints Markdown
    python3 scripts/report_card.py --json     # the same facts as JSON
"""

import argparse
import collections
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
DOCS = ROOT / "docs"


def _rows(path):
    rows = []
    try:
        for line in Path(path).read_text().splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def _json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return default


def facts(state=STATE, docs=DOCS, now=None):
    now = now or datetime.now(timezone.utc)
    day_zero = _json(state / "day-zero.json", {})
    zero_cycle = int(day_zero.get("cycle") or 0)
    world = _json(state / "world.json", {})
    health = _json(docs / "health.json", {})
    findings = [row for row in _rows(state / "findings.jsonl") if int(row.get("cycle") or 0) >= zero_cycle]
    pairs = [row for row in _rows(state / "corroborations.jsonl") if int(row.get("cycle") or 0) >= zero_cycle]
    events = [row for row in _rows(state / "archive" / "events.jsonl") if int(row.get("cycle") or 0) >= zero_cycle]
    lines = _json(state / "research-lines.json", {}).get("lines", [])
    tools = _json(state / "tool-proposals.json", {}).get("proposals", [])
    disagreements = _json(docs / "disagreements.json", {}).get("entries", [])
    accepted = [row for row in findings if row.get("status") in ("unreviewed", "accepted", "supported")]
    rejected = [row for row in findings if row.get("status") == "rejected"]
    retracted = [row for row in findings if row.get("status") == "retracted"]
    reasons = collections.Counter(str(row.get("rejection_reason") or "unstated") for row in rejected)
    relations = collections.Counter(str(row.get("relation")) for row in pairs)
    judged_by_model = [row for row in pairs if row.get("judge") != "term-gate"]
    scored = [row for row in judged_by_model if isinstance(row.get("inference"), dict)]
    agreement = collections.Counter()
    for row in scored:
        agreement[(str(row.get("model_relation")), str(row["inference"].get("verdict")))] += 1
    rooms = [room for room in world.get("rooms", []) if room.get("founded_via") == "evidence-ledger"]
    rooms += [room for room in world.get("withdrawn_rooms", []) if room.get("founded_via") == "evidence-ledger"]
    withdrawn = [room for room in rooms if room.get("status") == "retracted" or room.get("collapsed_at")]
    withdrawal_reasons = collections.Counter(re.sub(r"\s*\([^)]*\)\s*$", "", str(room.get("retraction_reason") or "collapsed")) for room in withdrawn)
    registry = _json(state / "local-agents.json", {}).get("agents", [])
    zero_at = str(day_zero.get("at") or "")
    hires = [agent for agent in registry if str(agent.get("recorded_at") or agent.get("interviewed_at") or "") >= zero_at]
    retirements = [agent for agent in hires if agent.get("status") in ("retired", "fired", "departed")]
    providers = {item.get("name"): item.get("calls", 0) for item in (health.get("model_usage") or {}).get("providers", [])}
    started = day_zero.get("at")
    unattended_days = None
    if started:
        try:
            unattended_days = round((now - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds() / 86400, 2)
        except ValueError:
            unattended_days = None
    return {
        "generated_at": now.isoformat(), "day_zero": day_zero, "cycle": world.get("cycle"),
        "cycles_since_day_zero": (int(world.get("cycle") or 0) - zero_cycle) if world.get("cycle") else None,
        "days_since_day_zero": unattended_days,
        "findings": {"accepted": len(accepted), "rejected": len(rejected), "retracted": len(retracted),
                     "rejection_reasons": reasons.most_common(12)},
        "pairs": {"judged": len(pairs), "by_relation": dict(relations), "model_judged": len(judged_by_model), "inference_scored": len(scored),
                  "model_vs_inference": [{"model": key[0], "inference": key[1], "pairs": value} for key, value in sorted(agreement.items())]},
        "rooms": {"founded": len(rooms), "standing": len([room for room in rooms if room not in withdrawn]), "withdrawn": len(withdrawn),
                  "withdrawal_reasons": withdrawal_reasons.most_common(12),
                  "list": [{"id": room.get("id"), "founded_cycle": room.get("founded_cycle"), "status": room.get("status", "open"),
                            "reason": room.get("retraction_reason")} for room in rooms]},
        "lines": {"opened": len(lines), "closed": len([line for line in lines if line.get("status") == "closed"]),
                  "close_reasons": collections.Counter(str(line.get("closed_reason")) for line in lines if line.get("status") == "closed").most_common(8),
                  "origins": collections.Counter(str(line.get("origin", "")).split(":")[0] for line in lines).most_common(6)},
        "disagreements": {"total": len(disagreements), "open": sum(item.get("status") == "open" for item in disagreements),
                          "settled": sum(item.get("status") == "settled" for item in disagreements)},
        "tools": collections.Counter(str(item.get("status")) for item in tools).most_common(6),
        "roster": {"hired": len(hires), "retired": len(retirements), "active": health.get("active_residents")},
        "event_chain": health.get("event_chain"), "providers": providers,
        "inference_judge": {key: (health.get("inference_judge") or {}).get(key) for key in ("available", "scored_pairs")},
    }


def markdown(data):
    lines = ["# Backrooms report", "",
             f"Generated {data['generated_at'][:19]} UTC from the ledgers. Day zero: cycle {data['day_zero'].get('cycle')} at "
             f"{str(data['day_zero'].get('at', ''))[:19]} UTC. Now at cycle {data['cycle']}, "
             f"{data['cycles_since_day_zero']} cycles and {data['days_since_day_zero']} days later, with no human step in the loop.", ""]
    f = data["findings"]
    lines += ["## Findings", "", f"Accepted {f['accepted']}, rejected {f['rejected']}, retracted {f['retracted']}.", ""]
    if f["rejection_reasons"]:
        lines += ["| Rejection reason | Findings |", "|---|---|"] + [f"| {reason} | {count} |" for reason, count in f["rejection_reasons"]] + [""]
    p = data["pairs"]
    lines += ["## Judged pairs", "", f"{p['judged']} pairs judged ({p['model_judged']} by the language model, the rest settled by the term gate); "
              f"{p['inference_scored']} carry the reproducible judge's scores.", "",
              "| Relation | Pairs |", "|---|---|"] + [f"| {relation} | {count} |" for relation, count in sorted(p["by_relation"].items())] + [""]
    if p["model_vs_inference"]:
        lines += ["| Language model said | Inference judge said | Pairs |", "|---|---|---|"] + \
                 [f"| {row['model']} | {row['inference']} | {row['pairs']} |" for row in p["model_vs_inference"]] + [""]
    r = data["rooms"]
    lines += ["## Rooms", "", f"{r['founded']} rooms founded from evidence since day zero; {r['standing']} standing, {r['withdrawn']} withdrawn by rule.", ""]
    if r["withdrawal_reasons"]:
        lines += ["| Withdrawal reason | Rooms |", "|---|---|"] + [f"| {reason} | {count} |" for reason, count in r["withdrawal_reasons"]] + [""]
    l = data["lines"]
    lines += ["## Research lines", "", f"{l['opened']} lines opened, {l['closed']} closed.", ""]
    if l["close_reasons"]:
        lines += ["| Closing reason | Lines |", "|---|---|"] + [f"| {reason} | {count} |" for reason, count in l["close_reasons"]] + [""]
    d = data["disagreements"]
    lines += ["## Disagreements", "", f"{d['total']} recorded, {d['open']} open, {d['settled']} settled by a third source.", ""]
    lines += ["## Tools", "", ", ".join(f"{status}: {count}" for status, count in data["tools"]) or "No tool proposals yet.", ""]
    ro = data["roster"]
    lines += ["## Roster", "", f"{ro['hired']} hired, {ro['retired']} retired since day zero; {ro['active']} active now.", ""]
    chain = data.get("event_chain") or {}
    lines += ["## Integrity", "", f"Event chain: {chain.get('count')} events, verified={chain.get('verified')}, head `{str(chain.get('head', ''))[:16]}…`. "
              f"Inference judge available={data['inference_judge'].get('available')}, scored pairs={data['inference_judge'].get('scored_pairs')}.", "",
              "Model calls today by provider: " + (", ".join(f"{name} {count}" for name, count in data["providers"].items()) or "none recorded") + ".", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    data = facts()
    print(json.dumps(data, indent=1, default=str) if args.json else markdown(data))


if __name__ == "__main__":
    main()
