"""Recover a normal add-on update interrupted after addon.xml was written.

The classic extractor writes directly into the installed add-on.  Its version
can therefore advance before its remaining files do.  A small pending record
forces the next startup to retry that exact update even when versions match.
"""

import json
import os
import re
import zipfile


_ID = re.compile(r'^[a-z][a-z0-9_.-]{1,100}$', re.I)


def _path(data_dir, addon_id):
    if not isinstance(addon_id, str) or not _ID.fullmatch(addon_id):
        raise ValueError('invalid addon id')
    return os.path.join(data_dir, 'ota-pending', addon_id + '.json')


def needs_retry(data_dir, addon_id):
    path = _path(data_dir, addon_id)
    try:
        if os.path.getsize(path) > 1024:
            return False
        with open(path, encoding='utf-8') as source:
            record = json.load(source)
        return record.get('schema') == 1 and record.get('addon_id') == addon_id
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def pending_addons(data_dir):
    directory = os.path.join(data_dir, 'ota-pending')
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    result = []
    for name in names:
        if not name.endswith('.json'):
            continue
        addon_id = name[:-5]
        try:
            if needs_retry(data_dir, addon_id):
                result.append(addon_id)
        except ValueError:
            continue
    return sorted(result)


def begin(data_dir, addon_id, version, sha256):
    path = _path(data_dir, addon_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as output:
        json.dump({'schema': 1, 'addon_id': addon_id,
                   'version': str(version), 'sha256': str(sha256)}, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def verify(package, addons_dir, addon_id, version):
    """Check all package files after extraction; immutable tool files bytewise."""
    target = os.path.join(addons_dir, addon_id)
    strict = addon_id == 'plugin.program.orderfavourites-hebrew'
    checked = 0
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            parts = info.filename.split('/')
            if (len(parts) < 2 or parts[0] != addon_id or
                    any(part in ('', '.', '..') for part in parts[1:-1]) or
                    '\\' in info.filename or ':' in info.filename):
                raise ValueError('unexpected add-on ZIP member')
            if info.is_dir():
                continue
            if not parts[-1]:
                raise ValueError('empty add-on ZIP member')
            actual = os.path.realpath(os.path.join(addons_dir, *parts))
            if os.path.commonpath((os.path.realpath(target), actual)) != os.path.realpath(target):
                raise ValueError('add-on ZIP member escaped target')
            if not os.path.isfile(actual):
                raise IOError('installed add-on file absent: ' + info.filename)
            if strict:
                with open(actual, 'rb') as installed:
                    if installed.read() != archive.read(info):
                        raise IOError('installed add-on file differs: ' + info.filename)
            checked += 1
    if not checked:
        raise ValueError('empty add-on ZIP')
    import xml.etree.ElementTree as ET
    root = ET.parse(os.path.join(target, 'addon.xml')).getroot()
    if root.get('id') != addon_id or root.get('version') != str(version):
        raise ValueError('installed add-on identity differs')
    return checked


def complete(data_dir, addon_id):
    os.remove(_path(data_dir, addon_id))
