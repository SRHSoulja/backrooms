#!/usr/bin/env python3
"""Keep the bounded local daemon alive and reload it only between cycles.

A source change no longer kills the daemon mid-cycle. The supervisor waits for
the tree to settle, asks the daemon (SIGUSR1) to exit after the cycle it is
running, and only forces a stop if that takes longer than the grace period.
Shutdown and forced stops address the daemon's own process group; the model is
stopped by the daemon itself, with the recorded pidfile as the only backstop.
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.runtime_process import ReloadWatcher, reap_recorded_model, stop_process_group, rotate_log
except ImportError:
    from runtime_process import ReloadWatcher, reap_recorded_model, stop_process_group, rotate_log

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "state/daemon.log"
MODEL_PID = ROOT / "state/llama-server.pid"
RELOAD_DEBOUNCE_SECONDS = 20
RELOAD_GRACE_SECONDS = 2700
stopping = False


def source_signature():
    """Return a cheap signature for runtime code loaded by the daemon."""
    return tuple((path.name, path.stat().st_mtime_ns, path.stat().st_size)
                 for path in sorted((ROOT / "scripts").glob("*.py")))


def stop(*_args):
    global stopping
    stopping = True


def log(message, **fields):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as handle:
        handle.write(json.dumps({"supervisor": message, "at": datetime.now(timezone.utc).isoformat(), **fields}) + "\n")


def run_daemon():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if rotate_log(LOG_PATH):
        log("daemon log rotated", kept=LOG_PATH.name + ".1")
    with LOG_PATH.open("a") as log_handle:
        return subprocess.Popen([sys.executable, str(ROOT / "scripts/local_daemon.py"), "--interval", str(os.getenv("BACKROOMS_CYCLE_SECONDS", "1800")), "--publish"],
                                cwd=ROOT, stdout=log_handle, stderr=subprocess.STDOUT, start_new_session=True)


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGHUP, stop)  # tmux kill-session sends SIGHUP; stop the daemon and model with us
    backoff = 5
    while not stopping:
        process = run_daemon()
        watcher = ReloadWatcher(source_signature(), RELOAD_DEBOUNCE_SECONDS, RELOAD_GRACE_SECONDS)
        reload_requested = False
        forced = False
        while process.poll() is None and not stopping:
            time.sleep(1)
            verdict = watcher.observe(source_signature(), time.time())
            if verdict == "request":
                os.kill(process.pid, signal.SIGUSR1)
                reload_requested = True
                log("runtime code changed; reload requested after the current cycle", pid=process.pid)
            elif verdict == "force" and not forced:
                forced = True
                log("daemon did not finish its cycle within the reload grace period; stopping its process group", pid=process.pid)
                stop_process_group(process.pid, wait=process.wait)
        if stopping and process.poll() is None:
            log("supervisor stopping; terminating daemon process group", pid=process.pid)
            stop_process_group(process.pid, wait=process.wait)
        reaped = reap_recorded_model(MODEL_PID)
        if reaped:
            log("stopped recorded model process the daemon left behind", pid=reaped)
        if stopping:
            break
        if reload_requested or process.returncode == 0:
            backoff = 5
            log("daemon exited; restarting", returncode=process.returncode, reload=reload_requested)
        else:
            log("daemon failed; backing off before restart", returncode=process.returncode, backoff=backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    main()
