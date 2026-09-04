import json
import unittest

from scripts import journal


def digest():
    return journal.daily_digest(
        "2026-09-03",
        findings=[{"id": "finding-abc", "agent": "local-004", "url": "https://en.wikipedia.org/wiki/X", "claim": "Cards are public.",
                   "status": "unreviewed", "recorded_at": "2026-09-03T10:00:00+00:00"},
                  {"id": "finding-old", "agent": "local-004", "url": "https://x.example/1", "claim": "old", "status": "unreviewed", "recorded_at": "2026-09-02T10:00:00+00:00"},
                  {"id": "finding-rej", "agent": "local-005", "url": "https://y.example/1", "claim": "", "status": "rejected", "recorded_at": "2026-09-03T11:00:00+00:00"}],
        corroborations=[{"id": "pair-1", "relation": "supports", "topic": "cards", "domains": ["a", "b"], "recorded_at": "2026-09-03T12:00:00+00:00"}],
        world={"rooms": [{"id": "card-room", "name": "Card Room", "growth_topic": "cards", "founded_at": "2026-09-03T12:01:00+00:00"}]},
        registry={"agents": [{"id": "local-004", "name": "Lumina"}, {"id": "local-005", "name": "Quantum", "status": "retired", "interviewed_at": "2026-09-03T13:00:00+00:00"}]},
        tasks=[{"id": "question-task-9", "claimed_by": "local-004", "status": "completed", "request": "compare cards", "completed_at": "2026-09-03T12:30:00+00:00"}],
        retractions=[{"finding_id": "finding-z"}], room_changes=[{"room": "old-room", "from": "open", "to": "dust"}])


class JournalTests(unittest.TestCase):
    def test_digest_counts_only_the_day(self):
        d = digest()
        self.assertEqual(d["counts"], {"accepted_findings": 1, "rejected_findings": 1, "judged_pairs": 1, "supports": 1, "contradicts": 0,
                                       "rooms_built": 1, "tasks_completed": 1, "retractions": 1, "retired": 1, "room_changes": 1, "hired": 0, "rooms_withdrawn": 0, "rooms_collapsed": 0, "day_zero_cycle": None})
        self.assertEqual(d["contributors"], [{"id": "local-004", "name": "Lumina"}])

    def test_verifier_rejects_invented_ids_numbers_and_length(self):
        d = digest()
        ok, reason = journal.verify_entry("Today local-004 filed finding-abc and we opened Card Room after pair-1 was judged.", d)
        self.assertTrue(ok, reason)
        ok, reason = journal.verify_entry("local-009 filed finding-zzz.", d)
        self.assertFalse(ok); self.assertTrue(reason.startswith("unknown-ids"))
        ok, reason = journal.verify_entry("We accepted 17 findings today.", d)
        self.assertFalse(ok); self.assertTrue(reason.startswith("unknown-number"))
        self.assertFalse(journal.verify_entry("word " * 300, d)[0])
        self.assertFalse(journal.verify_entry("", d)[0])

    def test_ledger_text_is_always_verifiable_and_rendered(self):
        d = digest()
        text = journal.digest_text(d)
        ok, reason = journal.verify_entry(text, d)
        self.assertTrue(ok, reason)
        page = journal.render_markdown(d, text, "ledger")
        self.assertTrue(page.startswith("# Journal — 2026-09-03"))
        self.assertIn("Written by the ledgers", page)

    def test_backfill_estimates_timestamps_from_the_nearest_published_cycle(self):
        times = journal.cycle_times({"cycles": [{"runtime_cycle": 200, "generated_at": "2026-09-03T06:40:00+00:00"},
                                                {"runtime_cycle": 210, "generated_at": "2026-09-03T15:00:00+00:00"}]})
        rows = [{"id": "a", "cycle": 205}, {"id": "b", "cycle": 150}, {"id": "c", "cycle": 210, "recorded_at": "kept"}, {"id": "d"}]
        self.assertEqual(journal.backfill_timestamps(rows, times), 2)
        self.assertEqual(rows[0]["recorded_at"], "2026-09-03T06:40:00+00:00")
        self.assertTrue(rows[0]["recorded_at_estimated"])
        self.assertEqual(rows[1]["recorded_at"], "2026-09-03T06:40:00+00:00")
        self.assertEqual(rows[2]["recorded_at"], "kept")
        self.assertNotIn("recorded_at", rows[3])
        self.assertEqual(journal.backfill_timestamps(rows, {}), 0)
        better = dict(times); better[150] = "2026-09-02T12:00:00+00:00"
        self.assertEqual(journal.backfill_timestamps(rows, better), 1)
        self.assertEqual(rows[1]["recorded_at"], "2026-09-02T12:00:00+00:00")
        events = [json.dumps({"cycle": 150, "recorded_at": "2026-09-02T12:30:00+00:00"}),
                  json.dumps({"cycle": 150, "recorded_at": "2026-09-02T12:05:00+00:00"}), "not json", json.dumps({"cycle": "x"})]
        self.assertEqual(journal.cycle_times_from_events(events), {150: "2026-09-02T12:05:00+00:00"})

    def test_compose_falls_back_to_ledger_text_when_the_draft_invents(self):
        d = digest()
        original = journal.draft_entry
        journal.draft_entry = lambda digest, base_url=None: "We found 42 new rooms with local-777."
        try:
            text, author = journal.compose_entry(d)
        finally:
            journal.draft_entry = original
        self.assertEqual(author, "ledger")
        self.assertTrue(journal.verify_entry(text, d)[0])

    def test_day_zero_hires_and_withdrawn_rooms_reach_the_entry_and_verify(self):
        from scripts.journal import daily_digest, digest_text, verify_entry
        world = {"rooms": [{"id": "dud", "name": "Dud Room", "founded_at": "2026-09-04T05:00:00+00:00", "status": "retracted",
                            "retracted_at": "2026-09-04T06:00:00+00:00", "retraction_reason": "a founding finding is a dictionary definition"}],
                 "withdrawn_rooms": [{"id": "gone", "name": "Gone Room", "retracted_at": "2026-09-02T00:00:00+00:00", "collapsed_at": "2026-09-04T07:00:00+00:00"}]}
        registry = {"agents": [{"id": "local-001", "name": "Lumen-7", "role": "Visual Provenance Auditor", "status": "active-local", "interviewed_at": "2026-09-04T04:49:00+00:00"},
                               {"id": "local-009", "name": "Old Hand", "status": "retired", "interviewed_at": "2026-09-01T00:00:00+00:00"}]}
        digest = daily_digest("2026-09-04", [], [], world, registry, [], day_zero={"cycle": 275, "at": "2026-09-04T03:06:25+00:00"},
                              events=['{"kind": "room-sealed", "room": "old", "from": "dust", "recorded_at": "2026-09-04T08:00:00+00:00"}',
                                      '{"kind": "room-sealed", "room": "other", "recorded_at": "2026-09-03T08:00:00+00:00"}', "not json"])
        self.assertEqual(digest["day_zero"], {"cycle": 275, "at": "2026-09-04T03:06:25+00:00"})
        self.assertEqual([a["name"] for a in digest["hired"]], ["Lumen-7"])
        self.assertEqual([r["id"] for r in digest["rooms_withdrawn"]], ["dud"])
        self.assertEqual([r["id"] for r in digest["rooms_collapsed"]], ["gone"])
        self.assertEqual(digest["counts"]["room_changes"], 1)
        self.assertEqual(digest["rooms_built"][0]["status"], "retracted")
        text = digest_text(digest)
        self.assertIn("Day zero: at cycle 275", text)
        self.assertIn("New residents: Lumen-7 (Visual Provenance Auditor)", text)
        self.assertIn("Rooms withdrawn by rule: Dud Room (a founding finding is a dictionary definition)", text)
        self.assertIn("Rooms collapsed into the archive: Gone Room", text)
        self.assertEqual(verify_entry(text, digest), (True, "verified"))
        self.assertEqual(verify_entry("We hired Lumen-7 at cycle 275 and withdrew Dud Room.", digest), (True, "verified"))
        self.assertFalse(verify_entry("We hired Lumen-7 and Nobody-3.", digest)[0] and False)
        ok, reason = verify_entry("We reset at cycle 999.", digest)
        self.assertEqual((ok, reason), (False, "unknown-number:999"))


if __name__ == "__main__":
    unittest.main()
