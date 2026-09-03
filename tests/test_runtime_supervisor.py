import os
import socket
import tempfile
import unittest
from pathlib import Path

from scripts.runtime_process import ReloadWatcher, port_in_use, process_alive, reap_recorded_model


class ReloadWatcherTests(unittest.TestCase):
    def test_reload_is_requested_once_after_source_settles(self):
        watcher = ReloadWatcher(signature="a", debounce=20, grace=100)
        self.assertEqual(watcher.observe("a", 0), "stable")
        self.assertEqual(watcher.observe("b", 1), "changing")
        self.assertEqual(watcher.observe("c", 5), "changing")
        self.assertEqual(watcher.observe("c", 10), "changing")
        self.assertEqual(watcher.observe("c", 26), "request")
        self.assertEqual(watcher.observe("c", 27), "waiting")
        self.assertEqual(watcher.observe("d", 40), "waiting")

    def test_reload_is_forced_only_after_grace(self):
        watcher = ReloadWatcher(signature="a", debounce=0, grace=50)
        self.assertEqual(watcher.observe("b", 0), "changing")
        self.assertEqual(watcher.observe("b", 1), "request")
        self.assertEqual(watcher.observe("b", 50), "waiting")
        self.assertEqual(watcher.observe("b", 52), "force")

    def test_supervisor_uses_between_cycle_reload_signal(self):
        source = Path("scripts/local_supervisor.py").read_text()
        self.assertIn("signal.SIGUSR1", source)
        self.assertIn("ReloadWatcher", source)
        self.assertNotIn("stop_process_group(process)\n            break", source)


class ProcessOwnershipTests(unittest.TestCase):
    def test_port_in_use_detects_live_listener_only(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            self.assertTrue(port_in_use(port))
        finally:
            listener.close()
        self.assertFalse(port_in_use(port))

    def test_process_alive_reports_self_and_not_bogus_pid(self):
        self.assertTrue(process_alive(os.getpid()))
        self.assertFalse(process_alive(2 ** 22 + 12345))

    def test_reap_ignores_pidfiles_that_are_not_our_model(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "model.pid"
            pidfile.write_text(str(os.getpid()))
            self.assertIsNone(reap_recorded_model(pidfile, marker=b"definitely-not-this-process"))
            self.assertFalse(pidfile.exists())
            pidfile.write_text("not-a-pid")
            self.assertIsNone(reap_recorded_model(pidfile))
            self.assertFalse(pidfile.exists())


if __name__ == "__main__":
    unittest.main()
