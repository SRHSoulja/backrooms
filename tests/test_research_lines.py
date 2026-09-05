import unittest

from scripts.research_lines import (COOLDOWN_CYCLES, EMPTY_CYCLES_CAP, HOP_CAP, anchor_terms, decide, generic_terms, in_cooldown,
                                    line_query, note_outcome, open_line, public_view, shares_anchor, empty_state)

FALLBACK = "Which claim in the open record is least supported by an independent public source, and which source could settle it?"


class AnchorTests(unittest.TestCase):
    def test_anchors_are_the_rare_terms_not_the_research_vocabulary(self):
        self.assertEqual(anchor_terms("Which GitHub repositories does Roskomnadzor's official organization publish, according to public sources?"),
                         ["roskomnadzor"])
        self.assertEqual(anchor_terms("Does the **AutoHVSR algorithm's** mean resonant frequency RMSE of 0.05 Hz hold across noisy HVSR datasets?")[:3],
                         ["rmse", "hvsr", "autohvsr"])
        self.assertIn("wsj", anchor_terms("What do WSJ's documented editorial workflows show about submission-to-publication intervals?"))
        # a question with no proper noun still gets a few long content words, never generic ones
        common = anchor_terms("How do published open-source agent systems implement persistent memory across restarts?")
        self.assertTrue(common and all(term not in {"github", "agent", "systems", "published"} for term in common))
        self.assertEqual(anchor_terms("Which sources support the claim?"), [])

    def test_anchor_matching_is_by_stem_and_generic_words_do_not_count(self):
        anchors = anchor_terms("Does the GitHub profile Roscomnadzor27 have any publicly documented affiliation with Roskomnadzor's official channels?")
        self.assertEqual(anchors, ["roscomnadzor27", "roskomnadzor"])
        self.assertTrue(shares_anchor("Roskomnadzor's takedown notices were posted in a GitHub repository.", anchors))
        self.assertFalse(shares_anchor("The GitHub profile for 'roscom' (Ross Cameron) is associated with Roscommon Pty Ltd.", anchors))
        self.assertFalse(shares_anchor("Contributions on GitHub are only counted if they meet specific criteria.", anchors))
        self.assertFalse(shares_anchor("anything", []))

    def test_generic_terms_come_from_the_ledger_once_it_is_big_enough(self):
        claims = ["GitHub blocks %d things" % n for n in range(25)]
        self.assertIn("github", generic_terms(claims))
        self.assertNotIn("blocks", generic_terms(claims + ["other"] * 200))
        self.assertEqual(generic_terms(claims[:5]), set())


class LineTests(unittest.TestCase):
    def test_a_resident_question_opens_a_line_and_steps_stay_on_it_while_new_subjects_queue(self):
        state = empty_state()
        first = decide(state, 300, [("Which GitHub repositories does Roskomnadzor's official organization publish?", "resident:echo")],
                       lambda line: "", [], FALLBACK)
        self.assertTrue(first["opened"])
        line = open_line(state)
        self.assertEqual((line["anchors"], line["origin"], first["source"]), (["roskomnadzor"], "queued:resident:echo", "resident:echo"))
        self.assertEqual(first["research_topic"].split()[0], "roskomnadzor")
        # a step shares an anchor; a different subject waits in the queue
        second = decide(state, 301, [("Does the GitHub profile Roscomnadzor27 belong to Roskomnadzor?", "resident:morrow"),
                                     ("What does the AutoHVSR paper report as its RMSE?", "resident:echo")], lambda line: "", [], FALLBACK)
        self.assertEqual((second["line_id"], second["source"], len(line["hops"])), (line["id"], "resident:morrow", 2))
        self.assertEqual([item["source"] for item in state["queue"]], ["resident:echo"])
        # no step and no follow-up: the line's last question is carried, not a new subject
        third = decide(state, 302, [("Something about BlackRock's assets?", "resident:echo")], lambda line: "", [], FALLBACK)
        self.assertEqual((third["question"], third["source"]), (second["question"], "carried:" + line["id"]))
        self.assertEqual(len(state["queue"]), 2)
        # a finding follow-up on the line is the third and last hop; after that the line only carries
        fourth = decide(state, 303, [], lambda line: "Do other sources support the finding that Roskomnadzor posted takedown notices?", [], FALLBACK)
        self.assertEqual((fourth["source"], len(line["hops"])), ("finding-followup", HOP_CAP))
        fifth = decide(state, 304, [("Did Roskomnadzor block GitHub in 2014?", "resident:morrow")], lambda line: "", [], FALLBACK)
        self.assertEqual((fifth["question"], len(line["hops"]), line.get("cap_reached_cycle")), (fourth["question"], HOP_CAP, 304))

    def test_outcomes_close_a_line_and_the_queue_opens_the_next_with_a_cooldown(self):
        state = empty_state()
        decide(state, 300, [("Which GitHub repositories does Roskomnadzor's official organization publish?", "resident:echo"),
                            ("What does the AutoHVSR paper report as its RMSE?", "resident:morrow")], lambda line: "", [], FALLBACK)
        line = open_line(state)
        self.assertEqual(note_outcome(state, 300, 2), [])
        self.assertEqual((line["findings"], line["empty_cycles"]), (2, 0))
        for cycle in range(301, 301 + EMPTY_CYCLES_CAP - 1):
            self.assertEqual(note_outcome(state, cycle, 0), [])
        closed = note_outcome(state, 301 + EMPTY_CYCLES_CAP - 1, 0)
        self.assertEqual(closed[0]["reason"], f"no new accepted finding in {EMPTY_CYCLES_CAP} cycles")
        self.assertEqual(line["status"], "closed")
        self.assertTrue(in_cooldown(["roskomnadzor"], state, line["closed_cycle"] + 1))
        self.assertFalse(in_cooldown(["roskomnadzor"], state, line["closed_cycle"] + COOLDOWN_CYCLES))
        # the queued subject opens next; a proposal on the closed subject is refused by the cooldown
        cycle = line["closed_cycle"] + 1
        nxt = decide(state, cycle, [("Did Roskomnadzor block GitHub in 2014?", "resident:echo")], lambda line: "", [], FALLBACK)
        self.assertTrue(nxt["opened"])
        self.assertEqual(open_line(state)["anchors"][:2], ["rmse", "autohvsr"])
        self.assertEqual(state["queue"], [])
        # a room founded on the line wins and closes it
        won = note_outcome(state, cycle, 1, ["the-autohvsr-room"])
        self.assertEqual((won[0]["reason"], won[0]["rooms"]), ("room founded on the line", ["the-autohvsr-room"]))

    def test_hiring_questions_and_the_fallback_open_lines_when_nothing_is_queued(self):
        state = empty_state()
        hires = [("local-004", "Does the GitHub profile Roscomnadzor27 show activity?"),  # would be refused by the council rules upstream
                 ("local-006", "Do peer-reviewed papers validate the under-correction claim about ARIMA forecasts of Brent crude?")]
        first = decide(state, 310, [], lambda line: "", hires, FALLBACK)
        self.assertEqual((first["source"], first["opened"]), ("hire:local-004", True))
        line = open_line(state)
        self.assertEqual(note_outcome(state, 310, 0, ["room-x"])[0]["reason"], "room founded on the line")
        second = decide(state, 311, [], lambda line: "", hires, FALLBACK)
        self.assertEqual(second["source"], "hire:local-006")
        self.assertEqual(state["used_hire_questions"], ["local-004", "local-006"])
        for cycle in range(311, 311 + EMPTY_CYCLES_CAP):
            note_outcome(state, cycle, 0)
        third = decide(state, 320, [], lambda line: "", hires, FALLBACK)
        self.assertEqual((third["source"], third["anchors"], third["research_topic"]), ("fixed-fallback", [], ""))
        # the fallback line gives way as soon as a resident brings a subject
        fourth = decide(state, 321, [("How does OpenAlex count citations for retracted papers?", "resident:echo")], lambda line: "", [], FALLBACK)
        self.assertEqual((fourth["opened"], fourth["closed"][0]["reason"]), (True, "superseded by a resident question"))
        view = public_view(state)
        self.assertEqual(view["open"], open_line(state)["id"])
        self.assertEqual(view["hop_cap"], HOP_CAP)
        self.assertEqual(line_query(open_line(state)).split()[0], "openalex")


if __name__ == "__main__":
    unittest.main()
