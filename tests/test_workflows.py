"""The cycle workflow is the runtime when the world lives on GitHub Actions;
these checks keep its safety properties from regressing."""

import unittest
from pathlib import Path


class CycleWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = Path(".github/workflows/cycle.yml").read_text()

    def test_runs_on_a_schedule_with_no_overlap(self):
        self.assertIn("cron: '*/30 * * * *'", self.text)
        self.assertIn("group: backrooms-cycle", self.text)
        self.assertIn("cancel-in-progress: false", self.text)
        self.assertIn("timeout-minutes:", self.text)

    def test_never_starts_a_local_model_and_names_its_host(self):
        self.assertIn("BACKROOMS_LOCAL_MODEL: never", self.text)
        self.assertIn("BACKROOMS_RUNTIME_HOST: github-actions", self.text)
        self.assertIn("--publish --interval 1800 --max-cycles 3", self.text)
        self.assertIn("BACKROOMS_POST_CYCLE", self.text)
        self.assertIn("gh workflow run pages.yml --ref main", self.text)
        self.assertIn("actions: write", self.text)

    def test_provider_key_goes_to_a_temp_file_and_is_removed(self):
        self.assertIn("secrets.MISTRAL_API_KEY", self.text)
        self.assertIn("install -m 600", self.text)
        self.assertIn("BACKROOMS_ENV_FILE=", self.text)
        self.assertIn('rm -f "$RUNNER_TEMP/backrooms.env"', self.text)
        self.assertNotIn("echo $MISTRAL_API_KEY", self.text)

    def test_private_state_is_a_separate_repository_saved_every_run(self):
        self.assertIn("secrets.STATE_DEPLOY_KEY", self.text)
        self.assertIn("path: state", self.text)
        self.assertIn("if: always()", self.text)
        self.assertIn("git push", self.text)

    def test_site_is_deployed_by_the_cycle_itself(self):
        self.assertIn("needs: cycle", self.text)
        self.assertIn("actions/deploy-pages", self.text)


class PublicRepositoryTests(unittest.TestCase):
    def test_state_directory_is_never_tracked_publicly(self):
        self.assertIn("\nstate/\n", Path(".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
