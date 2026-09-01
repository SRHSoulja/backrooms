#!/usr/bin/env python3
"""Keep the local model loaded and run bounded resident cycles periodically."""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state/world.json"


def wait_ready(url):
    for _ in range(120):
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("local model did not become ready")


def record(result):
    with STATE.open() as handle:
        world = json.load(handle)
    number = len(world["events"]) + 1
    world["cycle"] += 1
    world["events"].append({
        "id": f"event-{number:03d}", "actor": "system", "kind": "local-daemon-cycle",
        "purpose": "bounded resident council", "text": "Local council completed. Echo and Morrow outputs were generated from public shared state; see local daemon logs for raw output.",
        "confidence": 0.5, "cycle": world["cycle"], "recorded_at": datetime.now(timezone.utc).isoformat()
    })
    with STATE.open("w") as handle:
        json.dump(world, handle, indent=2)
        handle.write("\n")
    print(json.dumps(result), flush=True)


parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=900, help="seconds between bounded cycles")
parser.add_argument("--port", type=int, default=8080)
args = parser.parse_args()
server = subprocess.Popen(["llama-server", "-hf", "Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M", "--host", "127.0.0.1", "--port", str(args.port), "--ctx-size", "4096", "--predict", "240"], cwd=ROOT)
try:
    wait_ready(f"http://127.0.0.1:{args.port}")
    while True:
        completed = subprocess.run([sys.executable, str(ROOT / "scripts/roundtable.py"), "--base-url", f"http://127.0.0.1:{args.port}"], cwd=ROOT, capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            record(json.loads(completed.stdout))
        else:
            print(json.dumps({"error": "roundtable failed", "returncode": completed.returncode}), flush=True)
        time.sleep(args.interval)
except KeyboardInterrupt:
    pass
finally:
    server.terminate()
    server.wait(timeout=15)
