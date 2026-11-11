import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'scripts'))
from publication_status import update_status


class PublicationStatusTests(unittest.TestCase):
    def setUp(self):
        self.legacy = {
            'schema': 1,
            'region': 'us-ia',
            'last_successful_check_utc': '2026-11-10T18:00:00+00:00',
            'source_data_utc': '2026-11-08T21:21:00Z',
            'last_successful_publication_utc': '2026-11-09T20:00:00+00:00',
            'last_published_version': 'ia-v1',
            'last_check': {'published': True, 'note': 'preserve Iowa history'},
        }
        self.report = {
            'region': 'us-wi', 'checked_utc': '2026-11-11T19:00:00+00:00',
            'source_data_utc': '2026-11-11T06:00:00Z', 'changed': ['roads_-90_43.sqlite'],
            'reused': [], 'removed': [], 'full_bytes': 1500, 'upload_bytes': 1200,
            'duration_seconds': 91.2, 'no_changes': False, 'published': False,
            'version': 'wi-v1',
        }

    def test_migrates_legacy_status_and_updates_only_wisconsin(self):
        original = copy.deepcopy(self.legacy)
        updated = update_status(self.legacy, self.report, dry_run=True)
        self.assertEqual(self.legacy, original)
        self.assertEqual(updated['schema'], 2)
        self.assertEqual(updated['regions']['us-ia']['last_successful_publication_utc'], self.legacy['last_successful_publication_utc'])
        self.assertEqual(updated['regions']['us-ia']['last_published_version'], 'ia-v1')
        self.assertEqual(updated['regions']['us-ia']['last_check'], self.legacy['last_check'])
        self.assertEqual(updated['regions']['us-wi']['last_successful_check_utc'], self.report['checked_utc'])
        self.assertTrue(updated['regions']['us-wi']['last_check']['dry_run'])

    def test_successful_publication_advances_only_its_regions_publication_fields(self):
        report = {**self.report, 'published': True, 'version': 'wi-v2'}
        updated = update_status(self.legacy, report, dry_run=False)
        self.assertEqual(updated['regions']['us-wi']['last_successful_publication_utc'], report['checked_utc'])
        self.assertEqual(updated['regions']['us-wi']['last_published_version'], 'wi-v2')
        self.assertEqual(updated['regions']['us-ia']['last_published_version'], 'ia-v1')

    def test_dry_run_and_noop_preserve_previous_publication(self):
        prior = {'schema': 2, 'regions': {'us-wi': {
            'last_successful_check_utc': '2026-11-10T19:00:00+00:00',
            'last_successful_publication_utc': '2026-11-10T18:00:00+00:00',
            'last_published_version': 'wi-old',
        }}}
        dry = update_status(prior, {**self.report, 'published': True}, dry_run=True)
        noop = update_status(prior, {**self.report, 'no_changes': True, 'published': False}, dry_run=False)
        for result in (dry, noop):
            self.assertEqual(result['regions']['us-wi']['last_successful_publication_utc'], '2026-11-10T18:00:00+00:00')
            self.assertEqual(result['regions']['us-wi']['last_published_version'], 'wi-old')

    def test_backwards_check_time_is_rejected_per_region_only(self):
        current = update_status(self.legacy, self.report, dry_run=True)
        older_wi = {**self.report, 'checked_utc': '2026-11-11T18:00:00+00:00'}
        with self.assertRaises(ValueError):
            update_status(current, older_wi, dry_run=True)
        later_ia = {**self.report, 'region': 'us-ia', 'checked_utc': '2026-11-10T19:00:00+00:00'}
        self.assertEqual(update_status(current, later_ia, dry_run=True)['regions']['us-ia']['last_successful_check_utc'], later_ia['checked_utc'])

    def test_rejects_unknown_region_identifier(self):
        with self.assertRaises(ValueError):
            update_status({}, {**self.report, 'region': 'iowa'}, dry_run=True)


if __name__ == '__main__':
    unittest.main()
