import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TreasuryIntentTests(unittest.TestCase):
    def test_unconfigured_treasury_cannot_create_spendable_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            # The command still records an auditable intent, but policy blocks it.
            completed = subprocess.run([sys.executable, "scripts/treasury_intent.py", "--asset", "USDC",
                                        "--amount", "0.25", "--destination", "11111111111111111111111111111111",
                                        "--purpose", "test"], capture_output=True, text=True, check=True)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "blocked-by-policy")
            self.assertFalse(result["signed"])
            self.assertFalse(result["broadcast"])


if __name__ == "__main__":
    unittest.main()
