# -*- coding: utf-8 -*-
# Dynamic, JSON-driven favourites generator for the Kodi POV IL build.
#
# Builds each skin's defaults from resources/favourites_config.json, then
# three-way merges against the last generated defaults. Kodi user edits remain
# authoritative, including order, icon/action edits, additions and deletions.
#
# Public API:
#   generate_favourites_xml(skin_id, merge=True, write=True) -> str (the XML)
#
# The config defines a dictionary of named tiles plus, per skin, an ordered list
# of tile keys (or an 'inherit' of another skin) and optional per-tile overrides
# (icon/action/name). A tile 'icon' is either a bare filename (joined with the
# config's icon_base, e.g. special://home/media/povil_icons/<file> -- the global
# media folder that media_installer.py deploys/overwrites the icons into) or a
# full special:// / http(s) path used verbatim.
#
# Designed to be import-safe outside Kodi (xbmc* are optional) so it can be unit
# tested, and to be loaded cross-addon by the wizard's skin switcher.

import json
import os
import re
import tempfile
import sqlite3
import uuid
from contextlib import closing, contextmanager
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree as ET

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    import xbmc
except Exception:
    xbmc = None

try:
    import xbmcgui
except Exception:
    xbmcgui = None


FAVOURITES_PATH = 'special://profile/favourites.xml'
STATE_PATH = ('special://profile/addon_data/'
              'plugin.program.orderfavourites-hebrew/favourites_state.json')
DEFAULT_SKIN_KEY = 'default'

def _log(msg, error=False):
    if xbmc is None:
        return
    try:
        level = xbmc.LOGERROR if error else xbmc.LOGINFO
        xbmc.log('[orderfavourites favourites_generator] ' + msg, level)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config & Conditionals
# ---------------------------------------------------------------------------
def _config_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'resources', 'favourites_config.json')


def _load_config(config_path=None):
    path = config_path or _config_path()
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


_VIS_MGR = None


def _vis_mgr():
    """Lazy, cross-addon import of the wizard's Dynamic Visibility Manager."""
    global _VIS_MGR
    if _VIS_MGR is None:
        try:
            import sys
            p = xbmcvfs.translatePath(
                'special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')
            if p not in sys.path:
                sys.path.append(p)
            import pov_visibility_mgr
            _VIS_MGR = pov_visibility_mgr
        except Exception as e:
            _log('visibility manager unavailable: {0}'.format(e), error=True)
            _VIS_MGR = False
    return _VIS_MGR or None


def _check_condition(tile_def):
    """A tile with a "condition" ("trakt" | "tmdb" | "mdblist" | "umbrella", or a
    list of them) is emitted only when every named service is active."""
    cond = tile_def.get('condition')
    if not cond:
        return True
    mgr = _vis_mgr()
    if mgr is None:
        return False  # fail closed: hide gated tiles rather than ship dead ones
    names = cond if isinstance(cond, (list, tuple)) else [cond]
    return all(mgr.is_service_active(n) for n in names)


def _resolve_skin(config, skin_id):
    """Return the resolved skin entry {'order': [...], 'overrides': {...}} for
    skin_id, following any 'inherit' chain. Falls back to DEFAULT_SKIN_KEY when
    the skin is unknown (so a brand-new/other skin still gets the full set)."""
    skins = config.get('skins', {}) or {}
    entry = skins.get(skin_id)
    if entry is None:
        entry = skins.get(DEFAULT_SKIN_KEY, {})
    seen = set()
    # Walk inherit links, letting the child's own keys win over the parent's.
    while isinstance(entry, dict) and entry.get('inherit') and entry['inherit'] not in seen:
        parent_key = entry['inherit']
        seen.add(parent_key)
        parent = skins.get(parent_key)
        if not isinstance(parent, dict):
            break
        merged = dict(parent)
        for k, v in entry.items():
            if k != 'inherit':
                merged[k] = v
        entry = merged
    return entry or {}


# ---------------------------------------------------------------------------
# XML building
# ---------------------------------------------------------------------------
def _xml_escape_text(value):
    # Element body: escape &, <, > (a literal " is legal in element text).
    return (value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _xml_escape_attr(value):
    # Double-quoted attribute: escape &, <, >, ".
    return (value.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _thumb_for(config, icon):
    if not icon:
        return ''
    if icon.startswith('special://') or icon.startswith('http://') or icon.startswith('https://'):
        return icon
    return config.get('icon_base', '') + icon


def _tile_xml(config, key, overrides):
    base = (config.get('tiles', {}) or {}).get(key)
    if not base:
        _log('unknown tile key "{0}" -- skipped'.format(key))
        return None

    if not _check_condition(base):
        return None

    name = base.get('name', '')
    icon = base.get('icon', '')
    action = base.get('action', '')
    ov = (overrides or {}).get(key)
    if ov:
        name = ov.get('name', name)
        icon = ov.get('icon', icon)
        action = ov.get('action', action)
    thumb = _thumb_for(config, icon)
    return '    <favourite name="{0}" thumb="{1}">{2}</favourite>'.format(
        _xml_escape_attr(name), _xml_escape_attr(thumb), _xml_escape_text(action))


# ---------------------------------------------------------------------------
# Existing-file merge (preserve user choices)
# ---------------------------------------------------------------------------
def _read_existing():
    if xbmcvfs is None:
        return None
    try:
        if not xbmcvfs.exists(FAVOURITES_PATH):
            return None
        fh = xbmcvfs.File(FAVOURITES_PATH)
        try:
            data = fh.read()
        finally:
            fh.close()
        return data or ''
    except Exception as e:
        _log('could not read existing favourites: {0}'.format(e))
        return ''


def _state_file():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(STATE_PATH)
    except Exception:
        return None


def _load_state():
    baseline, deleted, _ = _load_state_details()
    return baseline, deleted


def _load_state_details():
    path = _state_file()
    if path and os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                state = json.load(fh)
            if state.get('version') == 1 and isinstance(state.get('baseline'), str):
                identities = state.get('identities', {})
                if not isinstance(identities, dict):
                    identities = {}
                return state['baseline'], set(state.get('deleted', [])), identities
        except (OSError, ValueError, TypeError) as exc:
            _log('could not read favourites state: {0}'.format(exc), error=True)
    return None, set(), {}


def _save_state(baseline, deleted, identities=None):
    path = _state_file()
    if not path:
        return False
    tmp = None
    try:
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.favourites-', dir=folder)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump({'version': 1, 'layout_version': 4, 'baseline': baseline,
                       'deleted': sorted(deleted), 'identities': identities or {}},
                      fh, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except (OSError, ValueError) as exc:
        _log('could not save favourites state: {0}'.format(exc), error=True)
        return False
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def seed_previous_defaults(xml):
    """One-time migration hook for the old build's per-skin favourites seed.

    The old build installed its canonical XML under media/builds_favourites_xml.
    Supplying that exact baseline lets the first modular refresh distinguish
    old build defaults from a user's edits. Never replace an existing state.
    """
    path = _state_file()
    if not path or os.path.exists(path):
        return False
    try:
        _parse_favourites(xml, 'legacy default')
    except ValueError as exc:
        _log('legacy baseline rejected: {0}'.format(exc), error=True)
        return False
    return _save_state(xml, set())


def _parse_favourites(xml, label):
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError) as exc:
        raise ValueError('{0} favourites.xml is malformed'.format(label)) from exc
    if root.tag != 'favourites':
        raise ValueError('{0} favourites.xml has an unexpected root'.format(label))
    by_name = {}
    for item in root:
        name = item.get('name')
        if (item.tag != 'favourite' or not name or not (item.text or '').strip()
                or len(item) or name in by_name):
            raise ValueError('{0} favourites.xml is ambiguous'.format(label))
        by_name[name] = item
    return root, by_name


def _same_favourite(left, right):
    return (left.attrib == right.attrib
            and (left.text or '').strip() == (right.text or '').strip())


def _layout_version():
    try:
        with open(_state_file(), 'r', encoding='utf-8') as fh:
            return int(json.load(fh).get('layout_version', 1))
    except (OSError, ValueError, TypeError):
        return 1


def _mdbl_personal(item):
    return 'action=mdblist_my_' in (item.text or '')


def _repair_mdbl_personal(item, desired_by_name):
    """Upgrade known build shortcuts even when the old baseline was lost.

    Earlier installs retained watchlist-only actions as user edits after a
    baseline refresh. The old URL also has a separate Kodi directory cache.
    Use the same full-library URL as the skin menus. Match only the two build
    labels and unfiltered default parameters; custom watchlists stay intact.
    Keep the user's position and thumbnail, and never create a deleted tile.
    """
    name = item.get('name')
    if name not in ('[B]הסרטים שלי (MDBList)[/B]', '[B]הסדרות שלי (MDBList)[/B]'):
        return
    desired = desired_by_name.get(name)
    if desired is None:
        return
    match = re.fullmatch(r'ActivateWindow\(10025,"([^"]+)",return\)',
                         (item.text or '').strip())
    if not match:
        return
    url = urlsplit(match.group(1))
    if (url.scheme != 'plugin' or url.netloc != 'plugin.video.pov'
            or url.path != '/' or url.fragment):
        return
    pairs = parse_qsl(url.query, keep_blank_values=True)
    params = dict(pairs)
    if len(params) != len(pairs) or set(params) - {'action', 'mode', 'name', 'iconImage'}:
        return
    shows = name == '[B]הסדרות שלי (MDBList)[/B]'
    action = 'mdblist_my_tvshows' if shows else 'mdblist_my_movies'
    mode = 'build_tvshow_list' if shows else 'build_movie_list'
    icon = ('special://home/addons/plugin.video.pov/resources/skins/'
            'Default/media/mdblist.png')
    if (params.get('action') not in ('mdblist_watchlist', action)
            or params.get('mode') != mode
            or params.get('name') not in ('MDBList', 'MDBList Watchlist')
            or ('iconImage' in params and params['iconImage'] != icon)):
        return
    item.text = desired.text


def _insert_personal(root, item, desired_root):
    """Anchor a new service tile without sorting any existing user tiles."""
    preceding = list(desired_root)[:list(desired_root).index(item)]
    for anchor in reversed(preceding):
        for existing in root:
            if existing.get('name') == anchor.get('name'):
                root.insert(list(root).index(existing) + 1,
                            ET.fromstring(ET.tostring(item)))
                return
    root.append(ET.fromstring(ET.tostring(item)))


def _action_identity(action):
    # Presentation parameters can change with translations and thumbnail fixes.
    # Keep filters, IDs and routing parameters: custom destinations stay custom.
    return re.sub(r'plugin://[^"\s)]+', lambda match: _url_identity(match.group()),
                  (action or '').strip())


def _url_identity(url):
    parsed = urlsplit(url)
    pairs = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key not in ('name', 'iconImage')]
    return repr((parsed.scheme, parsed.netloc, parsed.path, sorted(pairs), parsed.fragment))


def _tile_identities(config, xmls, recorded=None):
    """Match known build tiles across label changes without changing Kodi XML."""
    names, actions = {}, {}
    for key, tile in config.get('tiles', {}).items():
        variants = [tile]
        for skin in config.get('skins', {}).values():
            override = skin.get('overrides', {}).get(key)
            if override:
                variants.append(dict(tile, **override))
        for variant in variants:
            identity = 'povil.tile:' + key
            names[variant.get('name')] = identity
            fingerprint = _action_identity(variant.get('action'))
            actions.setdefault(fingerprint, set()).add(identity)
    names['[B]סדרות חדשים[/B]'] = 'povil.tile:shows_new'
    names.update({name: key for name, key in (recorded or {}).items()
                  if isinstance(name, str) and isinstance(key, str)
                  and key.startswith('povil.tile:')})
    for xml in xmls:
        if xml is None:
            continue
        _, rows = _parse_favourites(xml, 'identity')
        for name, item in rows.items():
            candidates = actions.get(_action_identity(item.text), set())
            if name not in names and len(candidates) == 1:
                names[name] = next(iter(candidates))
    return names


def _merge_favourites(existing, previous, desired, deleted, repair_tail=False, identities=None):
    """Three-way merge: preserve user order, edits, additions and deletions.

    `previous` is the last generated *default*, even if the installed file
    was edited later. A service-gated default that disappears is removed only
    when it is still untouched. Explicit user deletions survive reconnection.
    """
    desired_root, desired_by_name = _parse_favourites(desired, 'new default')
    if existing is None:
        return desired, set()
    user_root, user_by_name = _parse_favourites(existing, 'installed')
    if previous is None:
        old_by_name = {}
    else:
        _, old_by_name = _parse_favourites(previous, 'previous default')
    deleted = set(deleted)
    identities = identities or {}
    current_ids = {identities.get(name, name) for name in user_by_name}
    desired_by_id = {identities.get(name, name): item for name, item in desired_by_name.items()}
    # Convert old label tombstones before an update renames the same build tile.
    deleted.update(identities[name] for name in tuple(deleted) if name in identities)
    for name in old_by_name:
        identity = identities.get(name, name)
        if identity not in current_ids:
            deleted.add(name)
            deleted.add(identity)
    # An explicit re-add (including a renamed tile) reverses its own deletion.
    deleted = {name for name in deleted if identities.get(name, name) not in current_ids}
    for item in list(user_root):
        name = item.get('name')
        old = old_by_name.get(name)
        if old is None or not _same_favourite(item, old):
            continue
        replacement = desired_by_id.get(identities.get(name, name))
        index = list(user_root).index(item)
        user_root.remove(item)
        if replacement is not None:
            user_root.insert(index, ET.fromstring(ET.tostring(replacement)))
    for item in user_root:
        _repair_mdbl_personal(item, desired_by_name)
    if repair_tail:
        # The previous generator appended newly connected MDBList tiles.
        # Repair only that untouched trailing block, once; leave edited tiles,
        # deliberate non-tail positions and other favourites where they are.
        trailing = []
        for item in reversed(list(user_root)):
            name = item.get('name')
            old = old_by_name.get(name)
            if (not _mdbl_personal(item) or old is None
                    or not _same_favourite(item, old)):
                break
            trailing.append(item)
        for item in trailing:
            user_root.remove(item)
    current_names = {item.get('name') for item in user_root}
    current_ids = {identities.get(name, name) for name in current_names}
    for item in desired_root:
        name = item.get('name')
        identity = identities.get(name, name)
        if identity not in current_ids and name not in deleted and identity not in deleted:
            if _mdbl_personal(item) and previous is not None:
                _insert_personal(user_root, item, desired_root)
            else:
                user_root.append(ET.fromstring(ET.tostring(item)))
            current_names.add(name)
            current_ids.add(identity)
    return ET.tostring(user_root, encoding='unicode'), deleted


def _write_favourites(text):
    if xbmcvfs is None:
        _log('xbmcvfs unavailable -- not writing favourites', error=True)
        return False
    tmp = None
    try:
        path = xbmcvfs.translatePath(FAVOURITES_PATH)
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.favourites-', dir=folder)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except Exception as e:
        _log('write failed: {0}'.format(e), error=True)
        return False
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
@contextmanager
def _refresh_lock():
    """Serialize the XML and baseline pair across Kodi script interpreters."""
    path = _state_file()
    if not path:
        raise OSError('Favourites state path unavailable')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    window = None
    token = uuid.uuid4().hex
    with closing(sqlite3.connect(path + '.lock.db', timeout=3)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            if xbmcgui is not None:
                window = xbmcgui.Window(10000)
                window.setProperty('POVIL.FavouritesRefresh', token)
            yield
        finally:
            if window is not None and window.getProperty('POVIL.FavouritesRefresh') == token:
                window.clearProperty('POVIL.FavouritesRefresh')
            conn.rollback()


def generate_favourites_xml(skin_id, merge=True, write=True, config_path=None):
    if not write:
        return _generate_favourites_xml(skin_id, merge, write, config_path)
    try:
        with _refresh_lock():
            return _generate_favourites_xml(skin_id, merge, write, config_path)
    except (OSError, sqlite3.Error) as exc:
        _log('favourites refresh deferred: ' + type(exc).__name__, error=True)
        return None


def _generate_favourites_xml(skin_id, merge=True, write=True, config_path=None):
    """Build favourites.xml for skin_id from favourites_config.json.

    merge=True preserves user order, edits, additions and deletions by
    comparing against the last generated defaults. New defaults are appended.
    write=True writes the result to special://profile/favourites.xml.
    Returns the XML string on success, or None when the installed file was
    invalid or the requested write failed. A rejected write leaves it intact.
    """
    config = _load_config(config_path)
    skin_cfg = _resolve_skin(config, skin_id)
    order = skin_cfg.get('order')
    if not order:
        order = (config.get('skins', {}).get(DEFAULT_SKIN_KEY, {}) or {}).get('order', [])
    overrides = skin_cfg.get('overrides', {})

    lines = []
    for key in order:
        tile = _tile_xml(config, key, overrides)
        if tile:
            lines.append(tile)

    desired = '<favourites>\n' + '\n'.join(lines) + '\n</favourites>\n'
    xml = desired
    deleted = set()
    previous = None
    previous_deleted = set()
    existing = None
    identities = {}
    if merge:
        previous, previous_deleted, recorded = _load_state_details()
        layout_version = _layout_version()
        existing = _read_existing()
        try:
            identities = _tile_identities(config, (previous, existing, desired), recorded)
            xml, deleted = _merge_favourites(
                existing, previous, desired, previous_deleted,
                repair_tail=layout_version < 2, identities=identities)
        except ValueError as exc:
            _log('leaving existing favourites untouched: {0}'.format(exc), error=True)
            return None

    if write:
        if existing == xml:
            if previous != desired or previous_deleted != deleted or _layout_version() < 4:
                if not _save_state(desired, deleted, identities):
                    return None
            return xml
        if _write_favourites(xml):
            if not _save_state(desired, deleted, identities):
                _log('favourites written but baseline state was not saved', error=True)
            _log('wrote {0} favourite(s) for skin "{1}"'.format(len(lines), skin_id))
        else:
            _log('failed to write favourites for skin "{0}"'.format(skin_id), error=True)
            return None
    return xml
