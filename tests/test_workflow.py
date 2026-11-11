import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).parents[1]


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / '.github/workflows/update-maps.yml').read_text()

    def test_hourly_dispatcher_targets_daily_checks_with_a_small_dynamic_matrix(self):
        self.assertIn("cron: '23 * * * *'", self.workflow)
        self.assertIn('scripts/publication_scheduler.py', self.workflow)
        self.assertIn('--budget 3', self.workflow)
        self.assertIn('--github-output "$GITHUB_OUTPUT"', self.workflow)
        self.assertIn("fromJSON(needs.plan.outputs.regions)", self.workflow)
        self.assertIn("needs.plan.outputs.regions != '[]'", self.workflow)
        self.assertIn('max-parallel: 1', self.workflow)
        self.assertIn('default: due', self.workflow)
        self.assertIn('default: true', self.workflow)
        self.assertIn('allow_count_anomaly:', self.workflow)

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
        self.assertIn('record_attempt', self.workflow)
        self.assertIn("steps.publish.outcome", self.workflow)
        self.assertIn('always()', self.workflow)
        self.assertIn('timeout-minutes: 105', self.workflow)
        self.assertIn('timeout --signal=TERM --kill-after=30s 100m', self.workflow)
        self.assertIn("outcome='started'", self.workflow)
        self.assertLess(self.workflow.index("outcome='started'"), self.workflow.index('Install pinned map build dependencies'))
        self.assertIn('git diff --cached --quiet', self.workflow)
        self.assertIn('HEAD:${BRANCH_NAME}', self.workflow)

    def test_readme_documents_safe_setup_and_freshness_limits(self):
        readme = (ROOT / 'README.md').read_text()
        for detail in (
            'hourly', '24 hours', 'MAP_PUBLICATION_ENABLED', 'dry_run` input defaults to true',
            'publication-status.json', '60 days', 'never uses trip recordings',
            'does not promise unlimited free runner capacity', '50 states', 'DC',
            'one region at a time', 'six hours', '2 GiB',
        ):
            with self.subTest(detail=detail):
                self.assertIn(detail, readme)


if __name__ == '__main__':
    unittest.main()
