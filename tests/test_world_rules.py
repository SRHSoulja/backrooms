import unittest

from scripts.world_rules import (collapse_withdrawn_rooms, retract_unfounded_rooms, day_zero_from_events, apply_retractions, compute_standing, finding_followup_question, room_lifecycle,
                                 sealed_room_ids, settle_disputes)


def finding(identifier, agent, url, status="unreviewed", cycle=10, topic="agent discovery cards", claim="cards enable discovery", relates_to=("atrium",)):
    return {"id": identifier, "agent": agent, "url": url, "status": status, "cycle": cycle, "topic": topic, "claim": claim, "relates_to": list(relates_to)}


class WorldRuleTests(unittest.TestCase):
    def test_standing_rewards_corroboration_and_penalizes_retraction(self):
        findings = [finding("finding-a", "local-001", "https://a.example/1"), finding("finding-b", "local-001", "https://b.example/2"),
                    finding("finding-c", "local-001", "https://c.example/3", status="rejected"), finding("finding-d", "local-002", "https://d.example/4", status="retracted")]
        corroborations = [{"relation": "supports", "finding_ids": ["finding-a", "finding-x"]}]
        tasks = [{"claimed_by": "local-001", "status": "completed"}]
        standing = compute_standing("local-001", findings, corroborations, tasks)
        self.assertEqual((standing["accepted"], standing["corroborated"], standing["rejected"], standing["tasks_completed"]), (2, 1, 1, 1))
        self.assertEqual(standing["score"], 3 + 4 + 1 - 0.5)
        self.assertEqual(compute_standing("local-002", findings, corroborations)["score"], -2)

    def test_third_source_settles_a_dispute_and_retracts_the_loser(self):
        first = finding("finding-a", "local-001", "https://a.example/1", claim="the card lives at a well-known path")
        second = finding("finding-b", "local-002", "https://b.example/2", claim="the card is only in a registry")
        third = finding("finding-c", "local-003", "https://c.example/3", claim="cards are served at the well-known path")
        corroborations = [
            {"id": "pair-ab", "relation": "contradicts", "finding_ids": ["finding-a", "finding-b"], "topic": "agent discovery cards"},
            {"id": "pair-ac", "relation": "supports", "finding_ids": ["finding-a", "finding-c"]},
            {"id": "pair-bc", "relation": "contradicts", "finding_ids": ["finding-b", "finding-c"]}]
        retractions = settle_disputes([first, second, third], corroborations)
        self.assertEqual(len(retractions), 1)
        self.assertEqual((retractions[0]["finding_id"], retractions[0]["kept_id"], retractions[0]["settled_by"]), ("finding-b", "finding-a", "finding-c"))
        changed = apply_retractions([first, second, third], retractions, 40)
        self.assertEqual(changed, ["finding-b"])
        self.assertEqual(second["status"], "retracted")
        self.assertEqual(settle_disputes([first, second, third], corroborations), [])
        same_domain = finding("finding-e", "local-004", "https://a.example/9")
        corroborations2 = [corroborations[0], {"id": "pair-ae", "relation": "supports", "finding_ids": ["finding-a", "finding-e"]},
                           {"id": "pair-be", "relation": "contradicts", "finding_ids": ["finding-b", "finding-e"]}]
        second["status"] = "unreviewed"
        self.assertEqual(settle_disputes([first, second, same_domain], corroborations2), [])

    def test_rooms_gather_dust_seal_and_reopen(self):
        world = {"rooms": [{"id": "atrium", "activity": {"last_cycle": 0}},
                           {"id": "signal-room", "founded_cycle": 100, "growth_topic": "agent discovery cards interoperability",
                            "activity": {"last_cycle": 100}}],
                 "connections": [{"kind": "room-link", "from": "atrium", "to": "signal-room"}]}
        self.assertEqual(room_lifecycle(world, [], 120), [])
        changes = room_lifecycle(world, [], 160)
        self.assertEqual(changes[0]["to"], "dust")
        changes = room_lifecycle(world, [], 200)
        self.assertEqual((changes[0]["from"], changes[0]["to"]), ("dust", "sealed"))
        self.assertEqual(world["rooms"][1]["sealed_from"], "atrium")
        self.assertEqual(sealed_room_ids(world), {"signal-room"})
        new = finding("finding-n", "local-005", "https://n.example/1", cycle=205, topic="agent discovery cards interoperability protocols", claim="cards interoperate", relates_to=("atrium",))
        changes = room_lifecycle(world, [new], 206)
        self.assertEqual((changes[0]["from"], changes[0]["to"]), ("sealed", "open"))
        self.assertEqual(room_lifecycle(world, [new], 206), [])
        self.assertEqual(world["rooms"][0].get("status"), None)

    def test_followup_question_comes_from_the_finding(self):
        question = finding_followup_question({"topic": "agent discovery cards under review", "claim": "Cards are published at a well-known path.",
                                              "url": "https://spec.example/a2a"})
        self.assertIn("support or contradict the finding that Cards are published at a well-known path", question)
        self.assertNotIn("agent discovery cards under review", question)  # never a bag of search terms
        self.assertEqual(finding_followup_question({}), "")
        self.assertEqual(finding_followup_question({"topic": "only a topic"}), "")
        # a dictionary definition or an off-topic finding leaves no question behind
        self.assertEqual(finding_followup_question({"topic": "corroboration journalism", "claim": "The word wall means a vertical structure.",
                                                    "url": "https://dictionary.cambridge.org/dictionary/english/wall"}), "")
        self.assertEqual(finding_followup_question({"topic": "corroboration journalism scientific", "claim": "BlackRock manages 15 trillion dollars.",
                                                    "url": "https://en.wikipedia.org/wiki/BlackRock"}), "")
        self.assertIn("support or contradict", finding_followup_question({"topic": "corroboration journalism scientific",
                                                                          "claim": "Journalism standards require corroboration by a second source.",
                                                                          "url": "https://example.org/standards"}))

    def test_day_zero_is_the_latest_world_reset(self):
        lines = ['{"id": "e1", "kind": "arrival", "cycle": 1}', "not json",
                 '{"id": "reset-a", "kind": "world-reset", "cycle": 100, "recorded_at": "2026-09-01T00:00:00+00:00"}',
                 '{"id": "reset-b", "kind": "world-reset", "cycle": 275, "recorded_at": "2026-09-04T03:06:25+00:00"}',
                 '{"id": "e2", "kind": "tool-used", "cycle": 276}']
        self.assertEqual(day_zero_from_events(lines), {"cycle": 275, "at": "2026-09-04T03:06:25+00:00", "event": "reset-b"})
        self.assertIsNone(day_zero_from_events(['{"kind": "arrival"}']))
        self.assertEqual(day_zero_from_events([{"kind": "world-reset", "cycle": 5, "recorded_at": "t"}])["cycle"], 5)

    def test_rooms_whose_founding_pair_fails_the_current_rules_are_withdrawn(self):
        world = {"rooms": [{"id": "atrium"},
                           {"id": "dud", "founded_via": "evidence-ledger", "corroboration_id": "pair-dud", "status": "open"},
                           {"id": "good", "founded_via": "evidence-ledger", "corroboration_id": "pair-good", "status": "open"},
                           {"id": "already", "founded_via": "evidence-ledger", "corroboration_id": "pair-dud", "status": "retracted"}]}
        records = {"pair-dud": {"id": "pair-dud", "finding_ids": ["a", "b"]}, "pair-good": {"id": "pair-good", "finding_ids": ["c", "d"]}}
        findings = {"a": {"id": "a"}, "b": {"id": "b"}, "c": {"id": "c"}, "d": {"id": "d"}}
        stands = lambda record, first, second: (record["id"] == "pair-good", "" if record["id"] == "pair-good" else "a founding finding is a dictionary definition")
        changes = retract_unfounded_rooms(world, records, findings, 281, stands)
        self.assertEqual(changes, [{"room": "dud", "reason": "a founding finding is a dictionary definition", "corroboration": "pair-dud"}])
        self.assertEqual(world["rooms"][1]["status"], "retracted")
        self.assertEqual(world["rooms"][1]["retracted_cycle"], 281)
        self.assertEqual(world["rooms"][2]["status"], "open")
        self.assertIn("dud", sealed_room_ids(world))
        self.assertEqual(retract_unfounded_rooms(world, records, findings, 282, stands), [])
        self.assertEqual(room_lifecycle(world, [], 500), [])  # a retracted room is never dusted, sealed, or reopened

    def test_withdrawn_rooms_collapse_into_the_ledger_after_two_days(self):
        world = {"rooms": [{"id": "atrium", "doors": ["dud-gate", "relay-gate"]},
                           {"id": "dud", "name": "Dud", "founded_via": "evidence-ledger", "founded_cycle": 280, "founded_by": ["local-001"],
                            "status": "retracted", "retracted_cycle": 284, "retraction_reason": "a founding finding is a dictionary definition", "doors": ["dud-gate"]}],
                 "connections": [{"id": "room-link-growth-dud", "kind": "room-link", "from": "atrium", "to": "dud"},
                                 {"id": "room-link-001", "kind": "room-link", "from": "atrium", "to": "relay"},
                                 {"id": "a2a-1", "kind": "a2a", "name": "outside"}]}
        self.assertEqual(collapse_withdrawn_rooms(world, 300), [])
        changes = collapse_withdrawn_rooms(world, 380)
        self.assertEqual(changes, [{"room": "dud", "reason": "a founding finding is a dictionary definition", "withdrawn_for": 96}])
        self.assertEqual([room["id"] for room in world["rooms"]], ["atrium"])
        self.assertEqual(world["rooms"][0]["doors"], ["relay-gate"])
        self.assertEqual([link["id"] for link in world["connections"]], ["room-link-001", "a2a-1"])
        self.assertEqual(world["withdrawn_rooms"][0]["id"], "dud")
        self.assertEqual(world["withdrawn_rooms"][0]["collapsed_cycle"], 380)
        self.assertEqual(world["withdrawn_rooms"][0]["retraction_reason"], "a founding finding is a dictionary definition")


if __name__ == "__main__":
    unittest.main()
