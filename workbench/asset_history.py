"""Observed additions, never backdate existing assets using file timestamps."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

CN = timezone(timedelta(hours=8))


def week_key(at):
    day = datetime.fromisoformat(at).astimezone(CN).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def identity(row):
    return {k: row.get(k, '') for k in ('assetId', 'id', 'title', 'product', 'feature', 'suiteTier', 'admission')}


def advance(state, previous, snapshot):
    at = snapshot['scannedAt']
    current = {r['assetId']: r for r in snapshot['cases']}
    initial = not state
    state = deepcopy(state) if state else {
        'baselineAt': at, 'baselineCount': len(current), 'seen': list(current), 'weeks': {}}
    week = state['weeks'].setdefault(week_key(at), {
        'firstObservedAt': at, 'lastObservedAt': at, 'added': [], 'removed': [], 'restored': []})
    week['lastObservedAt'] = at
    week['observedProducts'] = sorted(set(week.get('observedProducts', [])) | {
        s['product'] for s in snapshot['sources'] if s['status'] == 'connected'})
    day = datetime.fromisoformat(at).astimezone(CN).date().isoformat()
    observations = week.setdefault('observations', {})
    observation = observations.setdefault(day, {'at': at, 'products': []})
    observation['at'] = at
    observation['products'] = sorted(set(observation['products']) | {
        s['product'] for s in snapshot['sources'] if s['status'] == 'connected'})
    if not initial:
        old = {r['assetId']: r for r in previous.get('cases', [])}
        seen = set(state['seen'])
        # An unavailable source is not evidence that its cases were deleted.
        connected = {s['product'] for s in snapshot['sources'] if s['status'] == 'connected'}
        previous_connected = {s['product'] for s in previous.get('sources', []) if s['status'] == 'connected'}
        for key in current.keys() - old.keys():
            row = identity(current[key]) | {'observedAt': at}
            week['restored' if key in seen else 'added'].append(row)
            seen.add(key)
        for key in old.keys() - current.keys():
            if old[key]['product'] in connected & previous_connected:
                week['removed'].append(identity(old[key]) | {'observedAt': at})
        state['seen'] = sorted(seen)
    week['total'] = len(current)
    return state


def public_history(state):
    if not state:
        return None
    return {'baselineAt': state['baselineAt'], 'baselineCount': state['baselineCount'],
            'weeks': [{'week': key, **value} for key, value in sorted(state['weeks'].items(), reverse=True)]}
