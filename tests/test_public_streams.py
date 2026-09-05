import unittest
from datetime import date

from scripts import public_streams, research_lines

WIKITEXT = """{{Current events|year=2026|month=09|day=4|top=yes}}
<!-- All news items below this line -->
;Armed conflicts and attacks
**[[Gaza war]]
***[[Battle of Sufa#Aftermath|Aftermath of the Battle of Sufa]]
****The [[Israel Defense Forces]] state that a [[Nukhba forces|Nukhba Force]] commander was killed in an [[airstrike]] in [[Khan Yunis]], [[Gaza Strip]]. [https://www.timesofisrael.com/x (''The Times of Israel'')]
**[[2026 Tacloban school shooting]], [[2026 Ateneo de Zamboanga shooting]]
***Over 120 people are confirmed to have been killed since yesterday during clashes between the Houthis and the Yemeni Armed Forces. [https://www.france24.com/en/x (''AFP'' via ''France 24'')]
*Short one. [https://a.example (''A'')]
"""


class PublicStreamTests(unittest.TestCase):
    def test_only_cited_event_sentences_become_items(self):
        items = public_streams.items_from_wikitext(WIKITEXT, date(2026, 9, 4))
        texts = [item["text"] for item in items]
        self.assertEqual(len(items), 2, texts)
        self.assertTrue(texts[0].startswith("The Israel Defense Forces state that a Nukhba Force commander was killed"))
        self.assertEqual(items[0]["sources"], ["The Times of Israel"])
        self.assertIn("Over 120 people", texts[1])
        self.assertEqual(items[1]["day"], "2026-09-04")
        self.assertFalse(any("Tacloban" in text for text in texts))  # a topic header, no citation
        text, sources = public_streams.clean_wikitext("A [[b|c]] and [[d]] with '''bold'''<ref>x</ref> {{tmpl}}. [https://z.example/q (''Z News'')]")
        self.assertEqual((text, sources), ("A c and d with bold", ["Z News"]))

    def test_roots_rotate_by_cycle_and_carry_the_first_source(self):
        items = public_streams.items_from_wikitext(WIKITEXT, date(2026, 9, 4))
        first = public_streams.stream_questions(items, 10, limit=2)
        second = public_streams.stream_questions(items, 11, limit=2)
        self.assertEqual(len(first), 2)
        self.assertNotEqual(first[0][0], second[0][0])
        self.assertTrue(first[0][0].startswith("Do independent public sources confirm that "))
        self.assertIn("first reported by The Times of Israel", first[0][0])
        self.assertEqual(first[0][1], "stream:wikipedia-current-events/2026-09-04")
        self.assertEqual(public_streams.day_page(date(2026, 9, 4)), "Portal:Current_events/2026_September_4")

    def test_a_stream_root_opens_a_line_after_the_queue_and_before_hiring_questions(self):
        state = research_lines.empty_state()
        streams = [("Do independent public sources confirm that Over 120 people were killed in clashes between the Houthis and the Yemeni Armed Forces (first reported by AFP)?",
                    "stream:wikipedia-current-events/2026-09-04")]
        decision = research_lines.decide(state, 340, [], lambda line: "", [("local-001", "Does EXIF metadata reference documented subjects?")], "fallback",
                                         stream_questions=streams)
        self.assertEqual((decision["source"], decision["opened"]), ("stream:wikipedia-current-events/2026-09-04", True))
        self.assertIn("houthis", research_lines.open_line(state)["anchors"])
        research_lines.note_outcome(state, 340, 1)
        again = research_lines.decide(state, 341, [], lambda line: "", [], "fallback", stream_questions=streams)
        self.assertEqual(again["line_id"], decision["line_id"])


if __name__ == "__main__":
    unittest.main()
