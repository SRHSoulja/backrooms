import unittest

from scripts.capability_policy import policy_for, public_catalog


class CapabilityPolicyTests(unittest.TestCase):
    def test_dangerous_capabilities_are_never_granted(self):
        self.assertEqual(policy_for("external-write")["grant"], "never")
        self.assertEqual(policy_for("financial-transaction")["grant"], "never")

    def test_catalog_projection_contains_explicit_policy(self):
        tools = public_catalog()["tools"]
        self.assertTrue(tools)
        self.assertTrue(all("grant" in tool and "prerequisites" in tool for tool in tools))


if __name__ == "__main__":
    unittest.main()
