import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).parents[1]
REGION_FILE = ROOT / 'regions.json'

STATE_SLUGS = {
    'us-al': 'alabama', 'us-ak': 'alaska', 'us-az': 'arizona', 'us-ar': 'arkansas',
    'us-ca': 'california', 'us-co': 'colorado', 'us-ct': 'connecticut', 'us-de': 'delaware',
    'us-fl': 'florida', 'us-ga': 'georgia', 'us-hi': 'hawaii', 'us-id': 'idaho',
    'us-il': 'illinois', 'us-in': 'indiana', 'us-ia': 'iowa', 'us-ks': 'kansas',
    'us-ky': 'kentucky', 'us-la': 'louisiana', 'us-me': 'maine', 'us-md': 'maryland',
    'us-ma': 'massachusetts', 'us-mi': 'michigan', 'us-mn': 'minnesota', 'us-ms': 'mississippi',
    'us-mo': 'missouri', 'us-mt': 'montana', 'us-ne': 'nebraska', 'us-nv': 'nevada',
    'us-nh': 'new-hampshire', 'us-nj': 'new-jersey', 'us-nm': 'new-mexico', 'us-ny': 'new-york',
    'us-nc': 'north-carolina', 'us-nd': 'north-dakota', 'us-oh': 'ohio', 'us-ok': 'oklahoma',
    'us-or': 'oregon', 'us-pa': 'pennsylvania', 'us-ri': 'rhode-island', 'us-sc': 'south-carolina',
    'us-sd': 'south-dakota', 'us-tn': 'tennessee', 'us-tx': 'texas', 'us-ut': 'utah',
    'us-vt': 'vermont', 'us-va': 'virginia', 'us-wa': 'washington', 'us-wv': 'west-virginia',
    'us-wi': 'wisconsin', 'us-wy': 'wyoming', 'us-dc': 'district-of-columbia',
}


class RegionRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.regions = json.loads(REGION_FILE.read_text())

    def test_registry_contains_each_state_and_dc_once(self):
        self.assertEqual(len(self.regions), 51)
        self.assertEqual(set(self.regions), set(STATE_SLUGS))
        self.assertTrue(all(re.fullmatch(r'us-[a-z]{2}', region_id) for region_id in self.regions))
        self.assertTrue(all(isinstance(entry.get('name'), str) and entry['name'] for entry in self.regions.values()))

    def test_every_url_matches_the_official_geofabrik_us_extract_slug(self):
        base = 'https://download.geofabrik.de/north-america/us/'
        for region_id, slug in STATE_SLUGS.items():
            with self.subTest(region=region_id):
                self.assertEqual(self.regions[region_id]['source_url'], f'{base}{slug}-latest.osm.pbf')

    def test_heavy_extract_schedule_weights_are_explicit(self):
        for region_id, entry in self.regions.items():
            expected = 3 if region_id in {'us-ak', 'us-ca', 'us-tx'} else 1
            with self.subTest(region=region_id):
                self.assertEqual(entry.get('schedule_weight'), expected)

    def test_existing_iowa_and_wisconsin_entries_are_preserved(self):
        self.assertEqual(self.regions['us-ia']['name'], 'Iowa')
        self.assertEqual(self.regions['us-ia']['source_url'],
                         'https://download.geofabrik.de/north-america/us/iowa-latest.osm.pbf')
        self.assertEqual(self.regions['us-wi']['name'], 'Wisconsin')
        self.assertEqual(self.regions['us-wi']['source_url'],
                         'https://download.geofabrik.de/north-america/us/wisconsin-latest.osm.pbf')


if __name__ == '__main__':
    unittest.main()
