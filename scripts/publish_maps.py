"""Build a complete catalog with reusable immutable grids. Dry-run by default."""
import argparse, datetime, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, time, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
REPO = 'u2jrmw/drive-probe-map-data'
CATALOG_URL = f'https://github.com/{REPO}/releases/download/catalog-v1/catalog.json'
UTC = datetime.timezone.utc

def timestamp(value):
    if not isinstance(value,str): raise ValueError('Missing source timestamp')
    parsed=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None: raise ValueError('Source timestamp needs timezone')
    return parsed.astimezone(UTC)

def latest_source(manifest):
    values=[manifest.get(k) for k in ('data_timestamp','source_data_utc','live_osm_refresh_utc','live_tag_refresh_utc','tag_refresh_utc') if manifest.get(k)]
    # Legacy refresh metadata can be nested. Never silently ignore its date.
    for k,v in manifest.items():
        if 'refresh' in k.lower() and isinstance(v,dict):
            values += [v[n] for n in ('timestamp','retrieved_utc','updated_utc') if v.get(n)]
    if not values: raise ValueError('Published map has no verifiable source date')
    return max(values,key=timestamp)

def validate_source(source,previous=None,now=None):
    value=timestamp(source);now=now or datetime.datetime.now(UTC)
    if value > now+datetime.timedelta(hours=1):raise ValueError('Source timestamp is in the future')
    if now-value > datetime.timedelta(hours=72):raise ValueError('Source extract is older than 72 hours')
    if previous and value<timestamp(previous):raise ValueError('Source extract predates published data or tag refresh')

def validate_counts(current,previous,allow=False):
    if current.get('roads',0)<=0:raise ValueError('Empty road pack')
    for key,fraction in [('roads',.9),('explicit_limits',.8)]:
        if previous.get(key,0)>0 and current.get(key,0)<previous[key]*fraction and not allow:
            raise ValueError(f'Unexpected {key} drop; inspect and explicitly approve count anomaly')

def merge_catalog(previous,region,now):
    regions=[r for r in previous.get('regions',[]) if r['id']!=region['id']]+[region]
    return dict(schema=1,generated_utc=now,regions=sorted(regions,key=lambda r:r['id']))

def download(url,target,expected=None):
    if not url.startswith('https://'):raise ValueError('HTTPS required')
    target=pathlib.Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(4):
        try:
            digest=hashlib.sha256();size=0
            request=urllib.request.Request(url,headers={'User-Agent':'DriveProbe-MapPublisher/1.0','Cache-Control':'no-cache'})
            with urllib.request.urlopen(request,timeout=120) as response,open(target,'wb') as output:
                while True:
                    block=response.read(1024*1024)
                    if not block:break
                    digest.update(block);size+=len(block);output.write(block)
            if expected and (size!=expected['bytes'] or digest.hexdigest()!=expected['sha256'].lower()):raise ValueError('Remote size/hash mismatch: '+target.name)
            return
        except Exception:
            if attempt==3:raise
            time.sleep(2**attempt)

def read_json(url):
    with tempfile.TemporaryDirectory() as root:
        file=pathlib.Path(root)/'data.json';download(url,file);return json.loads(file.read_text())

class GitHubTransport:
    def __init__(self,repo=REPO):self.repo=repo
    def gh(self,*args,input=None):
        run=subprocess.run(['gh',*args,'--repo',self.repo],input=input,capture_output=True,text=True)
        if run.returncode:raise RuntimeError('GitHub operation failed: '+run.stderr.strip())
        return run.stdout
    def catalog(self):return read_json(CATALOG_URL+"?check="+str(time.time_ns()))
    def upload(self,tag,directory,files):
        try:self.gh('release','view',tag,'--json','tagName')
        except RuntimeError:self.gh('release','create',tag,'--title',tag,'--notes','Automated OpenStreetMap road database snapshot. © OpenStreetMap contributors · ODbL 1.0.')
        assets=json.loads(self.gh('release','view',tag,'--json','assets'))['assets']
        existing={a['name']:a for a in assets}
        for entry in files:
            if entry['path'] in existing:
                with tempfile.TemporaryDirectory() as root:download(entry['url'],pathlib.Path(root)/entry['path'],entry)
            else:self.gh('release','upload',tag,str(directory/entry['path']))
    def verify(self,files):
        with tempfile.TemporaryDirectory() as root:
            for entry in files:download(entry['url'],pathlib.Path(root)/entry['path'],entry)
    def promote(self,catalog):
        # GitHub's asset replacement can briefly 404. Save and restore last-good bytes on failure.
        previous=self.catalog()
        with tempfile.TemporaryDirectory() as root:
            path=pathlib.Path(root)/'catalog.json';path.write_text(json.dumps(catalog,indent=2)+'\n')
            try:
                self.gh('release','upload','catalog-v1',str(path),'--clobber')
                actual=self.catalog()
                if actual!=catalog:raise ValueError('Published catalog verification failed')
            except Exception:
                path.write_text(json.dumps(previous,indent=2)+'\n')
                self.gh('release','upload','catalog-v1',str(path),'--clobber')
                raise

def publish_prepared(transport,tag,directory,region):
    # Only upload entries belonging to this immutable release, not reused older grids.
    files=[f for f in region['files'] if '/'+tag+'/' in f['url']]
    transport.upload(tag,directory,files)
    transport.verify(region['files'])
    current=transport.catalog()
    existing=next((r for r in current.get('regions',[]) if r['id']==region['id']),None)
    if existing and existing.get('source_data_utc') and timestamp(existing['source_data_utc'])>timestamp(region['source_data_utc']):
        raise ValueError('A newer state was published while this job was building')
    catalog=merge_catalog(current,region,datetime.datetime.now(UTC).isoformat())
    transport.promote(catalog)
    return catalog

def publish_region(region_id,*,dry_run=True,allow_count_anomaly=False,source_path=None,workspace=None,transport=None,stage_only=False):
    from build_osm_roads import build
    from package_region import package
    from grid_content import fingerprint_grid, CONTENT_FORMAT
    start=time.monotonic();transport=transport or GitHubTransport()
    config=json.loads((pathlib.Path(__file__).parents[1]/'regions.json').read_text())
    if region_id not in config:raise ValueError('Region is not offered: '+region_id)
    region=config[region_id]
    with tempfile.TemporaryDirectory(dir=workspace) as temporary:
        root=pathlib.Path(temporary);previous=transport.catalog()
        old=next((r for r in previous['regions'] if r['id']==region_id),None)
        old_manifest=None;prior=root/'prior';prior.mkdir()
        if old:
            for entry in old['files']:
                name=entry['path']
                if pathlib.Path(name).name!=name or name in ('','.','..'):raise ValueError('Unsafe previous asset name')
                download(entry['url'],prior/name,entry)
            old_manifest=json.loads((prior/'manifest.json').read_text())
        source=pathlib.Path(source_path) if source_path else root/'source.osm.pbf'
        if not source_path:download(region['source_url'],source)
        raw=root/'raw';build(str(source),raw,region['name'],region['source_url'])
        manifest=json.loads((raw/'manifest.json').read_text())
        source_time=manifest['data_timestamp']
        validate_source(source_time,latest_source(old_manifest) if old_manifest else None)
        if old_manifest:validate_counts(manifest['counts'],old_manifest.get('counts',{}),allow_count_anomaly)
        previous_shards={s['file']:s for s in (old_manifest or {}).get('shards',[])}
        changed=[];reused=[]
        for shard in manifest['shards']:
            old_shard=previous_shards.get(shard['file'])
            same=old_shard and old_shard.get('content_format') in (None,CONTENT_FORMAT) and fingerprint_grid(raw/shard['file'])==fingerprint_grid(prior/shard['file'])
            (reused if same else changed).append(shard['file'])
        removed=sorted(set(previous_shards)-{s['file'] for s in manifest['shards']})
        old_source=latest_source(old_manifest) if old_manifest else None
        noop=not changed and not removed and old_source==source_time
        report=dict(region=region_id,source_data_utc=source_time,checked_utc=datetime.datetime.now(UTC).isoformat(),changed=changed,reused=reused,removed=removed,full_bytes=old['download_bytes'] if noop and old else 0,upload_bytes=0,published=False,no_changes=noop)
        if not noop:
            version=source_time[:10]+'-'+manifest['source_sha256'][:10]+'-f'+str(CONTENT_FORMAT)+'-'+datetime.datetime.now(UTC).strftime('%Y%m%d%H%M%S')
            tag=region_id+'-'+version
            base=f'https://github.com/{REPO}/releases/download/{tag}'
            output=root/'release'
            catalog=package(raw,output,region_id,version,base,previous_region=old,previous_manifest=old_manifest,previous_directory=prior if old else None)
            result=catalog['regions'][0];result['source_data_utc']=source_time
            report['full_bytes']=result['download_bytes']
            report['upload_bytes']=sum(f['bytes'] for f in result['files'] if '/'+tag+'/' in f['url'])
            report['version']=version
            if not dry_run:
                if stage_only:
                    new_files=[f for f in result['files'] if '/'+tag+'/' in f['url']]
                    transport.upload(tag,output,new_files);transport.verify(result['files'])
                    report['staged']=True
                    report['candidate_catalog']=merge_catalog(previous,result,datetime.datetime.now(UTC).isoformat())
                else:
                    publish_prepared(transport,tag,output,result);report['published']=True
        report['duration_seconds']=round(time.monotonic()-start,2)
        return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region',default='us-ia');parser.add_argument('--publish',action='store_true');parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--allow-count-anomaly',action='store_true');parser.add_argument('--source');parser.add_argument('--stage',action='store_true',help='Upload immutable candidate assets without updating the live catalog');parser.add_argument('--summary',default='publication-result.json')
    args=parser.parse_args()
    if sum([args.publish,args.dry_run,args.stage])>1:parser.error('Choose --publish, --stage or --dry-run')
    result=publish_region(args.region,dry_run=not (args.publish or args.stage),stage_only=args.stage,allow_count_anomaly=args.allow_count_anomaly,source_path=args.source)
    pathlib.Path(args.summary).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
