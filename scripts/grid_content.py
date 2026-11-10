"""Canonical semantic fingerprints for published road-grid databases."""
import hashlib
import json
import math
import pathlib
import sqlite3

CONTENT_FORMAT = 1
_BATCH_SIZE = 512


def _decode_json(value, label):
    if not isinstance(value, str):
        raise ValueError(f'{label} must be JSON text')
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f'Malformed {label} JSON') from exc


def _canonical_tags(value):
    tags = _decode_json(value, 'tags')
    if not isinstance(tags, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in tags.items()):
        raise ValueError('Tags must be an object of string keys and values')
    return tags


def _canonical_paths(value):
    paths = _decode_json(value, 'paths')
    if not isinstance(paths, list) or not paths:
        raise ValueError('Paths must be a nonempty list')
    result = []
    for path in paths:
        if not isinstance(path, list) or len(path) < 2:
            raise ValueError('Each path must contain at least two coordinates')
        points = []
        for point in path:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('Coordinates must be longitude/latitude pairs')
            coords = []
            for coordinate in point:
                if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate):
                    raise ValueError('Coordinates must be finite numbers')
                coords.append(float(round(coordinate, 7)))
            if not -180 <= coords[0] <= 180 or not -90 <= coords[1] <= 90:
                raise ValueError('Coordinates are outside longitude/latitude ranges')
            points.append(coords)
        result.append(points)
    return result


def _road_record(row):
    way_id, route, name, limit_mph, paths, tags = row
    if isinstance(way_id, bool) or not isinstance(way_id, int):
        raise ValueError('Road ID must be an integer')
    if not isinstance(route, str) or not isinstance(name, str):
        raise ValueError('Road route and name must be text')
    if limit_mph is not None and (isinstance(limit_mph, bool) or not isinstance(limit_mph, (int, float)) or not math.isfinite(limit_mph)):
        raise ValueError('Road limit must be a finite number or null')
    if limit_mph is not None:
        limit_mph = float(limit_mph)
    return [way_id, route, name, limit_mph, _canonical_paths(paths), _canonical_tags(tags)]


def fingerprint_grid(path: pathlib.Path) -> str:
    """Hash road meaning, independent of SQLite row order, tags JSON order, or layout.

    Rows are streamed in primary-key order. Malformed content raises ``ValueError``
    so callers cannot accidentally classify an unreadable grid as unchanged.
    """
    path = pathlib.Path(path)
    digest = hashlib.sha256()
    digest.update(f'driveprobe-grid-content:{CONTENT_FORMAT}\n'.encode('ascii'))
    try:
        connection = sqlite3.connect(f'file:{path.resolve().as_posix()}?mode=ro', uri=True)
        with connection:
            columns = {row[1] for row in connection.execute('PRAGMA table_info(roads)')}
            required = {'id', 'route', 'name', 'limit_mph', 'paths', 'tags'}
            if not required.issubset(columns):
                raise ValueError('Road database is missing required semantic columns')
            cursor = connection.execute('SELECT id, route, name, limit_mph, paths, tags FROM roads ORDER BY id')
            while rows := cursor.fetchmany(_BATCH_SIZE):
                for row in rows:
                    payload = json.dumps(_road_record(row), ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':'), allow_nan=False)
                    digest.update(payload.encode('utf-8'))
                    digest.update(b'\n')
    except sqlite3.Error as exc:
        raise ValueError(f'Unable to fingerprint road database: {path}') from exc
    finally:
        if 'connection' in locals():
            connection.close()
    return digest.hexdigest()
