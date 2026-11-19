"""The records the build's device-to-device sync keeps (Wizard, cloud_sync): what a viewer has in POV and
Umbrella's own local lists -- favourites, dropped shows, watched marks, the places to continue from -- as one
map of records that every device of that viewer merges.

The owner, Nov 2026: "sync between devices from anywhere in the world, of series and films (lists and continue
watching), without fiddling with Trakt or MDBList". Kept in the viewer's own Google Drive (its hidden app folder,
drive.py); none of it passes through the build's own servers.

A record: {'v': {plain values}, 't': when it last changed (ms), 'd': 1 when it was removed}. Every device keeps
the map it last saw (the base); what changed on the device since is found by comparing its lists with that base
(changes), the two maps are merged record by record -- the later change wins, a removal included (merge) -- and
what the merged map holds that the device does not is written back to it (to_apply). The result is the same on
every device whatever order they sync in.

Everything that arrives from the cloud is checked here before any of it reaches a list (clean): a record whose
key or values are not of the expected shape is dropped. (Umbrella reads its favourites back with Python's
eval(): only plain strings and numbers ever reach it, written by this build.)
"""
import json
import re

TOMBSTONE_DAYS = 120            # a removal is remembered this long, so a device that was off still learns of it
MAX_TEXT = 300                  # longest text value kept (a title, an address of a picture)
KEY = re.compile(r'^(pov|umb)\.(fav|drop|watched|progress)\.[a-z]{2,12}(\.[A-Za-z0-9_:\-]{1,40}){1,4}$')


def _plain(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value if -10 ** 15 < value < 10 ** 15 else None
    if isinstance(value, float):
        return value if value == value and abs(value) < 10 ** 15 else None
    if isinstance(value, str):
        return value[:MAX_TEXT]
    return None


NAME = re.compile(r'^[A-Za-z_]{1,24}$')


def clean_value(value, depth=0):
    """A record's values: a map of short names to plain strings and numbers, or to such a map (two levels at most:
    an Umbrella favourite's details, and their ids); anything else dropped."""
    if not isinstance(value, dict) or depth > 2:
        return None
    out = {}
    for name, item in value.items():
        if not (isinstance(name, str) and NAME.match(name)):
            continue
        item = clean_value(item, depth + 1) if isinstance(item, dict) else _plain(item)
        if item is not None:
            out[name] = item
    return out


def clean(records):
    """The records of a map read from the cloud that have the expected shape."""
    out = {}
    if not isinstance(records, dict):
        return out
    for key, rec in records.items():
        if not (isinstance(key, str) and KEY.match(key) and isinstance(rec, dict)):
            continue
        t = rec.get('t')
        if not isinstance(t, int) or isinstance(t, bool) or t <= 0:
            continue
        if rec.get('d'):
            out[key] = {'t': t, 'd': 1}
            continue
        value = clean_value(rec.get('v'))
        if value is not None:
            out[key] = {'v': value, 't': t}
    return out


def _order(rec):
    # the later change wins; at the same moment a removal wins, then the larger value (the same on every device)
    return (rec['t'], 1 if rec.get('d') else 0, json.dumps(rec.get('v'), sort_keys=True))


def merge(*maps):
    """One map from several: for every key, its latest record."""
    out = {}
    for records in maps:
        for key, rec in records.items():
            have = out.get(key)
            if have is None or _order(rec) > _order(have):
                out[key] = rec
    return out


def changes(base, values, now, mine=lambda key: True):
    """The records for what the device holds now (values: key -> plain values), given the map it last saw: a key
    that is new or whose values differ is changed now; a key the base has alive and the device no longer has is
    removed now -- only among the keys of lists this device has (mine: an add-on that is not installed here
    removes nothing); everything else keeps the record it had."""
    out = {}
    for key, value in values.items():
        rec = base.get(key)
        if rec is not None and not rec.get('d') and rec.get('v') == value:
            out[key] = rec
        else:
            out[key] = {'v': value, 't': now}
    for key, rec in base.items():
        if key in out:
            continue
        out[key] = rec if rec.get('d') or not mine(key) else {'t': now, 'd': 1}
    return out


def to_apply(merged, values, mine=lambda key: True):
    """What the device must change so its lists hold what the merged map says: (put, remove) -- put maps a key to the
    values to write, remove lists the keys to take away; only for lists this device has (mine)."""
    put = {key: rec['v'] for key, rec in merged.items() if mine(key) and not rec.get('d') and values.get(key) != rec['v']}
    remove = [key for key, rec in merged.items() if mine(key) and rec.get('d') and key in values]
    return put, remove


def forget_old(records, now):
    """The map without removals older than TOMBSTONE_DAYS."""
    limit = now - TOMBSTONE_DAYS * 86400 * 1000
    return {key: rec for key, rec in records.items() if not (rec.get('d') and rec['t'] < limit)}


def dumps(records):
    return json.dumps({'format': 1, 'records': records}, separators=(',', ':'), sort_keys=True)


def loads(text):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get('format') != 1:
        return {}
    return clean(data.get('records'))
