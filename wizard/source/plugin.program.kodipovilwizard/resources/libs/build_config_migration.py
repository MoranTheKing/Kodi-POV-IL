"""Conservative settings merge for a future modular-build migration.

This module is deliberately not wired into the current quick-update path.
The modular candidate's two-way merge pushes build values over every user
setting except a fixed credential list.  An existing build can instead use
its previously shipped defaults as a baseline: only values still equal to
that baseline may receive the new default.  User changes and credentials
stay put.  Favourites and SQLite databases need separate migration rules.
"""

from __future__ import annotations

from copy import deepcopy
from xml.etree import ElementTree as ET


def _settings(text: str, label: str) -> ET.Element:
    if not text:
        raise ValueError(label + " settings.xml is empty")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(label + " settings.xml is malformed") from exc
    if root.tag != "settings":
        raise ValueError(label + " root is not <settings>")
    seen = set()
    for setting in root.findall("setting"):
        ident = setting.get("id")
        if not ident or ident in seen:
            raise ValueError(label + " has a missing or duplicate setting id")
        seen.add(ident)
    return root


def _value(setting: ET.Element) -> tuple:
    # Kodi's addon_data/settings.xml stores values as element text.  Keep the
    # uncommon nested form distinct so we never mistake it for a matching
    # baseline and overwrite a user's value.
    return (setting.text or "", tuple(ET.tostring(child, encoding="unicode")
                                      for child in setting))


def merge_settings_xml(old_defaults: str, installed: str, new_defaults: str,
                       protected_ids) -> tuple[str, dict]:
    """Return (merged XML, counts) without writing to the Kodi profile.

    A missing or malformed input refuses migration.  Settings only in the
    user's file stay untouched.  The caller must explicitly supply its
    credential/account ID policy.  An incoming setting is adopted only when the
    installed value still matches a known old build default; unknown values
    are treated as user-owned.  Explicitly protected IDs are never touched.
    """
    old_root = _settings(old_defaults, "old build")
    user_root = _settings(installed, "installed")
    new_root = _settings(new_defaults, "new build")
    old_by_id = {item.get("id"): item for item in old_root.findall("setting")}
    user_by_id = {item.get("id"): item for item in user_root.findall("setting")}
    protected = set(protected_ids)
    counts = {"updated": 0, "added": 0, "unchanged": 0,
              "preserved": 0, "protected": 0}

    for incoming in new_root.findall("setting"):
        ident = incoming.get("id")
        if ident in protected:
            counts["protected"] += 1
            continue
        current = user_by_id.get(ident)
        if current is None:
            copy = deepcopy(incoming)
            user_root.append(copy)
            user_by_id[ident] = copy
            counts["added"] += 1
            continue
        if _value(current) == _value(incoming):
            counts["unchanged"] += 1
            continue
        previous = old_by_id.get(ident)
        if previous is None or _value(current) != _value(previous):
            counts["preserved"] += 1
            continue
        children = list(user_root)
        position = children.index(current)
        copy = deepcopy(incoming)
        user_root.remove(current)
        user_root.insert(position, copy)
        user_by_id[ident] = copy
        counts["updated"] += 1

    return ET.tostring(user_root, encoding="unicode"), counts
