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


LISTEN_STATE = "0A"


def port_has_listener(port, proc_tables=("/proc/net/tcp", "/proc/net/tcp6")):
    """True when a LISTEN socket owns the port, read from the kernel's TCP tables.

    A bind probe is the wrong test here: right after a model process dies its
    accepted connections linger in FIN_WAIT/TIME_WAIT for a while, and a plain
    bind can fail on those even though no one is listening. Only a socket in
    LISTEN state means another server owns the port.
    """
    wanted = f":{int(port):04X}"
    found_table = False
    for table in proc_tables:
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        found_table = True
        for line in lines:
            fields = line.split()
            if len(fields) > 3 and fields[1].upper().endswith(wanted) and fields[3].upper() == LISTEN_STATE:
                return True
    if found_table:
        return False
    return _bind_probe_in_use(port)


def _bind_probe_in_use(port, host="127.0.0.1"):
    """Fallback for hosts without /proc: a bind that fails means the port is taken."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, int(port)))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def port_in_use(port, host="127.0.0.1"):
    """True when another listener already owns the port (see port_has_listener)."""
    return port_has_listener(port)


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


def startup_delay(last_completed_at, interval, now):
    """Seconds a restarted daemon should idle before its first cycle so a reload
    or crash-restart does not double up on the cadence. Unknown or stale
    completion times mean no delay."""
    try:
        last = float(last_completed_at)
        interval = float(interval)
    except (TypeError, ValueError):
        return 0.0
    if interval <= 0 or last <= 0 or now < last:
        return 0.0
    return max(0.0, interval - (now - last))


def rotate_log(path, limit_bytes=20_000_000):
    """Keep an append-only log from growing without bound: once it passes the
    limit, move it aside as ``<name>.1`` (replacing the previous one) so the
    runtime can run for months unattended. Returns True when rotated."""
    path = Path(path)
    try:
        if not path.exists() or path.stat().st_size < limit_bytes:
            return False
        previous = path.with_name(path.name + ".1")
        if previous.exists():
            previous.unlink()
        path.rename(previous)
        return True
    except OSError:
        return False


def hosted_elsewhere(marker_path, host, takeover=False):
    """True when the state directory says another host runs the world.

    The running host writes its name to ``state/RUNTIME_HOST`` every cycle;
    a daemon on a different host refuses to start so two brains never run on
    one state. ``takeover`` (BACKROOMS_TAKEOVER=1) overrides deliberately."""
    if takeover:
        return False
    try:
        marker = Path(marker_path).read_text().strip()
    except OSError:
        return False
    return bool(marker) and marker != str(host)
