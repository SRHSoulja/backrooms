"""Process-ownership helpers shared by the daemon and its supervisor.

Everything here is deliberately narrow: a process is only ever stopped through
the process group it created for itself, or through a pidfile that the daemon
lineage wrote for a model it launched. Nothing scans for or kills unrelated
processes.
"""

import os
import signal
import socket
import subprocess
import time
from pathlib import Path


def port_in_use(port, host="127.0.0.1"):
    """True when any listener already owns the port.

    The probe sets SO_REUSEADDR so leftover TIME_WAIT connections do not count,
    but a live listener still refuses the bind even if it used SO_REUSEPORT,
    which is exactly the duplicate-ownership case that must be refused.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, int(port)))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def process_alive(pid):
    """A zombie has already released its sockets and memory; treat it as gone."""
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
        state = stat.rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError, ValueError):
        return False
    return state != "Z"


def process_cmdline(pid):
    try:
        return Path(f"/proc/{int(pid)}/cmdline").read_bytes().replace(b"\0", b" ")
    except (OSError, ValueError):
        return b""


def stop_process_group(pid, wait=None, term_timeout=20, kill_timeout=5):
    """Send SIGTERM then SIGKILL to one process group we created ourselves."""
    for signal_number, timeout in ((signal.SIGTERM, term_timeout), (signal.SIGKILL, kill_timeout)):
        try:
            os.killpg(int(pid), signal_number)
        except ProcessLookupError:
            return True
        if wait is not None:
            try:
                wait(timeout=timeout)
                return True
            except subprocess.TimeoutExpired:
                continue
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not process_alive(pid):
                return True
            time.sleep(0.5)
    return not process_alive(pid)


def reap_recorded_model(pidfile, marker=b"llama-server"):
    """Stop the model process recorded in ``pidfile`` if it is still ours and alive.

    Returns the pid that was stopped, or None. The pidfile is removed either way
    so a stale record can never be reused.
    """
    pidfile = Path(pidfile)
    if not pidfile.exists():
        return None
    try:
        pid = int(pidfile.read_text().strip())
    except ValueError:
        pidfile.unlink(missing_ok=True)
        return None
    stopped = None
    if process_alive(pid) and marker in process_cmdline(pid):
        stop_process_group(pid)
        stopped = pid
    pidfile.unlink(missing_ok=True)
    return stopped


class ReloadWatcher:
    """Turn a source-tree change into a single reload request between cycles.

    ``observe`` returns one of: ``stable``, ``changing`` (a change is still
    settling), ``request`` (exactly once, when the tree has been stable for the
    debounce period), ``waiting`` (request sent, daemon still finishing its
    cycle), or ``force`` (the grace period ran out).
    """

    def __init__(self, signature, debounce=20, grace=2700):
        self.baseline = signature
        self.debounce = debounce
        self.grace = grace
        self.pending = None
        self.pending_since = None
        self.requested_at = None

    def observe(self, signature, now):
        if self.requested_at is not None:
            return "force" if now - self.requested_at > self.grace else "waiting"
        if signature == self.baseline:
            self.pending = None
            self.pending_since = None
            return "stable"
        if signature != self.pending:
            self.pending = signature
            self.pending_since = now
            return "changing"
        if now - self.pending_since >= self.debounce:
            self.requested_at = now
            return "request"
        return "changing"
