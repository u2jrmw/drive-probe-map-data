import hashlib, importlib.util, json, pathlib, sqlite3, tempfile, unittest
spec=importlib.util.spec_from_file_location('package_region',pathlib.Path(__file__).parents[1]/'scripts/package_region.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.name='roads_-91_42.sqlite'
        with sqlite3.connect(self.source/self.name) as db:
            db.execute('create table roads(id integer)');db.execute('insert into roads values(1)')
        self.manifest={'schema':2,'region':'Iowa','shards':[{'file':self.name,'records':1}]}
        self.write_manifest();(self.source/'LICENSE.txt').write_text('ODbL')
        (self.source/'personal-trip.jsonl').write_text('must never publish')
    def write_manifest(self): (self.source/'manifest.json').write_text(json.dumps(self.manifest))
    def run_package(self): return mod.package(self.source,self.root/'out','us-ia','2026-11-08','https://example.com/release')
    def test_whitelist_hashes_identity(self):
        catalog=self.run_package();region=catalog['regions'][0]
        self.assertEqual({f['path'] for f in region['files']},{self.name,'manifest.json','LICENSE.txt'})
        for f in region['files']:
            content=(self.root/'out'/f['path']).read_bytes()
            self.assertEqual(len(content),f['bytes']);self.assertEqual(hashlib.sha256(content).hexdigest(),f['sha256'])
        manifest=json.loads((self.root/'out'/'manifest.json').read_text())
        self.assertEqual(manifest['region_id'],'us-ia')
        self.assertEqual(sum(f['bytes'] for f in region['files']),region['installed_bytes'])
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
