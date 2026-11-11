# U.S. map publication rollout

The registry covers all 50 states and Washington, DC. Only verified published packs enter the app catalog. No private application code or driving data is used by this public pipeline.

- Use standard public Ubuntu runners; do not enable billed larger runners, persistent Actions artifacts, LFS or large dependency/data caches.
- An hourly queue targets successful source checks every 24 hours. Select at most three work units per run. Alaska, California and Texas consume the whole batch; other regions cost one unit.
- Prioritize existing overdue published regions, then bootstrap new ones fairly. Failed attempts are recorded separately from successful checks and wait six hours before retrying. Manual region/dry-run/explicit-all controls remain available.
- Serialize publication and catalog promotion with the shared workflow concurrency group and a one-at-a-time matrix. Each region gets a fresh runner and a 120-minute timeout. Missed/queued cron runs select work from recorded status rather than permanently losing a fixed time slot.
- Preserve per-region source-date/count/integrity gates, immutable grid URLs, complete catalog merges and last-good catalog restoration. Reject release assets >=2 GiB or releases over 1000 new assets before uploading. Reclaim owned temporary source downloads after conversion.
- Record resource usage and attempts even when a region fails, preserving its last successful publication. Regional failures must not prevent other matrix regions from running.
- Verify the registry/scheduler/workflow and publisher guards locally, then run a small live-region publication and a California dry run on the standard runner before claiming nationwide resource compatibility.

Daily coverage is a target, not a timing guarantee: GitHub schedule delays, source outages, rate limits and heavy builds can defer a region. Initial packs populate gradually, roughly over a day under normal runtimes. A registered region is not advertised as downloadable until its pack passes publication checks. State/pack sizes shown in the app are measured output sizes, not PBF estimates.

Limits checked November 11, 2026: standard public runners have no monthly compute-minute charge; hosted jobs have a six-hour service limit (our timeout is two hours); Ubuntu public runners provide 4 CPUs / 16 GB RAM / 14 GB SSD; release assets must be below 2 GiB with at most 1000 assets per release. The repository's GITHUB_TOKEN has a 1000-request/hour primary API limit plus secondary limits. No promise of unrestricted infrastructure or future pricing is made.

Sources: https://docs.github.com/en/billing/concepts/product-billing/github-actions , https://docs.github.com/en/actions/reference/limits , https://docs.github.com/en/actions/reference/runners/github-hosted-runners , https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases , https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api .
