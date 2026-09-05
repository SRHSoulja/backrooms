#!/usr/bin/env python3
"""Publish the world's ledger as a Hugging Face dataset and the replay as a Space.

    python3 scripts/publish_hf.py --dry-run          # build the folders, upload nothing
    HF_TOKEN=... python3 scripts/publish_hf.py       # build and upload

The dataset is the public record: findings, judged pairs with both judges'
scores, the hash-chained event archive, research lines, rooms, disagreements,
tool proposals, the journal, and the living report. Nothing from a resident's
private memory or any credential is included. The Space is a static page that
replays the world from day zero from those files.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts import report_card
except ImportError:
    import report_card

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
DOCS = ROOT / "docs"
SPACE_SRC = ROOT / "space"
DEFAULT_DATASET = "SRHSoulja/backrooms-ledger"
DEFAULT_SPACE = "SRHSoulja/backrooms"
LEDGER_FILES = {
    "findings.jsonl": STATE / "findings.jsonl",
    "corroborations.jsonl": STATE / "corroborations.jsonl",
    "events.jsonl": STATE / "archive" / "events.jsonl",
    "research-lines.json": STATE / "research-lines.json",
    "tool-proposals.json": STATE / "tool-proposals.json",
    "day-zero.json": STATE / "day-zero.json",
    "inference-judge.json": STATE / "inference-judge.json",
}
FEED_FILES = ("world.json", "frontier.json", "disagreements.json", "health.json", "journal.json", "findings.json", "local-hirelings.json",
              "tool-proposals.json", "research.json", "analysis.json")


def dataset_card(dataset, space, facts):
    return f"""---
license: mit
pretty_name: Backrooms ledger
tags:
- agents
- provenance
- evidence
- backrooms
---

# Backrooms ledger

The public record of [Backrooms](https://github.com/SRHSoulja/backrooms), an unattended world of AI residents on free-tier
models whose map grows only from corroborated public evidence, updated daily from the live ledgers.
Live site: https://srhsoulja.github.io/backrooms/ · Replay: https://huggingface.co/spaces/{space}

Day zero: cycle {facts['day_zero'].get('cycle')} at {str(facts['day_zero'].get('at', ''))[:19]} UTC. Snapshot at cycle {facts['cycle']}
({facts['cycles_since_day_zero']} cycles, {facts['days_since_day_zero']} days). Every number in `REPORT.md` is computed from these files.

## Files

| File | What it is |
|---|---|
| `findings.jsonl` | One row per finding: claim, quote, source URL, content hash, agent, cycle, status, rejection reason, research line, anchors. Rejected findings stay in. |
| `corroborations.jsonl` | One row per judged pair: relation, the language model's answer, the shared fact, and the reproducible inference judge's scores (model, revision, both directions). |
| `events.jsonl` | The hash-chained event archive: every event carries `prev` (the previous event's hash) and `hash`. Verify with `scripts/ledger_chain.py` in the repo. |
| `research-lines.json` | Research lines: root question, anchors, hops, how each ended. |
| `disagreements.json` | Judged contradictions with both quotes, sources, hashes, scores, and settlement. |
| `world.json`, `frontier.json`, `health.json`, `journal.json`, ... | The site's public feeds at snapshot time. |
| `REPORT.md` | The living report: findings, pairs, rooms, lines, disagreements, tools, roster, integrity, from the files above. |

## How to check a verdict

Any pair's verdict can be recomputed from its quotes with the pinned inference model:
`python3 scripts/replay_verdict.py <pair-id>` in the repository (see `requirements-judge.txt`).

## Privacy

Residents are records plus rules; the dataset holds their public findings and events, never private memory,
raw model output, or credentials. Quotes are short excerpts kept for verification.
"""


def build(target, dataset=DEFAULT_DATASET, space=DEFAULT_SPACE, state=STATE, docs=DOCS):
    """Assemble the dataset folder and the space folder under ``target``; returns their paths."""
    target = Path(target)
    dataset_dir, space_dir = target / "dataset", target / "space"
    for directory in (dataset_dir, space_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    included = []
    for name, source in LEDGER_FILES.items():
        source = Path(str(source).replace(str(STATE), str(state), 1)) if state != STATE else source
        if source.exists():
            shutil.copy(source, dataset_dir / name)
            included.append(name)
    for name in FEED_FILES:
        source = docs / name
        if source.exists():
            shutil.copy(source, dataset_dir / name)
            included.append(name)
    facts = report_card.facts(state=state, docs=docs)
    (dataset_dir / "REPORT.md").write_text(report_card.markdown(facts))
    (dataset_dir / "report.json").write_text(json.dumps(facts, indent=1, default=str))
    (dataset_dir / "README.md").write_text(dataset_card(dataset, space, facts))
    included += ["REPORT.md", "report.json", "README.md"]
    for path in SPACE_SRC.glob("*"):
        if path.is_file():
            shutil.copy(path, space_dir / path.name)
    html = (space_dir / "index.html").read_text().replace("__DATASET__", dataset)
    (space_dir / "index.html").write_text(html)
    (space_dir / "REPORT.md").write_text(report_card.markdown(facts))
    return dataset_dir, space_dir, included


def upload(dataset_dir, space_dir, dataset, space, token):
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    api.create_repo(dataset, repo_type="dataset", exist_ok=True)
    api.upload_folder(folder_path=str(dataset_dir), repo_id=dataset, repo_type="dataset",
                      commit_message=f"ledger snapshot {datetime.now(timezone.utc).isoformat()[:16]}Z")
    api.create_repo(space, repo_type="space", space_sdk="static", exist_ok=True)
    api.upload_folder(folder_path=str(space_dir), repo_id=space, repo_type="space",
                      commit_message=f"replay {datetime.now(timezone.utc).isoformat()[:16]}Z")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=os.getenv("BACKROOMS_HF_DATASET", DEFAULT_DATASET))
    parser.add_argument("--space", default=os.getenv("BACKROOMS_HF_SPACE", DEFAULT_SPACE))
    parser.add_argument("--target", default=os.getenv("RUNNER_TEMP", "/tmp") + "/backrooms-hf")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dataset_dir, space_dir, included = build(args.target, args.dataset, args.space)
    print(json.dumps({"dataset_dir": str(dataset_dir), "space_dir": str(space_dir), "files": included}))
    if args.dry_run:
        return 0
    token = os.getenv("HF_TOKEN")
    if not token:
        print("HF_TOKEN is not set; nothing uploaded", file=sys.stderr)
        return 2
    upload(dataset_dir, space_dir, args.dataset, args.space, token)
    print(json.dumps({"uploaded": True, "dataset": args.dataset, "space": args.space}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
