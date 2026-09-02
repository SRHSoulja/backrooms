import copy
import tempfile
import unittest
from pathlib import Path

from scripts import local_autonomy


class LocalAutonomyTests(unittest.TestCase):
    def setUp(self):
        self.archive_dir = tempfile.TemporaryDirectory()
        self.original_archive = local_autonomy.ARCHIVE
        local_autonomy.ARCHIVE = Path(self.archive_dir.name) / "events.jsonl"

    def tearDown(self):
        local_autonomy.ARCHIVE = self.original_archive
        self.archive_dir.cleanup()

    def test_build_creates_one_connected_room_and_event(self):
        world = {"events": [], "rooms": [
            {"id": "relay", "name": "The Relay", "doors": [], "occupants": []}],
            "connections": []}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "relay",
                                 "room_proposal": {"kind": "build", "name": "Signal Garden",
                                                   "description": "A bounded test room.",
                                                   "source_room": "relay", "status": "construction-requested"}}]}

        changes = local_autonomy.apply_construction(world, registry, 70)

        self.assertEqual(changes[0]["room"], "signal-garden")
        self.assertEqual(world["connections"][0]["to"], "signal-garden")
        self.assertEqual(registry["agents"][0]["room_proposal"]["status"], "constructed")
        self.assertEqual(world["events"][0]["kind"], "room-built")
        self.assertTrue(local_autonomy.ARCHIVE.exists())

    def test_duplicate_build_proposal_is_idempotent(self):
        world = {"events": [], "rooms": [{"id": "relay", "doors": [], "occupants": []}], "connections": []}
        proposal = {"kind": "build", "name": "Signal Garden", "source_room": "relay",
                    "status": "construction-requested"}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "relay",
                                 "room_proposal": copy.deepcopy(proposal)}]}

        local_autonomy.apply_construction(world, registry, 71)
        local_autonomy.apply_construction(world, registry, 71)

        self.assertEqual(len(world["rooms"]), 2)
        self.assertEqual(len(world["connections"]), 1)

    def test_safe_request_creates_typed_artifact(self):
        world = {"rooms": [{"id": "atrium"}]}
        registry = {"agents": [{"id": "local-test", "status": "active-local", "room": "atrium",
                                 "request": "access to an Atrium map", "request_status": "open",
                                 "capabilities": []}]}
        resolutions = local_autonomy.resolve_requests(registry, world=world)
        self.assertEqual(resolutions[0]["status"], "fulfilled")
        self.assertEqual(registry["agents"][0]["request_artifact"]["kind"], "room-map")
        self.assertTrue(registry["agents"][0]["request_artifact"]["accepted"])

    def test_revoke_removes_capability_and_downgrades_agent(self):
        agent = {"status": "active-local", "capabilities": ["public-web-read", "bounded-questioning"]}
        local_autonomy.revoke(agent, "public-web-read", "test rejection")
        self.assertEqual(agent["status"], "probation")
        self.assertEqual(agent["capabilities"], ["bounded-questioning"])
        self.assertEqual(agent["safety_incidents"], 1)


if __name__ == "__main__":
    unittest.main()
