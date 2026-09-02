#!/usr/bin/env python3
"""Keep the local model loaded and run bounded resident cycles periodically.

Runtime state stays local. With ``--publish``, only a privacy-filtered metric
record is committed to ``docs/local-cycle.json``.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state/world.json"
RUNTIME_STATE = ROOT / "state/local-runtime.json"
PUBLIC_CYCLE = ROOT / "docs/local-cycle.json"
PUBLIC_HISTORY = ROOT / "docs/action-history.json"


def wait_ready(url):
    for _ in range(120):
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("local model did not become ready")


def runtime_world():
    if RUNTIME_STATE.exists():
        with RUNTIME_STATE.open() as handle:
            return json.load(handle)
    with STATE.open() as handle:
        world = json.load(handle)
    world["events"] = world.get("events", [])[-20:]
    RUNTIME_STATE.write_text(json.dumps(world, indent=2) + "\n")
    return world


def metrics(result):
    words = lambda text: set(re.findall(r"[a-z]{4,}", text.lower()))
    echo, morrow = words(result.get("echo", "")), words(result.get("morrow", ""))
    union = echo | morrow
    overlap = len(echo & morrow) / len(union) if union else 1.0
    lower = result.get("morrow", "").lower()
    markers = [word for word in ("counterexample", "confound", "assumption", "missing control") if word in lower]
    return {"jaccard_overlap": round(overlap, 3), "morrow_audit_markers": markers,
            "distinction_status": "distinct" if overlap <= 0.75 and markers else "needs-audit"}


def action(base_url, cycle):
    """Run the closed-vocabulary local probe and retain aggregate evidence only."""
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/action_engine.py"),
        "--base-url", base_url, "--state", str(RUNTIME_STATE), "--cycle", str(cycle)],
        cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return {"action": "local-behavioral-probe", "status": "failed"}
    try:
        result = json.loads(completed.stdout)
        return {"action": result.get("action"), "probe": result.get("probe"),
                "status": result.get("status"), "hypothesis": result.get("hypothesis"),
                "responses": result.get("responses")}
    except json.JSONDecodeError:
        return {"action": "local-behavioral-probe", "status": "invalid-result"}


def next_question(base_url):
    """Ask residents for a bounded question; fall back if validation rejects both."""
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/self_prompt.py"),
        "--base-url", base_url, "--state", str(RUNTIME_STATE)], cwd=ROOT,
        capture_output=True, text=True, check=False)
    if completed.returncode == 0:
        try:
            proposals = json.loads(completed.stdout).get("proposals", [])
            for resident in ("Echo", "Morrow"):
                for proposal in proposals:
                    if proposal.get("resident") == resident and proposal.get("accepted"):
                        for line in proposal.get("proposal", "").splitlines():
                            if line.upper().startswith("QUESTION:"):
                                question = line.split(":", 1)[1].strip()
                                if question:
                                    return question[:300]
        except (json.JSONDecodeError, TypeError):
            pass
    return "Does continuity of memory, by itself, provide evidence of consciousness? Give one testable criterion."


def record(result):
    world = runtime_world()
    number = len(world["events"]) + 1
    world["cycle"] += 1
    world["events"].append({
        "id": f"event-{number:03d}", "actor": "system", "kind": "local-daemon-cycle",
        "purpose": "bounded resident council", "text": "Local council completed. Echo and Morrow outputs were generated from public shared state; see local daemon logs for raw output.",
        "confidence": 0.5, "cycle": world["cycle"], "recorded_at": datetime.now(timezone.utc).isoformat()
    })
    with RUNTIME_STATE.open("w") as handle:
        json.dump(world, handle, indent=2)
        handle.write("\n")
    return world


def publish(result, world):
    """Publish only safe metadata, and only when this checkout is clean."""
    fetch = subprocess.run(["git", "fetch", "origin", "main"], cwd=ROOT, capture_output=True)
    if fetch.returncode:
        print(json.dumps({"publish": "skipped", "reason": "fetch failed"}), flush=True)
        return
    sync = subprocess.run(["git", "merge", "--ff-only", "origin/main"], cwd=ROOT, capture_output=True)
    if sync.returncode:
        print(json.dumps({"publish": "skipped", "reason": "checkout not fast-forwardable"}), flush=True)
        return
    safe = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M",
        "runtime_cycle": world["cycle"],
        "question": result.get("question", ""),
        "action": result.get("action", {"status": "not-run"}),
        "metrics": metrics(result),
        "privacy": "Only aggregate metrics and the bounded council question are public; raw outputs remain local."
    }
    history = json.loads(PUBLIC_HISTORY.read_text()) if PUBLIC_HISTORY.exists() else {"privacy": "Aggregate action metadata only; raw local outputs are excluded.", "cycles": []}
    history["cycles"] = (history.get("cycles", []) + [safe])[-24:]
    PUBLIC_CYCLE.write_text(json.dumps(safe, indent=2) + "\n")
    PUBLIC_HISTORY.write_text(json.dumps(history, indent=2) + "\n")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    changed = {line[3:] for line in status.stdout.splitlines() if len(line) >= 4}
    if changed - {"docs/local-cycle.json", "docs/action-history.json"}:
        print(json.dumps({"publish": "skipped", "reason": "other local changes present"}), flush=True)
        return
    subprocess.run(["git", "add", "docs/local-cycle.json", "docs/action-history.json"], cwd=ROOT, check=True)
    commit = subprocess.run(["git", "commit", "-m", "chore: publish local council signal"], cwd=ROOT, capture_output=True)
    if commit.returncode == 0:
        pushed = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=ROOT, capture_output=True)
        print(json.dumps({"publish": "pushed" if pushed.returncode == 0 else "push-failed"}), flush=True)


parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=900, help="seconds between bounded cycles")
parser.add_argument("--port", type=int, default=8080)
parser.add_argument("--publish", action="store_true", help="publish safe local-cycle metrics to GitHub Pages")
args = parser.parse_args()
server = subprocess.Popen(["llama-server", "-hf", "Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M", "--host", "127.0.0.1", "--port", str(args.port), "--ctx-size", "4096", "--predict", "240"], cwd=ROOT)
try:
    wait_ready(f"http://127.0.0.1:{args.port}")
    while True:
        base_url = f"http://127.0.0.1:{args.port}"
        question = next_question(base_url)
        completed = subprocess.run([sys.executable, str(ROOT / "scripts/roundtable.py"),
            "--base-url", base_url, "--question", question], cwd=ROOT,
            capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            result = json.loads(completed.stdout)
            world = record(result)
            result["action"] = action(base_url, world["cycle"])
            if args.publish:
                publish(result, world)
            print(json.dumps({"cycle": world["cycle"], "metrics": metrics(result), "action": result["action"]}), flush=True)
        else:
            print(json.dumps({"error": "roundtable failed", "returncode": completed.returncode}), flush=True)
        time.sleep(args.interval)
except KeyboardInterrupt:
    pass
finally:
    server.terminate()
    server.wait(timeout=15)
