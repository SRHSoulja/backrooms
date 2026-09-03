import fcntl
import hashlib
import inspect
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

    def test_reset_never_touches_the_wallet_public_feeds_journal_or_kept_ledgers(self):
        root = self.make_root()
        state = root / "state"
        precious = {
            "wallet/receiving.json": '{"address": "public-receiving-address"}',
            "wallet/treasury-policy.json": '{"enabled": false}',
            "docs/treasury.json": '{"status": "online"}',
            "docs/findings.json": '{"findings": [1]}',
            "journal/2026-09-02.md": "# 2026-09-02\n",
            ".env.example": "MISTRAL_API_KEY=\n",
            "state/treasury-intents.json": '{"intents": [{"id": "intent-1"}]}',
            "state/archive/events.jsonl": '{"id": "event-1"}\n',
            "state/quarantine-inbox.json": '{"messages": [{"id": "a2a-1"}]}',
            "state/codex-outbox/review-1.json": '{"lead": "x"}',
            "state/codex-consumed.json": '{"consumed": ["review-0"]}',
            "state/daemon.log": "cycle 239 published\n",
        }
        for name, text in precious.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        digest = lambda name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        before = {name: digest(name) for name in precious}
        plan = reset_world.reset_world(root, stamp="keep")
        self.assertEqual({name: digest(name) for name in precious}, before)
        self.assertTrue(any("wallet" in item for item in plan["untouched"]))
        self.assertTrue(any(".config/backrooms" in item for item in plan["untouched"]))
        self.assertIn("Never touched", (state / "archive/reset-keep/RESET.md").read_text())
        # The reset must stay confined to state/: no home-directory or vault access in its source.
        source = inspect.getsource(reset_world)
        self.assertNotIn("Path.home", source)
        self.assertNotIn("expanduser", source)
        self.assertNotIn("~/.config", source.replace("~/.config/backrooms/ (the vault", ""))
        # Founding-room charters and doors survive; only occupants and artifacts are cleared.
        world = json.loads((state / "world.json").read_text())
        self.assertEqual(world["rooms"][0]["doors"], ["relay-gate"])

    def test_keep_research_leaves_findings_and_corroborations_live_with_safety_copies(self):
        root = self.make_root()
        state = root / "state"
        before = {name: hashlib.sha256((state / name).read_bytes()).hexdigest() for name in ("findings.jsonl", "corroborations.jsonl")}
        plan = reset_world.reset_world(root, stamp="research", keep_research=True)
        self.assertNotIn("findings.jsonl", plan["archived"])
        self.assertIn("findings.jsonl", plan["kept"])
        self.assertIn("corroborations.jsonl", plan["kept"])
        self.assertEqual({name: hashlib.sha256((state / name).read_bytes()).hexdigest() for name in before}, before)
        archive = state / "archive/reset-research"
        self.assertTrue((archive / "findings.jsonl").exists())
        self.assertTrue((archive / "corroborations.jsonl").exists())
        self.assertFalse((state / "frontier.json").exists())
        self.assertIn("Original research kept live", (archive / "RESET.md").read_text())
        world = json.loads((state / "world.json").read_text())
        self.assertEqual([room["id"] for room in world["rooms"]], ["atrium", "relay"])
        self.assertEqual(json.loads((state / "local-agents.json").read_text())["agents"], [])


if __name__ == "__main__":
    unittest.main()
