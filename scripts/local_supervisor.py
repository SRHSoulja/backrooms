#!/usr/bin/env python3
"""Keep the bounded local daemon alive after recoverable model failures."""

import signal
import subprocess
import sys
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
stopping = False


def source_signature():
    """Return a cheap signature for runtime code loaded by the daemon."""
    return tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size)
                 for path in sorted((ROOT / "scripts").glob("*.py")))


def stop(*_args):
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def stop_process_group(process):
    """Stop the daemon and its model child together during reload/shutdown."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


backoff = 5
log_path = ROOT / "state/daemon.log"
log_path.parent.mkdir(parents=True, exist_ok=True)
while not stopping:
    signature = source_signature()
    changed = False
    with log_path.open("a") as log_handle:
        process = subprocess.Popen([sys.executable, str(ROOT / "scripts/local_daemon.py"), "--interval", "900", "--publish"], cwd=ROOT, stdout=log_handle, stderr=subprocess.STDOUT, start_new_session=True)
    while process.poll() is None and not stopping:
        time.sleep(1)
        if source_signature() != signature:
            changed = True
            stop_process_group(process)
            with log_path.open("a") as log_handle:
                log_handle.write('{"supervisor": "runtime code changed; daemon restarting"}\n')
            break
    if stopping and process.poll() is None:
        stop_process_group(process)
        break
    if changed or process.returncode == 0:
        backoff = 5
    else:
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)
