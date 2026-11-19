"""The records the build's device-to-device sync keeps (Wizard, cloud_sync): what a viewer has in POV and
Umbrella's own local lists -- favourites, dropped shows, watched marks, the places to continue from -- as one
map of records that every device of that viewer merges.

The owner, Nov 2026: "sync between devices from anywhere in the world, of series and films (lists and continue
watching), without fiddling with Trakt or MDBList". Kept in the viewer's own Google Drive (one file the build made,
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
            out[key] = {'v': value, 't': changed_at(key, value, rec, now)}
    for key, rec in base.items():
        if key in out:
            continue
        out[key] = rec if rec.get('d') or not mine(key) else {'t': now, 'd': 1}
    return out


TIMED = ('.watched.', '.progress.')


def row_time(value, now):
    """When a watched mark or a place was made, from its own last_played (ms); None when it has none usable."""
    import calendar
    import time
    text = value.get('last_played') if isinstance(value, dict) else None
    if not isinstance(text, str):
        return None
    text = text.strip()
    for pattern, utc in (('%Y-%m-%d %H:%M:%S', False), ('%Y-%m-%dT%H:%M:%S.%fZ', True), ('%Y-%m-%dT%H:%M:%SZ', True)):
        try:
            parsed = time.strptime(text[:26] if utc else text[:19], pattern)
        except ValueError:
            continue
        seconds = calendar.timegm(parsed) if utc else time.mktime(parsed)
        return min(int(seconds * 1000), now)
    return None


def changed_at(key, value, before, now):
    """The time of a changed record. A watched mark or a place carries the time it was made (the reviewer, 0.5.24:
    a place a TV noticed only at its next start -- it was switched off right after the film -- must not beat the newer
    place the viewer reached on another device meanwhile); never earlier than the record it replaces."""
    t = now
    if any(part in key for part in TIMED):
        made = row_time(value, now)
        if made is not None:
            t = made
    if before is not None and t <= before['t']:
        t = before['t'] + 1
    return t


GUARD_MIN = 10          # a list must lose at least this many ...
GUARD_SHARE = 0.5       # ... and more than this share of what it held, at once, to look reset


def list_of(key):
    return '.'.join(key.split('.')[:2])         # 'pov.fav', 'umb.progress' ...


def hold_resets(base, local):
    """A list that lost most of what it held at once (an add-on reinstalled, its data cleared, a fresh install) did
    not have all of it removed by the viewer: its removals are held back -- the device is filled again from the other
    devices instead (the reviewer, 0.5.24: "a device that loses its list wipes it on every device"). Returns the
    records without those removals, and {list: how many were held}."""
    alive, gone = {}, {}
    for key, rec in base.items():
        if not rec.get('d'):
            name = list_of(key)
            alive[name] = alive.get(name, 0) + 1
            now = local.get(key)
            if now is not None and now.get('d'):
                gone.setdefault(name, []).append(key)
    held = {name: keys for name, keys in gone.items() if len(keys) >= GUARD_MIN and len(keys) > GUARD_SHARE * alive[name]}
    if not held:
        return local, {}
    out = dict(local)
    for keys in held.values():
        for key in keys:
            out[key] = base[key]
    return out, {name: len(keys) for name, keys in held.items()}


def first_connect(local, remote):
    """A device's first round (it has no base): where its favourites or dropped shows differ from what the other
    devices already keep, theirs stand (its own rows are not newer for being noticed now); what they lack is added."""
    out = dict(local)
    for key, rec in local.items():
        if key in remote and not any(part in key for part in TIMED):
            out[key] = dict(rec, t=1)
    return out


def from_the_future(records, now, slack_ms=86400 * 1000):
    """Records stamped more than a day ahead of this device's clock (a box whose clock runs far ahead would win every
    conflict): taken as made now. Returns the records and how many were changed."""
    out, fixed = {}, 0
    for key, rec in records.items():
        if rec['t'] > now + slack_ms:
            rec, fixed = dict(rec, t=now), fixed + 1
        out[key] = rec
    return out, fixed


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
