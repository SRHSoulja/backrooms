#!/usr/bin/env python3
"""Keep the bounded local daemon alive after recoverable model failures."""

import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
stopping = False


def stop(*_args):
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
backoff = 5
log_path = ROOT / "state/daemon.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
while not stopping:
    with log_path.open("a") as log_handle:
        process = subprocess.Popen([sys.executable, str(ROOT / "scripts/local_daemon.py"), "--interval", "900", "--publish"], cwd=ROOT, stdout=log_handle, stderr=subprocess.STDOUT)
    while process.poll() is None and not stopping:
        time.sleep(1)
    if stopping and process.poll() is None:
        process.terminate()
        process.wait(timeout=20)
        break
    if process.returncode == 0:
        backoff = 5
    else:
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)
