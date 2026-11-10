"""Build a regional offline pack from an OSM PBF (pip install osmium).
Usage: python build_osm_roads.py INPUT.osm.pbf OUTPUT_DIRECTORY REGION SOURCE_URL
Database output is an ODbL derivative of OpenStreetMap, separate from app code.
"""
import datetime,json,math,pathlib,re,sqlite3,sys,hashlib
from grid_content import CONTENT_FORMAT, fingerprint_grid

def explicit_limit(tags):
    # Conditional, directional, lane and other extended rules require a richer evaluator.
    if any(k.startswith('maxspeed:') for k in tags):return None
    raw=tags.get('maxspeed','').strip().lower()
    m=re.fullmatch(r'(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?',raw)
    if not m:return None
    value=float(m[1]);mph=value if m[2]=='mph' else value/1.609344
    return mph if 0<mph<=100 else None

EXCLUDED={'footway','path','cycleway','steps','pedestrian','bridleway','construction','proposed','platform','corridor','raceway'}

def build(source,output,region,url):
    import osmium
    output=pathlib.Path(output)
    if output.exists() and any(output.iterdir()):raise RuntimeError('Use an empty output directory')
    output.mkdir(parents=True,exist_ok=True)
    dbs={};stats={};boxes={};counts={'roads':0,'explicit_limits':0,'invalid_geometry':0}
    class Handler(osmium.SimpleHandler):
        def way(self,w):
            t=dict(w.tags)
            if 'highway' not in t or t['highway'] in EXCLUDED or t.get('motor_vehicle')=='no' or t.get('motorcar')=='no':return
            if any(not n.location.valid() for n in w.nodes):counts['invalid_geometry']+=1;return
            points=[[round(n.lon,7),round(n.lat,7)] for n in w.nodes]
            if len(points)<2:return
            bb=[min(p[0] for p in points),max(p[0] for p in points),min(p[1] for p in points),max(p[1] for p in points)]
            key=f'{math.floor((bb[0]+bb[1])/2)}_{math.floor((bb[2]+bb[3])/2)}'
            if key not in dbs:
                db=sqlite3.connect(output/f'roads_{key}.sqlite');db.execute('CREATE TABLE roads(id INTEGER PRIMARY KEY,route TEXT,name TEXT,limit_mph REAL,paths TEXT,tags TEXT)');db.execute('CREATE VIRTUAL TABLE bounds USING rtree(id,min_lon,max_lon,min_lat,max_lat)');dbs[key]=db;stats[key]=[0,0];boxes[key]=[180,-180,90,-90]
            limit=explicit_limit(t);db=dbs[key]
            keep={k:v for k,v in t.items() if k in ('name','highway','oneway','access','motor_vehicle','motorcar','source:maxspeed') or k.startswith('maxspeed')}
            db.execute('INSERT INTO roads VALUES(?,?,?,?,?,?)',(w.id,f'osm-way-{w.id}',t.get('name') or t.get('ref') or 'Unnamed road',limit,json.dumps([points],separators=(',',':')),json.dumps(keep,separators=(',',':'))))
            db.execute('INSERT INTO bounds VALUES(?,?,?,?,?)',(w.id,*bb));stats[key][0]+=1;stats[key][1]+=limit is not None;counts['roads']+=1;counts['explicit_limits']+=limit is not None
            old=boxes[key];boxes[key]=[min(old[0],bb[0]),max(old[1],bb[1]),min(old[2],bb[2]),max(old[3],bb[3])]
    reader=osmium.io.Reader(str(source));header=reader.header();data_time=header.get('osmosis_replication_timestamp');reader.close()
    Handler().apply_file(str(source),locations=True,idx='flex_mem')
    for db in dbs.values():db.commit();assert db.execute('pragma quick_check').fetchone()[0]=='ok';db.execute('VACUUM');db.close()
    manifest={'schema':2,'region':region,'source':'OpenStreetMap','source_url':url,'data_timestamp':data_time,'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_sha256':hashlib.file_digest(open(source,'rb'),'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest(),'license':'ODbL 1.0','attribution':'© OpenStreetMap contributors','license_url':'https://opendatacommons.org/licenses/odbl/1-0/','counts':counts,'shards':[{'file':f'roads_{k}.sqlite','bounds':boxes[k],'records':stats[k][0],'known_limits':stats[k][1],'content_format':CONTENT_FORMAT,'content_sha256':fingerprint_grid(output/f'roads_{k}.sqlite')} for k in sorted(dbs)]}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (output/'LICENSE.txt').write_text('© OpenStreetMap contributors\nThis adapted database is available under the Open Database License (ODbL) 1.0.\nhttps://opendatacommons.org/licenses/odbl/1-0/\nhttps://www.openstreetmap.org/copyright\nSource extract: '+url+'\nModifications: filtered motor roads, selected tags, coordinate rounding and indexed SQLite conversion.\n')
    print(json.dumps(counts));print('Pack bytes:',sum(p.stat().st_size for p in output.iterdir()))
if __name__=='__main__':build(*sys.argv[1:])
