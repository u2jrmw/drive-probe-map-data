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

Use Python 3.11+ and install the pinned build dependency with `python -m pip install -r requirements-build.txt`. Download that state's `.osm.pbf` extract from Geofabrik, then run:

```sh
python scripts/build_osm_roads.py iowa-latest.osm.pbf packs/iowa-raw Iowa https://download.geofabrik.de/north-america/us/iowa-latest.osm.pbf
python scripts/package_region.py packs/iowa-raw packs/iowa-release us-ia 2026-11-08 https://github.com/u2jrmw/drive-probe-map-data/releases/download/iowa-2026-11-08-v1
```

The packager checks SQLite integrity and counts, copies only manifest-declared shards and attribution, and generates file hashes plus a catalog. It deliberately excludes arbitrary input files. Every update must use a new immutable release tag/version. Upload all data files except `catalog.json` to that release; verify anonymous downloads before updating the `catalog-v1` catalog asset. When adding another state, merge entries into the catalog rather than replacing existing states. Never include personal drive logs or credentials.

## Scheduled Iowa checks

The `Check and publish offline maps` workflow checks Iowa daily at 07:23 UTC. A run validates and builds the latest source snapshot, compares road content with the complete published Iowa package, and records a successful source check in `publication-status.json`. Semantic grid fingerprints allow unchanged SQLite files to keep their existing immutable release URLs; changed grids and release metadata use a new release. The stable catalog is promoted only after release assets have been checked.

Live publishing is disabled by default. In the repository's **Settings → Secrets and variables → Actions → Variables**, create `MAP_PUBLICATION_ENABLED` with value `false` while validating. Use **Actions → Check and publish offline maps → Run workflow** to perform a dry run; the `dry_run` input defaults to true. The manual region selector currently offers only `us-ia`. After the dry run and staging review, set the variable to `true` to allow scheduled publication. A scheduled run then publishes automatically; a manual run still defaults to dry run, and only `dry_run: false` requests publication. The repository variable must be exactly `true` for either path to publish. A manual `allow_count_anomaly` override is for an investigated road-count or usable-limit-count drop; it does not bypass source-date, integrity, or allowlist validation.

Each successful check records its source timestamp, check time, changed/reused/removed grid counts, full package bytes, uploaded bytes, duration, and whether anything was published. Dry runs and no-change checks advance the successful-check time but preserve the last successful publication time. Failed source checks do not update the status. Successful checks commit this real status to the branch that triggered the workflow; the workflow has no push trigger, so that commit does not start another run. Review failed runs under **Actions** and configure GitHub repository notification settings to email workflow failures to maintainers.

The schedule is best effort: GitHub may delay scheduled work, and source availability or validation failures can skip a publication. Check the last successful source check and publication in `publication-status.json` when monitoring freshness. GitHub may disable scheduled workflows after 60 days without repository activity; the successful-check status commit provides meaningful repository activity while checks are running. If checks stop, review and re-enable the workflow in **Actions**. This setup uses public GitHub-hosted runners and Releases, but does not promise unlimited free runner capacity or punctual schedules. The publisher downloads public OSM source data and manifest-declared map assets only; it never uses trip recordings, coordinates, or private app code.

## Catalog contract

Catalog schema 1 contains `generated_utc` and `regions`. Each region has `id`, `name`, `version`, `published_utc`, `manifest_url`, `installed_bytes`, `download_bytes`, and `files`. Each file has basename-only `path`, public HTTPS `url`, integer `bytes`, and lowercase `sha256`. Totals include the manifest and license. The schema 2 manifest includes `region_id` and `package_version`; each shard has `file`, `bounds`, `records`, `known_limits`, `bytes`, and `sha256`. Bounds order is minimum longitude, maximum longitude, minimum latitude, maximum latitude.
