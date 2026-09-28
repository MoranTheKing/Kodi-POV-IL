"""Conservative, offline three-way merge for a future Kodi build migration.

The current modular updater replaces favourites.xml wholesale.  Existing
users may have reordered, edited, removed, or added favourites.  Compare
against the old build's shipped file so only untouched build entries receive
new defaults.  This function never opens or writes the Kodi profile.
"""

from copy import deepcopy
from xml.etree import ElementTree as ET


def _read(text, label):
    if not text:
        raise ValueError(label + ' favourites.xml is empty')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(label + ' favourites.xml is malformed') from exc
    if root.tag != 'favourites' or root.attrib:
        raise ValueError(label + ' must have a plain <favourites> root')
    by_name = {}
    for item in root:
        name = item.get('name')
        if (item.tag != 'favourite' or not name or not (item.text or '').strip()
                or len(item) or name in by_name):
            raise ValueError(label + ' contains an ambiguous favourite')
        by_name[name] = item
    return root, by_name


def _content(item):
    return dict(item.attrib), (item.text or '').strip()


def merge_favourites_xml(old_defaults, installed, new_defaults):
    """Return (merged XML, counts), preserving user-owned entries and order.

    An untouched old build item is replaced in its current position.  If a
    user edited or deleted an old item, that decision stays.  New build items
    append after the existing list.  Old-only build items remain, so a
    migration cannot silently delete navigation; callers must separately
    audit whether their action and icon still work in the new build.
    """
    old_root, old = _read(old_defaults, 'old build')
    user_root, user = _read(installed, 'installed')
    new_root, new = _read(new_defaults, 'new build')
    del old_root, new_root
    counts = {'updated': 0, 'added': 0, 'unchanged': 0,
              'user_preserved': 0, 'user_deleted': 0,
              'old_only_retained': 0}
    changed = False

    for name, incoming in new.items():
        current = user.get(name)
        previous = old.get(name)
        if current is None:
            if previous is not None:
                counts['user_deleted'] += 1
                continue
            user_root.append(deepcopy(incoming))
            user[name] = user_root[-1]
            counts['added'] += 1
            changed = True
            continue
        if _content(current) == _content(incoming):
            counts['unchanged'] += 1
            continue
        if previous is None or _content(current) != _content(previous):
            counts['user_preserved'] += 1
            continue
        siblings = list(user_root)
        position = siblings.index(current)
        replacement = deepcopy(incoming)
        user_root.remove(current)
        user_root.insert(position, replacement)
        user[name] = replacement
        counts['updated'] += 1
        changed = True

    counts['old_only_retained'] = sum(name in user for name in old.keys() - new.keys())
    return (ET.tostring(user_root, encoding='unicode') if changed else installed,
            counts)
