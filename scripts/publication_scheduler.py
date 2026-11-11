"""Select bounded, fair regions for scheduled OSM package publication."""
from __future__ import annotations
import argparse
import copy
import datetime
import json
import re
import sys
from pathlib import Path

from publication_status import _regions_from

UTC = datetime.timezone.utc
_REGION_ID = re.compile(r'us-[a-z]{2}\Z')
_CHECK_INTERVAL = datetime.timedelta(hours=24)
_FAILURE_BACKOFF = datetime.timedelta(hours=6)


def _utc_now(now):
    if now is None:
        return datetime.datetime.now(UTC)
    if not isinstance(now, datetime.datetime):
        raise ValueError('now must be a datetime')
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must include a timezone')
    return now.astimezone(UTC)


def _timestamp(value):
    """Parse an ISO timestamp, returning None when absent or unusable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    try:
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _validated_config(config):
    if not isinstance(config, dict):
        raise ValueError('Region config must be an object keyed by region ID')
    regions = {}
    for region_id, entry in config.items():
        if not isinstance(region_id, str) or not _REGION_ID.fullmatch(region_id):
            raise ValueError(f'Invalid region ID in config: {region_id!r}')
        if not isinstance(entry, dict):
            raise ValueError(f'Invalid config entry for {region_id}: expected an object')
        if not isinstance(entry.get('name'), str) or not entry['name']:
            raise ValueError(f'Invalid config entry for {region_id}: name is required')
        if not isinstance(entry.get('source_url'), str) or not entry['source_url']:
            raise ValueError(f'Invalid config entry for {region_id}: source_url is required')
        weight = entry.get('schedule_weight', 1)
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
            raise ValueError(f'Invalid schedule_weight for {region_id}: expected a positive integer')
        regions[region_id] = weight
    return regions


def _status_regions(status):
    if status is None:
        return {}
    return _regions_from(status)


def select_regions(config: dict, status: dict, *, region: str = 'due',
                   now: datetime.datetime | None = None, budget: int = 3) -> list[str]:
    """Select manual or scheduled publication targets from the registry and status."""
    weights = _validated_config(config)
    status_regions = _status_regions(status)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise ValueError('budget must be a nonnegative integer')
    if not isinstance(region, str):
        raise ValueError('region must be due, all, or a us-xx ID')
    ordered_ids = sorted(weights)
    if region == 'all':
        return ordered_ids
    if region != 'due':
        if not _REGION_ID.fullmatch(region):
            raise ValueError(f'Invalid region selector: {region!r}; expected due, all, or a us-xx ID')
        if region not in weights:
            raise ValueError(f'Region {region} is not in the region registry')
        return [region]

    current_time = _utc_now(now)
    eligible = []
    for region_id in ordered_ids:
        entry = status_regions.get(region_id, {})
        if not isinstance(entry, dict):
            raise ValueError(f'Invalid status entry for {region_id}: expected an object')

        successful_check = _timestamp(entry.get('last_successful_check_utc'))
        last_check = entry.get('last_check')
        last_check_was_dry_run = isinstance(last_check, dict) and last_check.get('dry_run') is True
        if not last_check_was_dry_run and successful_check is not None and successful_check <= current_time:
            if current_time - successful_check < _CHECK_INTERVAL:
                continue

        last_attempt = _timestamp(entry.get('last_attempt_utc'))
        if entry.get('last_attempt_outcome') in ('failure', 'started') and last_attempt is not None and last_attempt <= current_time:
            if current_time - last_attempt < _FAILURE_BACKOFF:
                continue

        published = bool(entry.get('last_published_version'))
        never_checked = last_check_was_dry_run or successful_check is None or successful_check > current_time
        priority = 0 if published else (1 if never_checked else 2)
        oldest_attempt = last_attempt or datetime.datetime.min.replace(tzinfo=UTC)
        eligible.append((priority, oldest_attempt, region_id))

    eligible.sort()
    selected = []
    spent = 0
    for _, _, region_id in eligible:
        weight = weights[region_id]
        if spent + weight > budget:
            if not selected:
                # Permit one oversized region so weight-three regions can run alone.
                selected.append(region_id)
            break
        selected.append(region_id)
        spent += weight
    return selected


def record_attempt(status: dict, region: str, *, outcome: str,
                   now: datetime.datetime | None = None,
                   run_url: str | None = None) -> dict:
    """Record an attempt without changing success history.

    ``started`` marks work begun before network/build steps; if its runner times out,
    scheduled selection applies the same six-hour retry backoff as a failure.
    """
    if not isinstance(region, str) or not _REGION_ID.fullmatch(region):
        raise ValueError('region must be a us-xx identifier')
    if outcome not in ('started', 'success', 'dry_run', 'failure'):
        raise ValueError('outcome must be started, success, dry_run, or failure')
    if run_url is not None and not isinstance(run_url, str):
        raise ValueError('run_url must be a string when provided')
    current_time = _utc_now(now)
    regions = _status_regions(status)
    entry = regions.get(region, {})
    if not isinstance(entry, dict):
        raise ValueError(f'Invalid status entry for {region}: expected an object')
    entry = copy.deepcopy(entry)
    entry['last_attempt_utc'] = current_time.isoformat()
    entry['last_attempt_outcome'] = outcome
    if run_url:
        entry['last_run_url'] = run_url
    else:
        entry.pop('last_run_url', None)
    regions[region] = entry
    return {'schema': 2, 'regions': regions}


def _read_json(path, description):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except OSError as exc:
        raise ValueError(f'Could not read {description} {path}: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON in {description} {path}: {exc}') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', default='due', help='due, all, or a specific us-xx region ID')
    parser.add_argument('--status', default='publication-status.json')
    parser.add_argument('--config', default='regions.json')
    parser.add_argument('--budget', type=int, default=3)
    parser.add_argument('--github-output', metavar='PATH', help='append regions=<JSON array> to this file')
    args = parser.parse_args(argv)
    try:
        config = _read_json(args.config, 'region config')
        try:
            status = _read_json(args.status, 'publication status')
        except ValueError as exc:
            if not Path(args.status).exists():
                status = {'schema': 2, 'regions': {}}
            else:
                raise exc
        selected = select_regions(config, status, region=args.region, budget=args.budget)
        rendered = json.dumps(selected, separators=(',', ':'))
        print(json.dumps(selected))
        if args.github_output:
            with open(args.github_output, 'a', encoding='utf-8') as handle:
                handle.write(f'regions={rendered}\n')
    except (ValueError, OSError) as exc:
        print(f'publication scheduler: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
