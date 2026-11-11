import copy
import datetime
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from publication_scheduler import record_attempt, select_regions

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 11, 12, 0, tzinfo=UTC)

def stamp(hours_ago=0):
    return (NOW - datetime.timedelta(hours=hours_ago)).isoformat()

def registry(*ids, weights=None):
    weights = weights or {}
    return {region: {'name': region, 'source_url': 'https://example.test/' + region,
                     **({'schedule_weight': weights[region]} if region in weights else {})}
            for region in ids}


class PublicationSchedulerTests(unittest.TestCase):
    def test_due_selection_uses_23_hour_threshold_for_24_hour_cadence(self):
        config = registry('us-ia', 'us-wi', 'us-il')
        status = {'schema': 2, 'regions': {
            'us-ia': {'last_successful_check_utc': stamp(22)},
            'us-wi': {'last_successful_check_utc': stamp(23)},
        }}
        self.assertEqual(select_regions(config, status, now=NOW), ['us-il', 'us-wi'])

    def test_three_minute_runs_with_hourly_dispatch_keep_all_regions_within_24_hours(self):
        config = json.loads((ROOT / 'regions.json').read_text())
        status = {'schema': 2, 'regions': {}}
        completed = {region_id: [] for region_id in config}
        start = NOW
        for hour in range(8 * 24):
            dispatch = start + datetime.timedelta(hours=hour)
            selected = select_regions(config, status, now=dispatch, budget=3)
            completion = dispatch + datetime.timedelta(minutes=3)
            for region_id in selected:
                entry = status['regions'].setdefault(region_id, {})
                entry['last_successful_check_utc'] = completion.isoformat()
                entry['last_attempt_utc'] = completion.isoformat()
                entry['last_attempt_outcome'] = 'success'
                entry['last_check'] = {'dry_run': False}
                completed[region_id].append(completion)

        for region_id, timestamps in completed.items():
            with self.subTest(region=region_id):
                self.assertTrue(timestamps, f'{region_id} never completed a bootstrap check')
                self.assertLessEqual(timestamps[0] - start, datetime.timedelta(hours=24))
                for previous, following in zip(timestamps, timestamps[1:]):
                    self.assertLessEqual(following - previous, datetime.timedelta(hours=24))

    def test_only_failed_attempts_apply_six_hour_backoff(self):
        config = registry('us-ia', 'us-wi', 'us-il')
        status = {'schema': 2, 'regions': {
            'us-ia': {'last_attempt_utc': stamp(5), 'last_attempt_outcome': 'failure'},
            'us-wi': {'last_attempt_utc': stamp(6), 'last_attempt_outcome': 'failure'},
            'us-il': {'last_attempt_utc': stamp(1), 'last_attempt_outcome': 'dry_run'},
        }}
        self.assertEqual(select_regions(config, status, now=NOW), ['us-wi', 'us-il'])

    def test_published_regions_precede_never_checked_and_oldest_attempt_breaks_ties(self):
        config = registry('us-wi', 'us-ia', 'us-il', 'us-in')
        status = {'schema': 2, 'regions': {
            'us-wi': {'last_published_version': 'wi-v1', 'last_attempt_utc': stamp(30)},
            'us-ia': {'last_published_version': 'ia-v1', 'last_attempt_utc': stamp(10)},
            'us-il': {'last_attempt_utc': stamp(50)},
        }}
        self.assertEqual(select_regions(config, status, now=NOW, budget=3), ['us-wi', 'us-ia', 'us-in'])

    def test_recent_dry_run_check_does_not_suppress_next_live_scheduled_run(self):
        config = registry('us-ia')
        status = {'schema': 2, 'regions': {'us-ia': {
            'last_successful_check_utc': stamp(1),
            'last_check': {'dry_run': True},
        }}}
        self.assertEqual(select_regions(config, status, now=NOW), ['us-ia'])

    def test_recent_dry_run_is_prioritized_with_never_checked_regions(self):
        config = registry('us-ia', 'us-wi', 'us-il')
        status = {'schema': 2, 'regions': {
            'us-ia': {'last_successful_check_utc': stamp(1), 'last_check': {'dry_run': True}},
            'us-wi': {'last_successful_check_utc': stamp(25), 'last_attempt_utc': stamp(2)},
            'us-il': {'last_successful_check_utc': stamp(25), 'last_attempt_utc': stamp(3)},
        }}
        self.assertEqual(select_regions(config, status, now=NOW), ['us-ia', 'us-il', 'us-wi'])

    def test_recent_live_noop_check_does_suppress_next_scheduled_run(self):
        config = registry('us-ia')
        status = {'schema': 2, 'regions': {'us-ia': {
            'last_successful_check_utc': stamp(1),
            'last_check': {'dry_run': False, 'no_changes': True},
        }}}
        self.assertEqual(select_regions(config, status, now=NOW), [])

    def test_leftover_started_attempt_backs_off_then_retries_without_blocking_other_regions(self):
        config = registry('us-ia', 'us-wi')
        status = {'schema': 2, 'regions': {
            'us-ia': {'last_attempt_utc': stamp(5), 'last_attempt_outcome': 'started'},
        }}
        self.assertEqual(select_regions(config, status, now=NOW), ['us-wi'])
        status['regions']['us-ia']['last_attempt_utc'] = stamp(6)
        self.assertEqual(select_regions(config, status, now=NOW), ['us-wi', 'us-ia'])

    def test_newest_failed_bootstrap_attempt_does_not_starve_older_missing_attempt(self):
        config = registry('us-ia', 'us-wi')
        status = {'schema': 2, 'regions': {
            'us-ia': {'last_attempt_utc': stamp(1), 'last_attempt_outcome': 'failure'},
        }}
        self.assertEqual(select_regions(config, status, now=NOW), ['us-wi'])

    def test_weighted_budget_breaks_at_first_nonfitting_region(self):
        config = registry('us-aa', 'us-ak', 'us-al', weights={'us-ak': 3})
        status = {'schema': 2, 'regions': {
            'us-aa': {'last_published_version': 'aa-v1'},
            'us-ak': {'last_published_version': 'ak-v1'},
        }}
        # The first weight-one region fits, but the next weight-three region does not.
        self.assertEqual(select_regions(config, status, now=NOW, budget=3), ['us-aa'])

    def test_first_weight_three_region_is_selected_alone(self):
        config = registry('us-ak', 'us-al', weights={'us-ak': 3})
        status = {'schema': 2, 'regions': {'us-ak': {'last_published_version': 'ak-v1'}}}
        self.assertEqual(select_regions(config, status, now=NOW, budget=3), ['us-ak'])

    def test_manual_region_ignores_due_and_backoff_and_all_is_sorted_full_registry(self):
        config = registry('us-wi', 'us-ia', 'us-il')
        status = {'schema': 2, 'regions': {
            'us-ia': {'last_successful_check_utc': stamp(1), 'last_attempt_utc': stamp(1), 'last_attempt_outcome': 'failure'},
            'us-il': {'last_successful_check_utc': stamp(1)},
            'us-wi': {'last_successful_check_utc': stamp(1)},
        }}
        self.assertEqual(select_regions(config, status, region='us-ia', now=NOW), ['us-ia'])
        self.assertEqual(select_regions(config, status, region='all', now=NOW), ['us-ia', 'us-il', 'us-wi'])

    def test_future_and_malformed_timestamps_do_not_suppress_regions_forever(self):
        config = registry('us-ia', 'us-wi', 'us-il')
        status = {'schema': 2, 'regions': {
            'us-ia': {'last_successful_check_utc': (NOW + datetime.timedelta(days=4)).isoformat()},
            'us-wi': {'last_successful_check_utc': 'not-a-time'},
            'us-il': {'last_attempt_utc': (NOW + datetime.timedelta(days=4)).isoformat(), 'last_attempt_outcome': 'failure'},
        }}
        self.assertEqual(select_regions(config, status, now=NOW), ['us-ia', 'us-wi', 'us-il'])

    def test_record_attempt_preserves_success_history_and_other_regions(self):
        original = {'schema': 2, 'regions': {
            'us-ia': {'last_successful_check_utc': stamp(30), 'last_successful_publication_utc': stamp(50),
                      'last_published_version': 'ia-v4', 'last_attempt_utc': stamp(10), 'last_attempt_outcome': 'failure'},
            'us-wi': {'last_successful_check_utc': stamp(2), 'custom': {'keep': True}},
        }}
        expected = copy.deepcopy(original)
        updated = record_attempt(original, 'us-ia', outcome='failure', now=NOW, run_url='https://example.test/run/1')
        self.assertEqual(original, expected)
        self.assertEqual(updated['schema'], 2)
        self.assertEqual(updated['regions']['us-ia']['last_successful_check_utc'], stamp(30))
        self.assertEqual(updated['regions']['us-ia']['last_successful_publication_utc'], stamp(50))
        self.assertEqual(updated['regions']['us-ia']['last_published_version'], 'ia-v4')
        self.assertEqual(updated['regions']['us-ia']['last_attempt_utc'], NOW.isoformat())
        self.assertEqual(updated['regions']['us-ia']['last_attempt_outcome'], 'failure')
        self.assertEqual(updated['regions']['us-ia']['last_run_url'], 'https://example.test/run/1')
        self.assertEqual(updated['regions']['us-wi'], original['regions']['us-wi'])

    def test_record_started_attempt_preserves_success_history(self):
        prior = {'schema': 2, 'regions': {'us-ia': {
            'last_successful_check_utc': stamp(30),
            'last_successful_publication_utc': stamp(40),
            'last_published_version': 'ia-v1',
            'last_check': {'version': 'ia-v1', 'dry_run': False},
        }}}
        updated = record_attempt(prior, 'us-ia', outcome='started', now=NOW)
        self.assertEqual(updated['regions']['us-ia']['last_successful_check_utc'], stamp(30))
        self.assertEqual(updated['regions']['us-ia']['last_successful_publication_utc'], stamp(40))
        self.assertEqual(updated['regions']['us-ia']['last_published_version'], 'ia-v1')
        self.assertEqual(updated['regions']['us-ia']['last_attempt_outcome'], 'started')

    def test_record_success_or_dry_run_never_advances_success_timestamp(self):
        prior = {'schema': 2, 'regions': {'us-ia': {'last_successful_check_utc': stamp(40)}}}
        for outcome in ('success', 'dry_run'):
            updated = record_attempt(prior, 'us-ia', outcome=outcome, now=NOW)
            self.assertEqual(updated['regions']['us-ia']['last_successful_check_utc'], stamp(40))
            self.assertEqual(updated['regions']['us-ia']['last_attempt_outcome'], outcome)
            self.assertNotIn('last_run_url', updated['regions']['us-ia'])

    def test_schema_one_legacy_status_is_mapped_and_migrated(self):
        legacy = {'schema': 1, 'region': 'us-ia', 'last_successful_check_utc': stamp(25),
                  'last_published_version': 'ia-v1', 'last_attempt_utc': stamp(7)}
        updated = record_attempt(legacy, 'us-ia', outcome='dry_run', now=NOW)
        self.assertEqual(updated['schema'], 2)
        self.assertEqual(updated['regions']['us-ia']['last_successful_check_utc'], stamp(25))
        self.assertEqual(updated['regions']['us-ia']['last_published_version'], 'ia-v1')
        self.assertEqual(select_regions(registry('us-ia', 'us-wi'), legacy, now=NOW), ['us-ia', 'us-wi'])

    def test_invalid_config_status_and_region_requests_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, 'schedule_weight'):
            select_regions({'us-ia': {'name': 'Iowa', 'source_url': 'https://example.test', 'schedule_weight': 0}}, {}, region='due')
        with self.assertRaisesRegex(ValueError, 'Unsupported publication status schema'):
            select_regions(registry('us-ia'), {'schema': 9}, now=NOW)
        with self.assertRaisesRegex(ValueError, 'Unsupported publication status schema'):
            select_regions(registry('us-ia'), {'schema': 9}, region='all', now=NOW)
        with self.assertRaisesRegex(ValueError, 'not in the region registry'):
            select_regions(registry('us-ia'), {}, region='us-wi', now=NOW)

    def test_cli_prints_json_and_writes_github_output(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = pathlib.Path(directory)
            config = temp / 'regions.json'
            status = temp / 'status.json'
            output = temp / 'github-output'
            config.write_text(json.dumps(registry('us-wi', 'us-ia')))
            status.write_text(json.dumps({'schema': 2, 'regions': {'us-ia': {'last_successful_check_utc': stamp(1)}}}))
            result = subprocess.run([
                sys.executable, str(ROOT / 'scripts/publication_scheduler.py'),
                '--region', 'due', '--status', str(status), '--config', str(config), '--budget', '3',
                '--github-output', str(output),
            ], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), ['us-wi'])
            self.assertEqual(output.read_text(), 'regions=["us-wi"]\n')


if __name__ == '__main__':
    unittest.main()
