import hashlib, importlib.util, json, pathlib, sqlite3, tempfile, unittest, sys
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'scripts'))
spec=importlib.util.spec_from_file_location('package_region',pathlib.Path(__file__).parents[1]/'scripts/package_region.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.name='roads_-91_42.sqlite'
        self.write_grid(self.source/self.name, 'Main Street', '[[[-93.1,41.0],[-93.2,41.1]]]')
        self.manifest={'schema':2,'region':'Iowa','shards':[{'file':self.name,'records':1}]}
        self.write_manifest();(self.source/'LICENSE.txt').write_text('ODbL')
        (self.source/'personal-trip.jsonl').write_text('must never publish')
    def write_manifest(self): (self.source/'manifest.json').write_text(json.dumps(self.manifest))
    def run_package(self): return mod.package(self.source,self.root/'out','us-ia','2026-11-08','https://example.com/release')
    @staticmethod
    def write_grid(path, name, paths, page_size=4096):
        path.unlink(missing_ok=True)
        with sqlite3.connect(path) as db:
            db.execute(f'PRAGMA page_size={page_size}')
            db.execute('create table roads(id integer primary key,route text,name text,limit_mph real,paths text,tags text)')
            db.execute('insert into roads values(1,?,?,?,?,?)',('osm-way-1',name,35.0,paths,json.dumps({'highway':'residential','name':name})))
            db.execute('CREATE VIRTUAL TABLE bounds USING rtree(id,min_lon,max_lon,min_lat,max_lat)')
            db.execute('insert into bounds values(1,-93.2,-93.1,41.0,41.1)')
    def test_reject_missing_spatial_index(self):
        with sqlite3.connect(self.source/self.name) as db: db.execute('DROP TABLE bounds')
        with self.assertRaises(ValueError): self.run_package()

    def test_reject_incomplete_spatial_index(self):
        with sqlite3.connect(self.source/self.name) as db: db.execute('DELETE FROM bounds')
        with self.assertRaises(ValueError): self.run_package()

    def test_whitelist_hashes_identity(self):
        catalog=self.run_package();region=catalog['regions'][0]
        self.assertEqual(json.loads((self.root/'out'/'catalog.json').read_text()),catalog)
        self.assertEqual({f['path'] for f in region['files']},{self.name,'manifest.json','LICENSE.txt'})
        for f in region['files']:
            content=(self.root/'out'/f['path']).read_bytes()
            self.assertEqual(len(content),f['bytes']);self.assertEqual(hashlib.sha256(content).hexdigest(),f['sha256'])
        manifest=json.loads((self.root/'out'/'manifest.json').read_text())
        self.assertEqual(manifest['region_id'],'us-ia')
        self.assertEqual(manifest['shards'][0]['content_format'],1)
        self.assertEqual(len(manifest['shards'][0]['content_sha256']),64)
        self.assertEqual(sum(f['bytes'] for f in region['files']),region['installed_bytes'])

    def test_reuses_previous_grid_url_and_exact_bytes_for_equal_content(self):
        first=self.run_package(); previous_region=first['regions'][0]
        previous_manifest=json.loads((self.root/'out'/'manifest.json').read_text())
        old_bytes=(self.root/'out'/self.name).read_bytes()
        # The rebuilt SQLite has different physical layout but identical road content.
        self.write_grid(self.source/self.name,'Main Street','[[[-93.1,41.0],[-93.2,41.1]]]',page_size=8192)
        second=mod.package(self.source,self.root/'out2','us-ia','2026-11-09','https://example.com/release-2',
                           previous_region=previous_region,previous_manifest=previous_manifest,previous_directory=self.root/'out')
        shard=next(f for f in second['regions'][0]['files'] if f['path']==self.name)
        self.assertEqual(shard['url'],next(f for f in previous_region['files'] if f['path']==self.name)['url'])
        self.assertEqual((self.root/'out2'/self.name).read_bytes(),old_bytes)
        self.assertEqual(shard['sha256'],hashlib.sha256(old_bytes).hexdigest())
        self.assertNotEqual(second['regions'][0]['manifest_url'],previous_region['manifest_url'])

    def test_changed_grid_uses_current_release_and_removed_grid_is_omitted(self):
        first=self.run_package(); previous_region=first['regions'][0]
        previous_manifest=json.loads((self.root/'out'/'manifest.json').read_text())
        self.write_grid(self.source/self.name,'Renamed Street','[[[-93.1,41.0],[-93.2,41.1]]]')
        changed=mod.package(self.source,self.root/'changed','us-ia','2026-11-09','https://example.com/release-2',
                            previous_region=previous_region,previous_manifest=previous_manifest,previous_directory=self.root/'out')
        changed_shard=next(f for f in changed['regions'][0]['files'] if f['path']==self.name)
        self.assertEqual(changed_shard['url'],f'https://example.com/release-2/{self.name}')
        self.manifest['shards']=[];self.write_manifest()
        second=mod.package(self.source,self.root/'out2','us-ia','2026-11-10','https://example.com/release-3',
                           previous_region=previous_region,previous_manifest=previous_manifest,previous_directory=self.root/'out')
        self.assertEqual({f['path'] for f in second['regions'][0]['files']},{'manifest.json','LICENSE.txt'})

    def test_legacy_previous_manifest_fingerprints_actual_database(self):
        first=self.run_package(); previous_region=first['regions'][0]
        previous_manifest=json.loads((self.root/'out'/'manifest.json').read_text())
        previous_manifest['shards'][0].pop('content_format');previous_manifest['shards'][0].pop('content_sha256')
        self.write_grid(self.source/self.name,'Main Street','[[[-93.1,41.0],[-93.2,41.1]]]',page_size=8192)
        second=mod.package(self.source,self.root/'out2','us-ia','2026-11-09','https://example.com/release-2',
                           previous_region=previous_region,previous_manifest=previous_manifest,previous_directory=self.root/'out')
        self.assertEqual(next(f for f in second['regions'][0]['files'] if f['path']==self.name)['url'],
                         next(f for f in previous_region['files'] if f['path']==self.name)['url'])

    def test_reads_previous_manifest_from_directory_when_omitted(self):
        first=self.run_package(); previous_region=first['regions'][0]
        self.write_grid(self.source/self.name,'Main Street','[[[-93.1,41.0],[-93.2,41.1]]]',page_size=8192)
        second=mod.package(self.source,self.root/'out2','us-ia','2026-11-09','https://example.com/release-2',
                           previous_region=previous_region,previous_directory=self.root/'out')
        old_url=next(f for f in previous_region['files'] if f['path']==self.name)['url']
        self.assertEqual(next(f for f in second['regions'][0]['files'] if f['path']==self.name)['url'],old_url)

    def test_incompatible_fingerprint_format_forces_grid_asset(self):
        first=self.run_package(); previous_region=first['regions'][0]
        previous_manifest=json.loads((self.root/'out'/'manifest.json').read_text())
        previous_manifest['shards'][0]['content_format']=99
        second=mod.package(self.source,self.root/'out2','us-ia','2026-11-09','https://example.com/release-2',
                           previous_region=previous_region,previous_manifest=previous_manifest,previous_directory=self.root/'out')
        shard=next(f for f in second['regions'][0]['files'] if f['path']==self.name)
        self.assertEqual(shard['url'],f'https://example.com/release-2/{self.name}')

    def test_added_grid_appears_in_complete_target_package(self):
        first=self.run_package(); previous_region=first['regions'][0]
        previous_manifest=json.loads((self.root/'out'/'manifest.json').read_text())
        added='roads_-92_42.sqlite'
        self.write_grid(self.source/added,'Second Road','[[[-92.1,42.0],[-92.2,42.1]]]')
        self.manifest['shards'].append({'file':added,'records':1});self.write_manifest()
        second=mod.package(self.source,self.root/'out2','us-ia','2026-11-09','https://example.com/release-2',
                           previous_region=previous_region,previous_manifest=previous_manifest,previous_directory=self.root/'out')
        files={f['path']:f for f in second['regions'][0]['files']}
        self.assertIn(added,files)
        self.assertEqual(files[added]['url'],f'https://example.com/release-2/{added}')
        self.assertIn(self.name,files)
    def test_reject_traversal(self):
        self.manifest['shards'][0]['file']='../secrets.sqlite';self.write_manifest()
        with self.assertRaises(ValueError): self.run_package()
    def test_reject_wrong_counts(self):
        self.manifest['shards'][0]['records']=99;self.write_manifest()
        with self.assertRaises(ValueError): self.run_package()
    def test_reject_overwrite(self):
        self.run_package()
        with self.assertRaises(ValueError): self.run_package()
if __name__=='__main__': unittest.main()
