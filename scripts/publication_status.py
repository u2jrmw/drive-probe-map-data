"""Helpers for preserving per-region map publication check history."""
import copy
import datetime
import re


def _time(value, label):
    if not isinstance(value, str):
        raise ValueError(f'Missing {label} timestamp')
    try:
        parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'Invalid {label} timestamp') from exc
    if parsed.tzinfo is None:
        raise ValueError(f'{label} timestamp needs a timezone')
    return parsed.astimezone(datetime.timezone.utc)


def _regions_from(status):
    if not isinstance(status, dict):
        raise ValueError('Publication status must be an object')
    schema = status.get('schema')
    if schema == 2:
        regions = status.get('regions')
        if not isinstance(regions, dict):
            raise ValueError('Schema-2 publication status needs a regions object')
        return copy.deepcopy(regions)
    if schema in (None, 1):
        region = status.get('region')
        if region is None:
            return {}
        if not isinstance(region, str) or not re.fullmatch(r'us-[a-z]{2}', region):
            raise ValueError('Legacy publication status has an invalid region')
        return {region: {key: copy.deepcopy(value) for key, value in status.items()
                         if key not in ('schema', 'region')}}
    raise ValueError(f'Unsupported publication status schema: {schema}')


def update_status(status, report, *, dry_run):
    """Return schema-2 status updated for one region, preserving all other regions."""
    if not isinstance(dry_run, bool):
        raise ValueError('dry_run must be a boolean')
    if not isinstance(report, dict):
        raise ValueError('Publication report must be an object')
    region = report.get('region')
    if not isinstance(region, str) or not re.fullmatch(r'us-[a-z]{2}', region):
        raise ValueError('Publication report region must be a us-xx identifier')
    checked_utc = report.get('checked_utc')
    checked_time = _time(checked_utc, 'checked_utc')
    source_data_utc = report.get('source_data_utc')
    _time(source_data_utc, 'source_data_utc')
    regions = _regions_from(status)
    current = regions.get(region, {})
    if not isinstance(current, dict):
        raise ValueError(f'Invalid status entry for {region}')
    previous_check = current.get('last_successful_check_utc')
    if previous_check is not None and checked_time < _time(previous_check, 'previous checked_utc'):
        raise ValueError(f'Check timestamp would move {region} status backward')

    current = copy.deepcopy(current)
    current['last_successful_check_utc'] = checked_utc
    current['source_data_utc'] = source_data_utc
    current['last_check'] = {
        key: copy.deepcopy(report[key])
        for key in ('checked_utc', 'source_data_utc', 'changed', 'reused', 'removed',
                    'full_bytes', 'upload_bytes', 'duration_seconds', 'no_changes', 'published')
        if key in report
    }
    current['last_check']['version'] = report.get('version')
    current['last_check']['dry_run'] = dry_run
    if report.get('published') is True and not dry_run and report.get('no_changes') is not True:
        current['last_successful_publication_utc'] = checked_utc
        if report.get('version'):
            current['last_published_version'] = report['version']
    regions[region] = current
    return {'schema': 2, 'regions': regions}
