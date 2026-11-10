import importlib.util
import json
import pathlib
import sqlite3
import tempfile
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / 'scripts/grid_content.py'
spec = importlib.util.spec_from_file_location('grid_content', MODULE_PATH)
grid_content = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid_content)


def make_db(path, rows, *, reverse=False, page_size=4096):
    with sqlite3.connect(path) as db:
        db.execute(f'PRAGMA page_size={page_size}')
        db.execute('CREATE TABLE roads(id INTEGER PRIMARY KEY, route TEXT, name TEXT, limit_mph REAL, paths TEXT, tags TEXT)')
        for row in rows:
            tags = json.loads(row[-1]) if isinstance(row[-1], str) else row[-1]
            if reverse:
                tags = dict(reversed(list(tags.items())))
            db.execute('INSERT INTO roads VALUES(?,?,?,?,?,?)', (*row[:-1], json.dumps(tags)))
        if reverse:
            db.commit()
            db.execute('VACUUM')


class GridContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.rows = [
            (2, 'osm-way-2', 'Second', 35.0, '[[[-93.1,41.0],[-93.2,41.1]]]', {'highway': 'residential', 'oneway': 'yes'}),
            (1, 'osm-way-1', 'First', None, '[[[-93.0,41.0],[-93.05,41.05]]]', {'name': 'First', 'highway': 'service'}),
        ]

    def fingerprint(self, name, rows=None, **kwargs):
        path = self.root / name
        make_db(path, rows if rows is not None else self.rows, **kwargs)
        return grid_content.fingerprint_grid(path)

    def test_ignores_insert_order_tag_json_order_and_sqlite_layout(self):
        first = self.fingerprint('first.sqlite')
        second = self.fingerprint('second.sqlite', list(reversed(self.rows)), reverse=True, page_size=8192)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_changes_to_meaningful_road_content_change_fingerprint(self):
        baseline = self.fingerprint('base.sqlite')
        variants = [
            [(3, *self.rows[0][1:]), self.rows[1]],
            [(*self.rows[0][:2], 'Renamed', *self.rows[0][3:]), self.rows[1]],
            [(*self.rows[0][:3], 36.0, *self.rows[0][4:]), self.rows[1]],
            [(*self.rows[0][:4], '[[[-93.1,41.0],[-93.25,41.1]]]', self.rows[0][5]), self.rows[1]],
            [(*self.rows[0][:5], {'highway': 'residential', 'oneway': 'no'}), self.rows[1]],
        ]
        for index, rows in enumerate(variants):
            with self.subTest(index=index):
                self.assertNotEqual(baseline, self.fingerprint(f'changed-{index}.sqlite', rows))

    def test_preserves_geometry_direction_and_empty_grid_fingerprint(self):
        baseline = self.fingerprint('base.sqlite')
        reversed_geometry = [(*self.rows[0][:4], '[[[-93.2,41.1],[-93.1,41.0]]]', self.rows[0][5]), self.rows[1]]
        self.assertNotEqual(baseline, self.fingerprint('reversed.sqlite', reversed_geometry))
        empty = self.fingerprint('empty.sqlite', [])
        self.assertEqual(empty, self.fingerprint('empty-again.sqlite', []))
        self.assertNotEqual(baseline, empty)

    def test_normalizes_numeric_coordinate_representation(self):
        integer_coords = [(*self.rows[0][:4], '[[[-93,41],[-94,42]]]', self.rows[0][5]), self.rows[1]]
        float_coords = [(*self.rows[0][:4], '[[[-93.0,41.0],[-94.0,42.0]]]', self.rows[0][5]), self.rows[1]]
        self.assertEqual(self.fingerprint('integer-coordinates.sqlite', integer_coords),
                         self.fingerprint('float-coordinates.sqlite', float_coords))

    def test_rejects_malformed_tags_or_geometry(self):
        for index, row in enumerate([
            (*self.rows[0][:5], '{not-json'),
            (*self.rows[0][:4], 'not-json', self.rows[0][5]),
        ]):
            path = self.root / f'malformed-{index}.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE roads(id INTEGER PRIMARY KEY, route TEXT, name TEXT, limit_mph REAL, paths TEXT, tags TEXT)')
                db.execute('INSERT INTO roads VALUES(?,?,?,?,?,?)', (*row[:-1], json.dumps(row[-1]) if isinstance(row[-1], dict) else row[-1]))
            with self.subTest(index=index), self.assertRaises(ValueError):
                grid_content.fingerprint_grid(path)

    def test_rejects_coordinates_outside_geographic_ranges(self):
        rows = [(*self.rows[0][:4], '[[[181,41],[-93.2,41.1]]]', self.rows[0][5])]
        path = self.root / 'out-of-range.sqlite'
        make_db(path, rows)
        with self.assertRaises(ValueError):
            grid_content.fingerprint_grid(path)


if __name__ == '__main__':
    unittest.main()
