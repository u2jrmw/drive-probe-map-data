"""Package an existing road database for public, checksummed distribution.
Only manifest-declared shards and LICENSE.txt are copied; never arbitrary input files.
"""
import argparse, datetime, hashlib, json, pathlib, re, shutil, sqlite3

def package(source, output, region_id, version, base_url):
    source, output = pathlib.Path(source), pathlib.Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output must be empty')
    if not re.fullmatch(r'us-[a-z]{2}', region_id) or not re.fullmatch(r'[a-zA-Z0-9.-]+', version):
        raise ValueError('Invalid region or version')
    if not base_url.startswith('https://'):
        raise ValueError('HTTPS release URL required')
    manifest = json.loads((source/'manifest.json').read_text())
    assert manifest['schema'] == 2
    output.mkdir(parents=True, exist_ok=True)
    files = []
    def copy(name):
        if pathlib.Path(name).name != name or name in ('', '.', '..'):
            raise ValueError('Unsafe filename')
        shutil.copyfile(source/name, output/name)
        return record(name)
    def record(name):
        p = output/name
        entry = dict(path=name, url=base_url.rstrip('/')+'/'+name, bytes=p.stat().st_size,
                     sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        files.append(entry)
        return entry
    names = set()
    for shard in manifest['shards']:
        name = shard['file']
        if not re.fullmatch(r'roads_-?\d+_-?\d+\.sqlite', name) or name in names:
            raise ValueError('Invalid or duplicate shard')
        names.add(name)
        with sqlite3.connect(f'file:{source/name}?mode=ro', uri=True) as db:
            if db.execute('pragma quick_check').fetchone()[0] != 'ok':
                raise ValueError('Corrupt database')
            if db.execute('select count(*) from roads').fetchone()[0] != shard['records']:
                raise ValueError('Record count mismatch')
        entry = copy(name)
        shard.update(bytes=entry['bytes'], sha256=entry['sha256'])
    copy('LICENSE.txt')
    manifest.update(region_id=region_id, package_version=version)
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    record('manifest.json')
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total = sum(f['bytes'] for f in files)
    catalog = dict(schema=1, generated_utc=now, regions=[dict(
        id=region_id, name=manifest['region'], version=version, published_utc=now,
        manifest_url=base_url.rstrip('/')+'/manifest.json',
        installed_bytes=total, download_bytes=total, files=files)])
    (output/'catalog.json').write_text(json.dumps(catalog, indent=2)+'\n')
    return catalog

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'region_id', 'version', 'base_url'): p.add_argument(name)
    args = p.parse_args()
    result = package(**vars(args))
    print(f"Prepared {result['regions'][0]['name']}: {result['regions'][0]['download_bytes']:,} bytes")
