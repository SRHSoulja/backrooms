import os
import socket
import tempfile
import unittest
from pathlib import Path

from scripts.runtime_process import startup_delay, ReloadWatcher, port_has_listener, port_in_use, process_alive, reap_recorded_model


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

    def test_supervisor_requests_reloads_with_sigusr1(self):
        from scripts import local_supervisor
        self.assertEqual(local_supervisor.RELOAD_DEBOUNCE_SECONDS, 20)
        self.assertTrue(hasattr(local_supervisor, "ReloadWatcher"))
        self.assertIn("signal.SIGUSR1", Path("scripts/local_supervisor.py").read_text())

    def test_supervisor_stops_its_daemon_on_hangup_from_tmux(self):
        source = Path("scripts/local_supervisor.py").read_text()
        for name in ("signal.SIGTERM", "signal.SIGINT", "signal.SIGHUP"):
            self.assertIn(f"signal.signal({name}, stop)", source)


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

    def test_lingering_connections_without_a_listener_do_not_count_as_ownership(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        port = listener.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port))
        accepted, _address = listener.accept()
        listener.close()
        try:
            # The accepted connection is still open and a second one sits in
            # TIME_WAIT on the server side, exactly the state left behind by a
            # model process that just exited. Nobody is listening any more.
            self.assertFalse(port_in_use(port))
        finally:
            accepted.close()
            client.close()

    def test_listener_detection_parses_kernel_table_format(self):
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / "tcp"
            table.write_text("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
                             "   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 1 0\n"
                             "   1: 0100007F:1F91 0100007F:C350 06 00000000:00000000 00:00000000 00000000  1000        0 1 0\n")
            self.assertTrue(port_has_listener(8080, proc_tables=(str(table),)))
            self.assertFalse(port_has_listener(8081, proc_tables=(str(table),)))

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


    def test_restarted_daemon_idles_out_the_rest_of_the_cadence(self):
        self.assertEqual(startup_delay(1000.0, 600, 1100.0), 500.0)
        self.assertEqual(startup_delay(1000.0, 600, 1700.0), 0.0)
        self.assertEqual(startup_delay(None, 600, 1100.0), 0.0)
        self.assertEqual(startup_delay("bad", 600, 1100.0), 0.0)
        self.assertEqual(startup_delay(2000.0, 600, 1100.0), 0.0)


if __name__ == "__main__":
    unittest.main()
