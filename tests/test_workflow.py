import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).parents[1]


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / '.github/workflows/update-maps.yml').read_text()

    def test_daily_schedule_runs_both_states_and_manual_selection_is_explicit(self):
        self.assertIn("cron: '23 7 * * *'", self.workflow)
        self.assertIn('type: choice\n        required: true\n        default: us-ia\n        options:\n          - us-ia\n          - us-wi', self.workflow)
        self.assertIn("fromJSON(github.event_name == 'schedule' && '[\"us-ia\",\"us-wi\"]'", self.workflow)
        self.assertIn('max-parallel: 1', self.workflow)
        self.assertIn('dry_run:\n        description: Check and build without publishing\n        type: boolean\n        required: true\n        default: true', self.workflow)
        self.assertIn('allow_count_anomaly:\n        description: Allow an explained road or speed-limit count drop\n        type: boolean\n        required: true\n        default: false', self.workflow)

    def test_job_is_guarded_serialized_bounded_and_minimally_privileged(self):
        self.assertIn("contents: write", self.workflow)
        self.assertIn('timeout-minutes: 120', self.workflow)
        self.assertRegex(self.workflow, r'cancel-in-progress:\s*false')
        self.assertIn("vars.MAP_PUBLICATION_ENABLED == 'true'", self.workflow)
        self.assertIn('group: map-publication', self.workflow)

    def test_tests_run_before_build_and_actions_are_full_sha_pinned(self):
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertLess(self.workflow.index("python -m unittest discover -s tests -v"),
                        self.workflow.index('scripts/publish_maps.py'))
        for reference in re.findall(r'uses:\s*([^\s]+)', self.workflow):
            if reference.startswith('actions/'):
                self.assertRegex(reference, r'@[0-9a-f]{40}$')
        self.assertIn('requirements-build.txt', self.workflow)
        self.assertIn('python-version: "3.11"', self.workflow)

    def test_publisher_modes_are_gated_and_status_commit_is_truthful(self):
        self.assertIn('args+=(--publish)', self.workflow)
        self.assertIn('args+=(--dry-run)', self.workflow)
        self.assertIn('/usr/bin/time -v', self.workflow)
        self.assertIn('publication-result.json', self.workflow)
        self.assertIn('publication-status.json', self.workflow)
        self.assertIn('publication_status import update_status', self.workflow)
        self.assertIn('update_status(status, report, dry_run=dry_run)', self.workflow)
        self.assertIn('git diff --cached --quiet', self.workflow)
        self.assertIn('HEAD:${BRANCH_NAME}', self.workflow)

    def test_readme_documents_safe_setup_and_freshness_limits(self):
        readme = (ROOT / 'README.md').read_text()
        for detail in (
            '07:23 UTC', 'MAP_PUBLICATION_ENABLED', 'dry_run` input defaults to true',
            'publication-status.json', '60 days', 'never uses trip recordings',
            'does not promise unlimited free runner capacity',
            'Iowa and Wisconsin', 'us-wi', 'keyed by region ID', 'one region at a time',
        ):
            with self.subTest(detail=detail):
                self.assertIn(detail, readme)


if __name__ == '__main__':
    unittest.main()
