import json
import tempfile
import unittest
from pathlib import Path

from scripts.codex_reviews import consume_outbox, extract_review_text, question_id_from_task, review_lead


class CodexReviewTests(unittest.TestCase):
    def test_final_assistant_message_is_extracted_from_known_stream_shapes(self):
        stream = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "t"}),
            json.dumps({"type": "item.completed", "item": {"type": "reasoning", "text": "thinking"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Draft answer."}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Final: two   sources agree."}}),
        ])
        self.assertEqual(extract_review_text(stream), "Final: two sources agree.")
        legacy = json.dumps({"id": "1", "msg": {"type": "agent_message", "message": "Legacy shape answer."}})
        self.assertEqual(extract_review_text(legacy), "Legacy shape answer.")
        openai_style = json.dumps({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Content list answer."}]})
        self.assertEqual(extract_review_text(openai_style), "Content list answer.")
        self.assertEqual(extract_review_text("plain line one\nplain line two"), "plain line one plain line two")
        self.assertEqual(extract_review_text(""), "")
        self.assertEqual(len(extract_review_text("x" * 5000, limit=100)), 100)

    def test_lead_identity_and_question_link(self):
        self.assertEqual(question_id_from_task("frontier-frontier-question-188-retry-2"), "frontier-question-188")
        lead = review_lead({"task_id": "frontier-frontier-question-188", "completed_at": "t"}, "text", 190)
        self.assertEqual((lead["id"], lead["question_id"], lead["status"]), ("lead-codex-frontier-frontier-question-188", "frontier-question-188", "unverified"))

    def test_outbox_is_consumed_once_and_withheld_text_yields_no_lead(self):
        with tempfile.TemporaryDirectory() as directory:
            outbox = Path(directory) / "outbox"
            outbox.mkdir()
            (outbox / "frontier-frontier-question-1.json").write_text(json.dumps({
                "task_id": "frontier-frontier-question-1", "status": "completed",
                "output": json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Compare the two specs."}})}))
            (outbox / "frontier-frontier-question-2.json").write_text(json.dumps({
                "task_id": "frontier-frontier-question-2", "status": "failed", "output": ""}))
            (outbox / "frontier-frontier-question-3.json").write_text(json.dumps({
                "task_id": "frontier-frontier-question-3", "status": "completed",
                "output": json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "api_key=abc123secret"}})}))
            consumed = Path(directory) / "consumed.json"
            frontier = {}
            sanitize = lambda text, limit: "[withheld]" if "api_key" in text else text[:limit]
            self.assertEqual(consume_outbox(outbox, consumed, frontier, 5, sanitize), 1)
            self.assertEqual([lead["text"] for lead in frontier["leads"]], ["Compare the two specs."])
            self.assertEqual(consume_outbox(outbox, consumed, frontier, 6, sanitize), 0)
            self.assertEqual(len(frontier["leads"]), 1)
            self.assertEqual(len(json.loads(consumed.read_text())["consumed"]), 3)


if __name__ == "__main__":
    unittest.main()
