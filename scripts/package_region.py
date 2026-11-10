"""Package a complete road database with optional immutable-grid reuse."""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import sqlite3

from grid_content import CONTENT_FORMAT, fingerprint_grid


def _safe_basename(name):
    if not isinstance(name, str) or pathlib.PurePath(name).name != name or name in ('', '.', '..'):
        raise ValueError('Unsafe filename')
    return name


def _sha256(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _manifest(path):
    try:
        result = json.loads(pathlib.Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Unable to read package manifest: {path}') from exc
    if not isinstance(result, dict) or result.get('schema') != 2 or not isinstance(result.get('shards'), list):
        raise ValueError('Expected a schema-2 manifest with a shard list')
    return result


def _validate_shard(path, expected_records):
    if isinstance(expected_records, bool) or not isinstance(expected_records, int) or expected_records < 0:
        raise ValueError('Invalid shard record count')
    try:
        with sqlite3.connect(f'file:{pathlib.Path(path).resolve().as_posix()}?mode=ro', uri=True) as db:
            integrity = db.execute('PRAGMA quick_check').fetchone()
            if integrity is None or integrity[0] != 'ok':
                raise ValueError('Corrupt database')
            db.execute('SELECT route,name,limit_mph,paths,tags FROM roads JOIN bounds ON roads.id=bounds.id WHERE min_lon<=? AND max_lon>=? AND min_lat<=? AND max_lat>=? LIMIT 0',(0,0,0,0))
            valid_index=db.execute('SELECT (SELECT count(*) FROM bounds)=(SELECT count(*) FROM roads) AND NOT EXISTS(SELECT 1 FROM roads LEFT JOIN bounds USING(id) WHERE bounds.id IS NULL)').fetchone()[0]
            if not valid_index: raise ValueError('Spatial index does not cover every road')
            count = db.execute('SELECT count(*) FROM roads').fetchone()[0]
            if count != expected_records:
                raise ValueError('Record count mismatch')
    except sqlite3.Error as exc:
        raise ValueError('Invalid road database') from exc


def package(source, output, region_id, version, base_url, previous_region=None,
            previous_manifest=None, previous_directory=None):
    source, output = pathlib.Path(source), pathlib.Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output must be empty')
    if not re.fullmatch(r'us-[a-z]{2}', region_id) or not re.fullmatch(r'[a-zA-Z0-9.-]+', version):
        raise ValueError('Invalid region or version')
    if not isinstance(base_url, str) or not base_url.startswith('https://'):
        raise ValueError('HTTPS release URL required')
    manifest = _manifest(source / 'manifest.json')
    if previous_manifest is None and previous_directory is not None:
        prior_manifest_path = pathlib.Path(previous_directory) / 'manifest.json'
        if prior_manifest_path.is_file():
            previous_manifest = _manifest(prior_manifest_path)
    previous_shards = {}
    previous_files = {}
    if previous_region is not None:
        if not isinstance(previous_region, dict) or not isinstance(previous_region.get('files'), list):
            raise ValueError('Invalid previous catalog region')
        for entry in previous_region['files']:
            if not isinstance(entry, dict):
                raise ValueError('Invalid previous catalog file entry')
            name = _safe_basename(entry.get('path'))
            previous_files[name] = entry
        if previous_manifest is not None:
            if not isinstance(previous_manifest, dict) or not isinstance(previous_manifest.get('shards'), list):
                raise ValueError('Invalid previous manifest')
            for shard in previous_manifest['shards']:
                if not isinstance(shard, dict):
                    raise ValueError('Invalid previous shard declaration')
                name = _safe_basename(shard.get('file'))
                previous_shards[name] = shard

    output.mkdir(parents=True, exist_ok=True)
    files = []
    release_root = base_url.rstrip('/')

    def record(name, url=None):
        path = output / name
        files.append(dict(path=name, url=url or f'{release_root}/{name}', bytes=path.stat().st_size,
                          sha256=_sha256(path)))
        return files[-1]

    def copy_current(name):
        shutil.copyfile(source / name, output / name)

    shards = manifest['shards']
    if not isinstance(shards, list):
        raise ValueError('Invalid shard list')
    names = set()
    for shard in shards:
        if not isinstance(shard, dict):
            raise ValueError('Invalid shard declaration')
        name = _safe_basename(shard.get('file'))
        if not re.fullmatch(r'roads_-?\d+_-?\d+\.sqlite', name) or name in names:
            raise ValueError('Invalid or duplicate shard')
        names.add(name)
        current_path = source / name
        _validate_shard(current_path, shard.get('records'))
        current_content = fingerprint_grid(current_path)
        declared_format = shard.get('content_format')
        declared_hash = shard.get('content_sha256')
        if declared_format is not None and declared_format != CONTENT_FORMAT:
            raise ValueError('Unsupported current shard content format')
        if declared_hash is not None and declared_hash != current_content:
            raise ValueError('Current shard semantic fingerprint mismatch')
        shard.update(content_format=CONTENT_FORMAT, content_sha256=current_content)

        reused = False
        old_file = previous_files.get(name)
        old_shard = previous_shards.get(name)
        if (previous_directory is not None and old_file is not None and old_shard is not None):
            old_path = pathlib.Path(previous_directory) / name
            if not old_path.is_file():
                raise ValueError(f'Missing previous grid: {name}')
            old_hash = _sha256(old_path)
            if old_hash != old_file.get('sha256') or old_path.stat().st_size != old_file.get('bytes'):
                raise ValueError(f'Previous grid checksum/size mismatch: {name}')
            old_format = old_shard.get('content_format')
            old_content = old_shard.get('content_sha256')
            if old_format == CONTENT_FORMAT and isinstance(old_content, str) and re.fullmatch(r'[0-9a-f]{64}', old_content):
                same_content = old_content == current_content
            elif old_format is None and old_content is None:
                # Legacy manifests have no semantic fingerprint: derive it from their actual DB.
                _validate_shard(old_path, old_shard.get('records'))
                same_content = fingerprint_grid(old_path) == current_content
            else:
                same_content = False
            if same_content:
                shutil.copyfile(old_path, output / name)
                entry = record(name, old_file.get('url'))
                reused = True
        if not reused:
            copy_current(name)
            entry = record(name)
        shard.update(bytes=entry['bytes'], sha256=entry['sha256'])

    # The complete new package has only target shards plus release-specific metadata.
    copy_current('LICENSE.txt')
    record('LICENSE.txt')
    manifest.update(region_id=region_id, package_version=version)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    record('manifest.json')
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total = sum(file['bytes'] for file in files)
    region = dict(id=region_id, name=manifest['region'], version=version, published_utc=now,
                  manifest_url=f'{release_root}/manifest.json', installed_bytes=total,
                  download_bytes=total, files=files)
    if manifest.get('data_timestamp'):
        region['source_data_utc'] = manifest['data_timestamp']
    catalog = dict(schema=1, generated_utc=now, regions=[region])
    (output / 'catalog.json').write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n')
    return catalog


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'region_id', 'version', 'base_url'):
        parser.add_argument(name)
    args = parser.parse_args()
    result = package(**vars(args))
    region = result['regions'][0]
    print(f"Prepared {region['name']}: {region['download_bytes']:,} bytes")
