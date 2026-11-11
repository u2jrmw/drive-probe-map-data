import datetime, importlib.util, pathlib, unittest, tempfile, json
from unittest import mock
spec=importlib.util.spec_from_file_location('publish_maps',pathlib.Path(__file__).parents[1]/'scripts/publish_maps.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class SourceTests(unittest.TestCase):
 def test_source_freshness_and_regression(self):
  now=datetime.datetime(2026,11,10,tzinfo=datetime.timezone.utc)
  p.validate_source('2026-11-09T00:00:00Z','2026-11-08T00:00:00Z',now=now)
  for source,previous in [(None,None),('2026-11-01T00:00:00Z',None),('2026-11-08T00:00:00Z','2026-11-09T00:00:00Z')]:
   with self.assertRaises(ValueError):p.validate_source(source,previous,now=now)
 def test_counts_override_only_count_anomalies(self):
  p.validate_counts({'roads':90,'explicit_limits':80},{'roads':100,'explicit_limits':100})
  for counts in [{'roads':89,'explicit_limits':100},{'roads':100,'explicit_limits':79}]:
   with self.assertRaises(ValueError):p.validate_counts(counts,{'roads':100,'explicit_limits':100})
   p.validate_counts(counts,{'roads':100,'explicit_limits':100},allow=True)
 def test_complete_merge_preserves_other_state(self):
  old={'schema':1,'generated_utc':'old','regions':[{'id':'us-ia','version':'old'},{'id':'us-il','version':'keep'}]}
  result=p.merge_catalog(old,{'id':'us-ia','version':'new'},'newtime')
  self.assertEqual([r['version'] for r in result['regions']],['new','keep'])
  self.assertEqual(old['regions'][0]['version'],'old')
 def test_publication_order_and_failed_verification(self):
  class Transport:
   def __init__(self,fail=False):self.events=[];self.fail=fail
   def upload(self,tag,directory,files):self.events.append('upload')
   def verify(self,files):
    self.events.append('verify')
    if self.fail:raise ValueError('bad remote hash')
   def catalog(self):self.events.append('read');return {'schema':1,'regions':[]}
   def promote(self,catalog):self.events.append('promote')
  region={'id':'us-ia','files':[],'source_data_utc':'2026-11-09T00:00:00Z'}
  t=Transport();p.publish_prepared(t,'tag',pathlib.Path('.'),region)
  self.assertEqual(t.events,['upload','verify','read','promote'])
  t=Transport(True)
  with self.assertRaises(ValueError):p.publish_prepared(t,'tag',pathlib.Path('.'),region)
  self.assertNotIn('promote',t.events)
 def test_release_limits_are_checked_before_upload(self):
  p.validate_release_assets([{'path':'roads.sqlite','bytes':2*1024**3-1}])
  for files in [[{'path':'too-big.sqlite','bytes':2*1024**3}], [{'path':'x','bytes':1}]*1001]:
   with self.assertRaises(ValueError):p.validate_release_assets(files)
 def test_invalid_asset_cannot_promote_a_catalog(self):
  class Transport:
   def upload(self,*args):raise AssertionError('Must reject oversized files before any upload')
  region={'id':'us-ca','files':[{'path':'roads.sqlite','url':'https://example.test/tag/roads.sqlite','bytes':2*1024**3}]}
  with self.assertRaises(ValueError):p.publish_prepared(Transport(),'tag',pathlib.Path('.'),region)
 def test_dry_run_validates_the_same_release_limits_as_publication(self):
  class Transport:
   def catalog(self):return {'schema':1,'regions':[]}
   def upload(self,*args):raise AssertionError('A dry run must not upload')
  def fake_build(source,output,name,url):
   output.mkdir()
   manifest={'data_timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'source_sha256':'a'*64,'counts':{'roads':1,'explicit_limits':0},'shards':[]}
   (output/'manifest.json').write_text(json.dumps(manifest))
  for count,size in [(1,2*1024**3),(1001,1)]:
   def fake_package(raw,output,region_id,version,base,**kwargs):
    return {'regions':[{'id':region_id,'files':[{'path':f'roads-{i}.sqlite','url':base+f'/roads-{i}.sqlite','bytes':size} for i in range(count)],'download_bytes':count*size}]}
   with tempfile.TemporaryDirectory() as root:
    source=pathlib.Path(root)/'input.pbf';source.write_bytes(b'fixture')
    with mock.patch('build_osm_roads.build',side_effect=fake_build),mock.patch('package_region.package',side_effect=fake_package):
     with self.assertRaises(ValueError):p.publish_region('us-ca',dry_run=True,source_path=source,transport=Transport())
 def test_unknown_source_on_legacy_refresh_fails_closed(self):
  self.assertEqual(p.latest_source({'data_timestamp':'2026-11-07T00:00:00Z','live_osm_refresh_utc':'2026-11-08T00:00:00Z'}),'2026-11-08T00:00:00Z')
if __name__=='__main__':unittest.main()
