import unittest
from pathlib import Path


class RuntimeSupervisorTests(unittest.TestCase):
    def test_supervisor_restarts_after_runtime_code_changes(self):
        source = Path("scripts/local_supervisor.py").read_text()
        self.assertIn("def source_signature():", source)
        self.assertIn("source_signature() != signature", source)
        self.assertIn("runtime code changed; daemon restarting", source)


if __name__ == "__main__":
    unittest.main()
