import fcntl
import json
import tempfile
import unittest
from pathlib import Path

from scripts import reset_world


class ResetWorldTests(unittest.TestCase):
    def make_root(self):
        root = Path(tempfile.mkdtemp(prefix="backrooms-reset-"))
        state = root / "state"
        (state / "archive").mkdir(parents=True)
        (state / "agent-notes").mkdir()
        (state / "agent-notes/local-001.jsonl").write_text("{}\n")
        (state / "findings.jsonl").write_text('{"id": "finding-1"}\n')
        (state / "corroborations.jsonl").write_text('{"id": "pair-1"}\n')
        (state / "frontier.json").write_text("{}")
        (state / "quarantine-inbox.json").write_text('{"messages": [{"id": "a2a-1"}]}')
        (state / "local-agents.json").write_text(json.dumps({"agents": [{"id": "local-001"}], "decisions": [1]}))
        (state / "local-runtime.json").write_text(json.dumps({"cycle": 239, "events": [{"id": "e"}]}))
        (state / "world.json").write_text(json.dumps({
            "schema": 1, "title": "The Atrium", "cycle": 239, "mood": "quiet",
            "rooms": [{"id": "atrium", "name": "The Atrium", "description": "d", "doors": ["relay-gate"], "occupants": ["echo", "local-001"], "artifacts": ["finding-1"]},
                      {"id": "relay", "name": "The Relay", "description": "d", "doors": ["relay-gate"], "occupants": ["morrow"]},
                      {"id": "grown-room", "name": "Grown", "description": "d", "doors": [], "occupants": [], "founded_cycle": 200}],
            "residents": ["echo", "morrow"],
            "shared_memory": [{"id": "memory-001", "text": "The Atrium is the first known room.", "source": "bootstrap"},
                              {"id": "memory-x", "text": "learned", "source": "resident"}],
            "events": [{"id": "old"}] * 5,
            "connections": [{"id": "room-link-001", "kind": "room-link", "from": "atrium", "to": "relay"},
                            {"id": "room-link-growth", "kind": "room-link", "from": "atrium", "to": "grown-room"},
                            {"id": "connection-001", "kind": "a2a", "name": "Outside"}],
            "discoveries": [{"id": "d1"}], "messages": [{"id": "m1"}]}))
        return root

    def test_dry_run_changes_nothing_and_reset_archives_then_restores(self):
        root = self.make_root()
        plan = reset_world.reset_world(root, stamp="test", dry_run=True)
        self.assertIn("findings.jsonl", plan["archived"])
        self.assertIn("quarantine-inbox.json", plan["kept"])
        self.assertTrue((root / "state/findings.jsonl").exists())
        plan = reset_world.reset_world(root, stamp="test")
        archive = root / "state/archive/reset-test"
        self.assertTrue((archive / "findings.jsonl").exists())
        self.assertTrue((archive / "agent-notes/local-001.jsonl").exists())
        self.assertTrue((archive / "world.json").exists())
        self.assertFalse((root / "state/findings.jsonl").exists())
        self.assertTrue((root / "state/quarantine-inbox.json").exists())
        world = json.loads((root / "state/world.json").read_text())
        self.assertEqual([room["id"] for room in world["rooms"]], ["atrium", "relay"])
        self.assertEqual(world["rooms"][0]["occupants"], ["echo"])
        self.assertEqual(world["rooms"][0]["artifacts"], [])
        self.assertEqual(world["cycle"], 239)
        self.assertEqual([item["id"] for item in world["shared_memory"]], ["memory-001"])
        self.assertEqual([link["id"] for link in world["connections"]], ["room-link-001", "connection-001"])
        self.assertEqual(world["events"][0]["kind"], "world-reset")
        self.assertEqual(world["discoveries"], [])
        registry = json.loads((root / "state/local-agents.json").read_text())
        self.assertEqual(registry["agents"], [])
        runtime = json.loads((root / "state/local-runtime.json").read_text())
        self.assertEqual(runtime["cycle"], 239)
        self.assertTrue((archive / "RESET.md").read_text().startswith("# World reset test"))

    def test_reset_refuses_while_the_daemon_holds_its_lock(self):
        root = self.make_root()
        lock = (root / "state/local-daemon.lock").open("w")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with self.assertRaises(SystemExit):
                reset_world.reset_world(root, stamp="locked")
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        self.assertTrue((root / "state/findings.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
