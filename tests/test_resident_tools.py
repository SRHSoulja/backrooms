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
        self.assertEqual((record["status"], record["name"], record["tests_passed"], record["tests_total"]), ("ready-for-review", "word_count", 2, 2))
        failing = GOOD.replace("'3'", "'4'")
        bad = resident_tools.propose_tool("local-003", 310, "word count two", "counts words", failing, path=self.ledger)
        self.assertEqual(bad["status"], "rejected")
        self.assertIn("tests failed", bad["reason"])
        again = resident_tools.propose_tool("local-004", 311, "word count", "counts words", GOOD, path=self.ledger)
        self.assertEqual(again["id"], record["id"])  # same code and name: same record
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual([item["status"] for item in ledger["proposals"]], ["ready-for-review", "rejected"])

    def test_approval_is_a_human_step_and_approved_tools_preload_into_analysis(self):
        record = resident_tools.propose_tool("local-003", 310, "word count", "counts words", GOOD, path=self.ledger)
        self.assertEqual(resident_tools.approved_tools(self.tools), [])
        target = resident_tools.approve(record["id"], path=self.ledger, tools_dir=self.tools, approver="tester")
        self.assertEqual(target.name, "word_count.py")
        tools = resident_tools.approved_tools(self.tools)
        self.assertEqual([(t["name"], t["description"]) for t in tools], [("word_count", "counts words")])
        prelude = resident_tools.prelude(self.tools)
        self.assertIn("def tool_word_count(", prelude)
        self.assertNotIn("TESTS", prelude)
        result = sandbox_run("print(tool_word_count(data))", "one two three four", prelude)
        self.assertEqual((result["status"], result["output"].strip()), ("completed", "4"))
        with self.assertRaises(SystemExit):
            resident_tools.approve(record["id"], path=self.ledger, tools_dir=self.tools)  # already approved
        self.assertEqual(json.loads(self.ledger.read_text())["proposals"][0]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
