import os
import unittest

from scripts import inference_judge


class InferenceJudgeTests(unittest.TestCase):
    def test_judge_is_opt_in_and_reports_why_when_off(self):
        previous = os.environ.get("BACKROOMS_INFERENCE_JUDGE")
        os.environ["BACKROOMS_INFERENCE_JUDGE"] = "0"
        try:
            status = inference_judge.status()
            self.assertEqual((status["enabled"], status["available"]), (False, False))
            self.assertIsNone(inference_judge.judge_pair({"quote": "a b c d e f g h i j k l m n o p q r s t"}, {"quote": "u v w x y z a b c d e f g h i j k l m n"}))
            self.assertIsNone(inference_judge.similarity("one passage here", "another passage"))
        finally:
            if previous is None:
                os.environ.pop("BACKROOMS_INFERENCE_JUDGE", None)
            else:
                os.environ["BACKROOMS_INFERENCE_JUDGE"] = previous
        self.assertEqual(len(inference_judge.NLI_REVISION), 40)
        self.assertEqual(len(inference_judge.EMBED_REVISION), 40)

    @unittest.skipUnless(os.getenv("BACKROOMS_TEST_INFERENCE") == "1", "set BACKROOMS_TEST_INFERENCE=1 to run the real models")
    def test_real_models_score_paraphrase_contradiction_and_mirror(self):
        os.environ["BACKROOMS_INFERENCE_JUDGE"] = "1"
        self.assertTrue(inference_judge.available(), inference_judge.status())
        same = inference_judge.judge_pair({"quote": "Roskomnadzor blocked access to GitHub in December 2014 after the site hosted pages about suicide."},
                                          {"quote": "Russia's media regulator blocked GitHub over content about suicide in December 2014."})
        self.assertGreater(same["support"], 0.9)
        opposite = inference_judge.judge_pair({"quote": "GitHub's user base grew linearly over the 18-month study period."},
                                              {"quote": "GitHub's user base grew exponentially, doubling every six months during the study."})
        self.assertGreater(opposite["contradiction"], 0.9)
        self.assertGreater(inference_judge.similarity("The AutoHVSR algorithm found the resonances for 99% of the 1109 records",
                                                      "AutoHVSR found the resonances for over 99% of 1109 records"), 0.9)
