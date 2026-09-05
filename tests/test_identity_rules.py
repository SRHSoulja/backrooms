import unittest

from scripts.identity_rules import is_reserved_name, name_stem, shares_stem


class IdentityRuleTests(unittest.TestCase):
    def test_reserved_names_stay_reserved(self):
        self.assertTrue(is_reserved_name("Echo Prime"))
        self.assertFalse(is_reserved_name("Vex-9"))

    def test_a_stem_is_the_first_real_word(self):
        self.assertEqual(name_stem("Vex-9"), "vex")
        self.assertEqual(name_stem("Vex-282"), "vex")
        self.assertEqual(name_stem("Dr. Glimmerbeam"), "glimmerbeam")
        self.assertEqual(name_stem("Lumen-7"), "lumen")
        self.assertEqual(name_stem("42"), "")

    def test_new_hires_may_not_echo_a_current_resident_with_a_new_number(self):
        roster = ["Lumen-7", "Vex-9", "Vex-282"]
        self.assertEqual(shares_stem("Vex-300", roster), "Vex-9")
        self.assertEqual(shares_stem("vex prime", roster), "Vex-9")
        self.assertIsNone(shares_stem("Sable-3", roster))
        self.assertIsNone(shares_stem("Lumen-7", []))
        self.assertIn("shares_stem(", open("scripts/local_recruiter.py").read())


if __name__ == "__main__":
    unittest.main()


class RegistryRetentionTests(unittest.TestCase):
    def test_trimming_the_registry_never_drops_an_active_resident(self):
        try:
            from scripts.identity_rules import retain_registry
        except ImportError:
            from identity_rules import retain_registry
        agents = ([{"id": "local-001", "status": "active-local"}] +
                  [{"id": f"local-{n:03d}", "status": "retired"} for n in range(2, 6)] +
                  [{"id": "local-006", "status": "probation"}])
        kept = retain_registry(agents, 3)
        self.assertEqual([a["id"] for a in kept], ["local-001", "local-005", "local-006"])
        self.assertEqual(retain_registry(agents, 10), agents)
        # every record active: nothing is dropped even over the limit
        active = [{"id": f"local-{n:03d}", "status": "active-local"} for n in range(1, 5)]
        self.assertEqual(retain_registry(active, 2), active)


class RecruiterImportTests(unittest.TestCase):
    def test_every_name_the_recruiter_imports_from_identity_rules_exists(self):
        import re
        from scripts import identity_rules
        source = open("scripts/local_recruiter.py").read()
        statements = re.findall(r"from (?:scripts\.)?identity_rules import ([^\n]+)", source)
        self.assertGreaterEqual(len(statements), 2)
        for names in statements:
            for name in [part.strip() for part in names.split(",")]:
                self.assertTrue(hasattr(identity_rules, name), name)
