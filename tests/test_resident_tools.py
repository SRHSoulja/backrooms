import json
import tempfile
import unittest
from pathlib import Path

from scripts import resident_tools
from scripts.code_sandbox import run as sandbox_run

GOOD = "def tool(text):\n    return str(len(text.split()))\nTESTS = [['a b c', '3'], ['', '0']]\n"


class ResidentToolTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="backrooms-tools-"))
        self.ledger = self.dir / "tool-proposals.json"
        self.tools = self.dir / "tools"

    def test_validation_requires_tool_and_tests_under_sandbox_rules(self):
        self.assertEqual(resident_tools.validate_tool(GOOD), "")
        self.assertIn("def tool(text)", resident_tools.validate_tool("def other(x):\n    return x\nTESTS = [[1, 1], [2, 2]]"))
        self.assertIn("TESTS", resident_tools.validate_tool("def tool(text):\n    return text\n"))
        self.assertIn("sandbox rules", resident_tools.validate_tool("import os\ndef tool(text):\n    return os.getcwd()\nTESTS = [[1, 1], [2, 2]]"))
        self.assertIn("credentials", resident_tools.validate_tool("def tool(text):\n    return 'api_key'\nTESTS = [[1, 1], [2, 2]]"))

    def test_proposal_is_gated_by_its_own_tests(self):
        record = resident_tools.propose_tool("local-003", 310, "word count", "counts words", GOOD, path=self.ledger)
        self.assertEqual((record["status"], record["name"], record["tests_passed"], record["tests_total"]), ("trial", "word_count", 2, 2))
        failing = GOOD.replace("'3'", "'4'")
        bad = resident_tools.propose_tool("local-003", 310, "word count two", "counts words", failing, path=self.ledger)
        self.assertEqual(bad["status"], "rejected")
        self.assertIn("tests failed", bad["reason"])
        again = resident_tools.propose_tool("local-004", 311, "word count", "counts words", GOOD, path=self.ledger)
        self.assertEqual(again["id"], record["id"])  # same code and name: same record
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual([item["status"] for item in ledger["proposals"]], ["trial", "rejected"])

    def test_a_passing_tool_is_on_trial_at_once_and_another_residents_use_adopts_it(self):
        adopted_dir = self.tools / "adopted"
        record = resident_tools.propose_tool("local-003", 310, "word count", "counts words", GOOD, path=self.ledger)
        self.assertEqual(record["status"], "trial")
        self.assertEqual(resident_tools.approved_tools(self.tools, adopted_dir), [])
        available = resident_tools.available_tools(self.tools, self.ledger, adopted_dir)
        self.assertEqual([(t["name"], t["status"], t["resident"]) for t in available], [("word_count", "trial", "local-003")])
        prelude = resident_tools.prelude(self.tools, self.ledger, adopted_dir)
        self.assertIn("def tool_word_count(", prelude)
        self.assertNotIn("TESTS", prelude)
        result = sandbox_run("print(tool_word_count(data))", "one two three four", prelude)
        self.assertEqual((result["status"], result["output"].strip()), ("completed", "4"))
        # the proposer's own use does not adopt; a failed analysis by someone else does not either
        self.assertEqual(resident_tools.note_use("print(tool_word_count(data))", "local-003", 311, "completed", self.ledger, adopted_dir), ([], ["word_count"]))
        self.assertEqual(resident_tools.note_use("x = tool_word_count(data)", "local-007", 312, "failed", self.ledger, adopted_dir), ([], ["word_count"]))
        self.assertEqual(json.loads(self.ledger.read_text())["proposals"][0]["status"], "trial")
        # another resident's completed analysis adopts it into state/tools
        adopted, used = resident_tools.note_use("print(tool_word_count(data))", "local-007", 313, "completed", self.ledger, adopted_dir)
        self.assertEqual((adopted[0]["name"], adopted[0]["adopted_by"], used), ("word_count", "local-007", ["word_count"]))
        self.assertTrue((adopted_dir / "word_count.py").exists())
        tools = resident_tools.approved_tools(self.tools, adopted_dir)
        self.assertEqual([(t["name"], t["status"], t["description"]) for t in tools], [("word_count", "adopted", "counts words")])
        self.assertIn("def tool_word_count(", resident_tools.prelude(self.tools, self.ledger, adopted_dir))
        ledger = json.loads(self.ledger.read_text())["proposals"][0]
        self.assertEqual((ledger["status"], len(ledger["uses"])), ("adopted", 3))
        # a name on trial or adopted cannot be taken again; an unused trial expires
        again = resident_tools.propose_tool("local-009", 314, "word count", "counts words differently", GOOD.replace("len(text.split())", "len(text.split()) + 0"), path=self.ledger)
        self.assertEqual(again["status"], "rejected")
        other = resident_tools.propose_tool("local-009", 314, "shout", "upper-cases", GOOD.replace("word_count", "shout"), path=self.ledger)
        self.assertEqual(other["status"], "trial")
        self.assertEqual(resident_tools.expire_trials(314 + resident_tools.TRIAL_CYCLES - 1, self.ledger), [])
        expired = resident_tools.expire_trials(314 + resident_tools.TRIAL_CYCLES, self.ledger)
        self.assertEqual([item["name"] for item in expired], ["shout"])
        self.assertEqual(resident_tools.tool_names_in("a = tool_alpha(x) + tool_beta_2(y)"), ["alpha", "beta_2"])

    def test_manual_override_still_adopts_a_trial_tool_by_hand(self):
        record = resident_tools.propose_tool("local-003", 310, "word count", "counts words", GOOD, path=self.ledger)
        target = resident_tools.approve(record["id"], path=self.ledger, tools_dir=self.tools, approver="tester")
        self.assertEqual(target.name, "word_count.py")
        self.assertEqual(json.loads(self.ledger.read_text())["proposals"][0]["status"], "approved")
        with self.assertRaises(SystemExit):
            resident_tools.approve(record["id"], path=self.ledger, tools_dir=self.tools)


if __name__ == "__main__":
    unittest.main()
