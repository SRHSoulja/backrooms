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
