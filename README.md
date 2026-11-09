# Drive Probe map data

Public offline road and explicit speed-limit databases for Drive Probe. Iowa is the only initial region. Additional U.S. states can be prepared individually when needed; no nationwide generation runs automatically.

The app downloads selected states to the device and matches roads offline. These are road databases, not map tiles. Missing or unsupported speed-limit tags remain unknown; coverage is not guaranteed and posted signs take precedence.

## Downloads

The app catalog is [catalog.json](https://github.com/u2jrmw/drive-probe-map-data/releases/download/catalog-v1/catalog.json). Each catalog entry identifies an immutable release, all required files, byte counts, and SHA-256 checksums. SQLite shards, the manifest, and attribution are release assets rather than Git history. No authentication is required.

The initial Iowa pack uses the Geofabrik snapshot dated November 7, 2026, with a November 8 live OSM tag refresh described in its manifest. It contains 542,433 road ways and 27,048 explicit usable speed limits. No personal driving records or private app code are included.

## Data license

© OpenStreetMap contributors. These adapted databases are provided under the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/). See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright). The downloadable databases themselves are the machine-readable adapted database. Preserve attribution and comply with ODbL when redistributing or adapting them.

Source extracts: [Geofabrik U.S. downloads](https://download.geofabrik.de/north-america/us.html). Transformations filter motor roads, retain relevant tags, round coordinates, and index road geometry in SQLite. Unsupported conditional/directional limits are intentionally left unknown.

## Prepare one region

Use Python 3.11+ and `pip install osmium`. Download that state's `.osm.pbf` extract from Geofabrik, then run:

```sh
python scripts/build_osm_roads.py iowa-latest.osm.pbf packs/iowa-raw Iowa https://download.geofabrik.de/north-america/us/iowa-latest.osm.pbf
python scripts/package_region.py packs/iowa-raw packs/iowa-release us-ia 2026-11-08 https://github.com/u2jrmw/drive-probe-map-data/releases/download/iowa-2026-11-08-v1
```

The packager checks SQLite integrity and counts, copies only manifest-declared shards and attribution, and generates file hashes plus a catalog. It deliberately excludes arbitrary input files. Every update must use a new immutable release tag/version. Upload all data files except `catalog.json` to that release; verify anonymous downloads before updating the `catalog-v1` catalog asset. When adding another state, merge entries into the catalog rather than replacing existing states. Never include personal drive logs or credentials.

## Catalog contract

Catalog schema 1 contains `generated_utc` and `regions`. Each region has `id`, `name`, `version`, `published_utc`, `manifest_url`, `installed_bytes`, `download_bytes`, and `files`. Each file has basename-only `path`, public HTTPS `url`, integer `bytes`, and lowercase `sha256`. Totals include the manifest and license. The schema 2 manifest includes `region_id` and `package_version`; each shard has `file`, `bounds`, `records`, `known_limits`, `bytes`, and `sha256`. Bounds order is minimum longitude, maximum longitude, minimum latitude, maximum latitude.
