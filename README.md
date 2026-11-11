# Drive Probe map data

Public offline road and explicit speed-limit databases for Drive Probe. The build registry covers all 50 states plus Washington, DC. New regions are prepared gradually by the hourly queue; only successfully validated and published packs appear as available downloads in the app.

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

## Nationwide daily checks through a small hourly queue

The `Check and publish offline maps` workflow wakes hourly at minute 23 UTC. It targets a successful live check for each of the 50 states and DC every 24 hours, rather than launching 51 builds simultaneously. The registry is `regions.json`; all source URLs were verified against Geofabrik’s official index. Iowa and Wisconsin retain their existing region IDs, downloads and publication history. New packs appear progressively, roughly over a day under normal build times; regions that have not passed publication are not advertised as downloadable.

Each hourly run selects up to three work units from actual check/attempt history. Alaska (`us-ak`), California (`us-ca`) and Texas (`us-tx`) each consume a whole batch; other regions use one unit. The matrix builds one region at a time on a fresh standard Ubuntu runner. Workflow-wide concurrency serializes manual runs, scheduled runs and catalog promotion, preventing two regions from overwriting each other’s catalog updates. Newer queued hourly runs can replace an older pending run; selection from recorded status catches unfinished work on the next run. This is a best-effort daily target, not an exact delivery time.

Overdue published regions take priority so bootstrap work does not neglect existing users. First attempts and older attempts are chosen fairly. A start marker is committed before expensive work, so a lost runner or job timeout cannot look like an untried region. Failed or abandoned-start attempts wait six hours before automatic retry; successful builds finalize the marker while preserving the last good map on failure. The publisher process stops after 100 minutes, with a 105-minute step and 120-minute job budget leaving cleanup headroom. A failed state does not cancel other matrix states. Failures do not advance successful-check/publication timestamps. Dry runs are recorded but do not satisfy the live daily check. Successful source checks, no-change checks and publications update only their own region under the schema-2 `publication-status.json` regions object.

Live publication is controlled by the existing Actions variable `MAP_PUBLICATION_ENABLED`. It must be exactly `true` for either scheduled or manual publication. To pause automatic publication, set it to `false`. Manual **Run workflow** offers `due` (the small automatic queue), a specific `us-xx` region, or `all` (an explicit full serial matrix). The `dry_run` input defaults to true; set it false only to request publication. Explicit `all` bypasses the small batch budget and is primarily an operator recovery/validation tool, not the normal nationwide schedule. The `allow_count_anomaly` override is only for investigated count drops; it does not bypass freshness, integrity, release-size or allowlist checks.

Semantic grid fingerprints reuse unchanged immutable files. Every catalog entry still lists the complete target package, including reused older URLs, and catalog promotion happens only after checksums and anonymous downloads are verified. Never delete old releases simply by age: newer packs can still reference their unchanged grids. Source-date regression, unexpectedly low road/limit counts or corrupt files keep the last good region available.

### GitHub limits and costs

Standard GitHub-hosted runners in this public repository have no monthly compute-minute charge. The workflow does not use billed larger runners, persistent build artifacts, Git LFS or large data caches. Downloads are Release assets, separate from Actions artifact storage. Our regional timeout is two hours, below GitHub’s six-hour hosted-job limit. Public Ubuntu runners have 4 CPUs, 16 GB RAM and 14 GB SSD; California and other large regions need measured headroom rather than a promise that every state will fit. Owned temporary source PBFs are removed after conversion to free space before packaging.

GitHub Release files must be below 2 GiB and there can be at most 1000 assets per release; the publisher rejects candidates exceeding those limits before upload. A state may total more than 2 GiB because it is split into individual grid assets. GitHub documents no total release-size or release-download bandwidth quota. The repository’s `GITHUB_TOKEN` has a primary API limit of 1000 requests/hour plus secondary limits, so publication is serialized and heavy regions are isolated. Resource usage is included in workflow summaries. Rate limits, source outages, runner disk/memory and workflow delays can still cause a state to fail safely; inspect its run before changing resource/batch settings.

This setup does not promise unlimited free runner capacity or punctual schedules. GitHub may disable scheduled workflows after 60 days without repository activity; meaningful attempt/status commits provide activity while jobs run. If the queue stops, review **Actions**, enable it if necessary, and inspect last successful check versus last attempt in `publication-status.json`. The publisher never uses trip recordings, coordinates or private app code.

References: [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Actions limits](https://docs.github.com/en/actions/reference/limits), [runner hardware](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), [release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases), [API limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).

## Catalog contract

Catalog schema 1 contains `generated_utc` and `regions`. Each region has `id`, `name`, `version`, `published_utc`, `manifest_url`, `installed_bytes`, `download_bytes`, and `files`. Each file has basename-only `path`, public HTTPS `url`, integer `bytes`, and lowercase `sha256`. Totals include the manifest and license. The schema 2 manifest includes `region_id` and `package_version`; each shard has `file`, `bounds`, `records`, `known_limits`, `bytes`, and `sha256`. Bounds order is minimum longitude, maximum longitude, minimum latitude, maximum latitude.
