"""Keep helper-generated widgets consistent with the user's saved paths.

The paths database is authoritative. A one-time migration restores missing
popular defaults in an otherwise unchanged build layout. Empty/custom layouts
and existing saved paths are preserved. No provider fetch is needed.
"""
import ast
from contextlib import closing
from copy import deepcopy
import html
import hashlib
import json
import os
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import parse_qsl, urlsplit

GROUPS = {'movie': ('MovieWidgets', 19010),
          'tvshow': ('TVShowWidgets', 22010),
          'custom1': ('Custom1Widgets', 23010),
          'custom2': ('Custom2Widgets', 24010),
          'custom3': ('Custom3Widgets', 25010)}
OLD = ('            if not "&amp;" in body:\n'
       '                final_format += body.replace("&", "&amp;")')
NEW = ('            # POV IL: retain rows containing existing XML entities.\n'
       '            final_format += __import__("re").sub(\n'
       '                r"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#x[0-9a-fA-F]+;)",\n'
       '                "&amp;", body)')
FIELDS = 'cpath_setting, cpath_path, cpath_header, cpath_type, cpath_label'
POPULAR = {'movie': ('build_movie_list', 'tmdb_movies_popular'),
           'tvshow': ('build_tvshow_list', 'trakt_tv_trending')}
NEW_RELEASES = {'movie': ('build_movie_list', 'tmdb_movies_latest_releases'),
                'tvshow': ('build_tvshow_list', 'tmdb_tv_premieres')}
NEXT_EPISODES = 'plugin://plugin.video.pov/?mode=build_next_episode&name=32483&iconImage=next_episodes&widget_limit=12'


def _path_identity(path):
    """Compare routing only; labels/icons never identify a custom route."""
    try:
        uri = urlsplit(html.unescape(path or ''))
        params = dict(parse_qsl(uri.query))
        mode = params.get('mode', '')
        return (uri.scheme, uri.netloc, uri.path, mode,
                params.get('action', ''),
                params.get('name', '') if 'shortcut_folder' in mode else '',
                tuple(sorted((k, v) for k, v in params.items() if k not in
                    ('mode', 'action', 'name', 'iconImage', 'external_list_item',
                     'shortcut_folder'))))
    except (TypeError, ValueError):
        return None


def _missing_popular(rows, defaults):
    """Restore only a gap between recognizable shipped rows, once per profile."""
    result = []
    for media, route in POPULAR.items():
        prefix = media + '.widget.'
        expected = {r[0]: r for r in defaults if r[0].startswith(prefix)}
        current = {r[0]: r for r in rows if r[0].startswith(prefix)}
        popular = [r for r in expected.values()
                   if _path_identity(r[1]) and _path_identity(r[1])[3:5] == route]
        if len(popular) != 1 or not current:
            continue
        missing = popular[0]
        if missing[0] in current or any(_path_identity(r[1]) ==
                _path_identity(missing[1]) for r in current.values()):
            continue
        # Any custom path, moved row or unknown slot means this is a personal
        # layout. Do not invent a default position within it.
        if len(current) < 2 or any(key not in expected or
                _path_identity(row[1]) != _path_identity(expected[key][1])
                for key, row in current.items()):
            continue
        result.append(missing)
    return result


def _load_defaults(addons, folder, archive=None, expected_sha=None):
    """Read only integrity-verified shipped widget defaults."""
    if archive is None:
        from resources.libs.profile_store import BOOTSTRAP_SHA256
        expected_sha = BOOTSTRAP_SHA256
        archive = os.path.join(addons, 'plugin.program.kodipovilwizard',
                               'resources', 'bootstrap', 'config.zip')
    with open(archive, 'rb') as handle:
        if not expected_sha or hashlib.sha256(handle.read()).hexdigest() != expected_sha:
            raise ValueError('FENtastic layout defaults failed integrity verification')
    pending = None
    try:
        with zipfile.ZipFile(archive) as source:
            payload = source.read('addon_data/script.fentastic.helper/cpath_cache.db')
        with tempfile.NamedTemporaryFile(dir=folder, suffix='.db', delete=False) as handle:
            pending = handle.name
            handle.write(payload)
        with closing(sqlite3.connect(pending)) as connection:
            return connection.execute('SELECT ' + FIELDS + ' FROM custom_paths').fetchall()
    finally:
        if pending and os.path.isfile(pending):
            os.remove(pending)


def _backup_database(database, backup):
    if not os.path.isfile(backup):
        # A separate reader avoids backup() waiting on our writer.
        with closing(sqlite3.connect(database)) as reader:
            with closing(sqlite3.connect(backup)) as dest:
                reader.backup(dest)


def restore_popular_defaults(addons, userdata, archive=None, expected_sha=None):
    """Migrate missing default DB rows; preserve later deliberate removals."""
    folder = os.path.join(userdata, 'addon_data', 'script.fentastic.helper')
    database = os.path.join(folder, 'cpath_cache.db')
    receipt = os.path.join(folder, 'povil-popular-defaults-v1.json')
    if os.path.isfile(receipt) or not os.path.isfile(database):
        return 0
    defaults = _load_defaults(addons, folder, archive, expected_sha)
    with closing(sqlite3.connect(database, timeout=1)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        rows = connection.execute('SELECT ' + FIELDS + ' FROM custom_paths').fetchall()
        missing = _missing_popular(rows, defaults)
        if missing:
            _backup_database(database, os.path.join(folder, 'cpath_cache.before-popular-v1.db'))
            connection.executemany('INSERT INTO custom_paths VALUES (?,?,?,?,?)', missing)
        connection.commit()
    _write(receipt, json.dumps({'version': 1, 'restored': [r[0] for r in missing]}).encode('utf8'))
    return len(missing)


def align_default_order(addons, userdata, archive=None, expected_sha=None):
    """Once per profile, place new before popular in recognizable build groups.

    Store the change in the helper's database so its regeneration and profile
    switches retain the order. Custom/moved/filtered groups are left intact.
    """
    folder = os.path.join(userdata, 'addon_data', 'script.fentastic.helper')
    database = os.path.join(folder, 'cpath_cache.db')
    receipt = os.path.join(folder, 'povil-new-before-popular-v1.json')
    if os.path.isfile(receipt) or not os.path.isfile(database):
        return 0
    defaults = _load_defaults(addons, folder, archive, expected_sha)
    aligned = []
    with closing(sqlite3.connect(database, timeout=1)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        if os.path.isfile(receipt):
            return 0  # Another interpreter completed the migration while waiting.
        rows = connection.execute('SELECT ' + FIELDS + ' FROM custom_paths').fetchall()
        for media in POPULAR:
            expected = {r[0]: r for r in defaults if r[0].startswith(media + '.widget.')}
            current = {r[0]: r for r in rows if r[0].startswith(media + '.widget.')}
            if not current or any(key not in expected or
                    _path_identity(row[1]) != _path_identity(expected[key][1])
                    for key, row in current.items()):
                continue
            pair = []
            for route in (POPULAR[media], NEW_RELEASES[media]):
                matches = [r for r in expected.values() if _path_identity(r[1]) and
                           _path_identity(r[1])[3:5] == route]
                if len(matches) != 1 or matches[0][0] not in current:
                    break
                pair.append(current[matches[0][0]])
            if len(pair) != 2:
                continue
            popular, new = pair
            if (int(new[0].rsplit('.', 1)[1]) != int(popular[0].rsplit('.', 1)[1]) + 1 or
                    any('Stacked' in (r[4] or '') or not (r[3] or '').startswith('WidgetList')
                        for r in pair)):
                continue
            _backup_database(database, os.path.join(folder, 'cpath_cache.before-order-v1.db'))
            # Swap payloads, not unique keys; keep headers, styles and labels.
            connection.executemany('UPDATE custom_paths SET cpath_path=?, cpath_header=?, '
                'cpath_type=?, cpath_label=? WHERE cpath_setting=?',
                [new[1:] + (popular[0],), popular[1:] + (new[0],)])
            aligned.append(media)
        connection.commit()
    _write(receipt, json.dumps({'version': 1, 'aligned': aligned}).encode('utf8'))
    return len(aligned)


def _catalogue_identity(path):
    identity = _path_identity(path)
    # The public legacy 0.1.179 build spelled these two shipped genre folders
    # without an apostrophe. Keep their URLs/data, but recognize the same role.
    if identity and identity[:4] == ('plugin', 'plugin.video.pov', '/', 'navigator.build_shortcut_folder_list'):
        aliases = {'FENtastic - סרטים - זאנרים': "FENtastic - סרטים - ז'אנרים",
                   'FENtastic - סדרות - זאנרים': "FENtastic - סדרות - ז'אנרים"}
        if identity[5] in aliases:
            identity = identity[:5] + (aliases[identity[5]],) + identity[6:]
    return identity


def _restore_legacy_genre_folders(rows, userdata):
    """Keep exact shipped old genre links working, preserving existing folders."""
    database = os.path.join(userdata, 'addon_data', 'plugin.video.pov', 'navigator.db')
    if not os.path.isfile(database):
        return
    aliases = set()
    for row in rows:
        original, canonical = _path_identity(row[1]), _catalogue_identity(row[1])
        if original and canonical != original:
            aliases.add((original[5], canonical[5]))
    if not aliases:
        return
    with closing(sqlite3.connect(database, timeout=1)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        for old, new in aliases:
            if connection.execute('SELECT 1 FROM navigator WHERE list_name=? AND list_type=?',
                                  (old, 'shortcut_folder')).fetchone():
                continue
            contents = connection.execute('SELECT list_contents FROM navigator '
                'WHERE list_name=? AND list_type=?', (new, 'shortcut_folder')).fetchone()
            if contents is not None:
                _backup_database(database, os.path.join(os.path.dirname(database),
                                                       'navigator.before-catalogue-v2.db'))
                connection.execute('INSERT INTO navigator VALUES (?,?,?)',
                                   (old, 'shortcut_folder', contents[0]))
        connection.commit()


def restore_catalogue_pair(addons, userdata, archive=None, expected_sha=None):
    """Upgrade the old four-row build layout, without replacing custom groups.

    Old layouts have personal, one catalogue, networks and genres. Their slots
    are compacted, so the missing catalogue's default slot is already occupied.
    A previous no-op popular/order receipt must not certify this layout complete.
    """
    folder = os.path.join(userdata, 'addon_data', 'script.fentastic.helper')
    database = os.path.join(folder, 'cpath_cache.db')
    receipt = os.path.join(folder, 'povil-catalogue-pair-v2.json')
    if os.path.isfile(receipt) or not os.path.isfile(database):
        return 0
    defaults = _load_defaults(addons, folder, archive, expected_sha)
    previous = {}
    for name in ('povil-popular-defaults-v1.json', 'povil-new-before-popular-v1.json'):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, encoding='utf8') as handle:
                previous[name] = json.load(handle)
    restored, decisions = [], {}
    with closing(sqlite3.connect(database, timeout=1)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        if os.path.isfile(receipt):
            return 0
        rows = connection.execute('SELECT ' + FIELDS + ' FROM custom_paths').fetchall()
        for media in POPULAR:
            prefix = media + '.widget.'
            expected = sorted([r for r in defaults if r[0].startswith(prefix)],
                              key=lambda r: int(r[0].rsplit('.', 1)[1]))
            decisions[media] = 'preserved'
            try:
                current = sorted([r for r in rows if r[0].startswith(prefix)],
                                 key=lambda r: int(r[0].rsplit('.', 1)[1]))
            except (ValueError, TypeError):
                continue
            if len(expected) != 5 or len(current) != 4:
                continue
            routes = [_catalogue_identity(r[1]) for r in expected]
            catalogues = [i for i, route in enumerate(routes) if route and
                          route[3:5] in (NEW_RELEASES[media], POPULAR[media])]
            if catalogues != [1, 2] or not all(routes) or len(set(routes)) != 5:
                continue
            identities = [_catalogue_identity(r[1]) for r in current]
            missing = [i for i, identity in enumerate(routes) if identity not in identities]
            if len(missing) != 1 or missing[0] not in catalogues:
                continue
            remaining = [r for i, r in enumerate(expected) if i != missing[0]]
            if (identities != [_catalogue_identity(r[1]) for r in remaining] or
                    any(r[3] != default[3] or 'Stacked' in (r[4] or '')
                        for r, default in zip(current, remaining))):
                continue
            indices = [int(r[0].rsplit('.', 1)[1]) for r in current]
            if indices != [1, 2, 3, 4] and [r[0] for r in current] != [r[0] for r in remaining]:
                continue
            # A successful older repair proves both rows existed. Respect
            # subsequent removal instead of treating it as a legacy layout.
            if (media in previous.get('povil-new-before-popular-v1.json', {}).get('aligned', []) or
                    any(key.startswith(prefix) for key in previous.get(
                        'povil-popular-defaults-v1.json', {}).get('restored', []))):
                decisions[media] = 'removed_after_previous_repair'
                continue
            payloads = {_catalogue_identity(r[1]): r[1:] for r in current}
            payloads[routes[missing[0]]] = expected[missing[0]][1:]
            ordered = list(expected)
            if routes[1][3:5] == POPULAR[media]:
                ordered[1], ordered[2] = ordered[2], ordered[1]
            _restore_legacy_genre_folders(current, userdata)
            _backup_database(database, os.path.join(folder, 'cpath_cache.before-catalogue-v2.db'))
            connection.executemany('DELETE FROM custom_paths WHERE cpath_setting=?',
                                   [(r[0],) for r in current])
            connection.executemany('INSERT INTO custom_paths VALUES (?,?,?,?,?)',
                [(prefix + str(i),) + payloads[_catalogue_identity(r[1])]
                 for i, r in enumerate(ordered, 1)])
            restored.append(media)
            decisions[media] = 'restored_pair'
        connection.commit()
    _write(receipt, json.dumps({'version': 2, 'restored': restored,
                               'groups': decisions}).encode('utf8'))
    return len(restored)


def seed_next_episode_default(addons, userdata, archive=None, expected_sha=None):
    """Add native episode previews once, only in an intact build TV layout.

    The provider remains POV's selected local/Trakt/MDBList history. Its native
    episode builder retains sorting, resume points and age classification.
    Custom routes, reordered/removed rows and an existing next row are kept.
    """
    folder = os.path.join(userdata, 'addon_data', 'script.fentastic.helper')
    database = os.path.join(folder, 'cpath_cache.db')
    receipt = os.path.join(folder, 'povil-next-episode-v1.json')
    if os.path.isfile(receipt) or not os.path.isfile(database):
        return 0
    defaults = _load_defaults(addons, folder, archive, expected_sha)
    expected = sorted((r for r in defaults if r[0].startswith('tvshow.widget.')),
                      key=lambda r: int(r[0].rsplit('.', 1)[1]))
    inserted = False
    with closing(sqlite3.connect(database, timeout=1)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        if os.path.isfile(receipt):
            return 0
        rows = connection.execute('SELECT ' + FIELDS + ' FROM custom_paths').fetchall()
        current = [r for r in rows if r[0].startswith('tvshow.widget.')]
        # Accept only the five shipped routes, with the established new/popular
        # order. Do not interpret a custom sixth row or a gap as a build default.
        try:
            current.sort(key=lambda r: int(r[0].rsplit('.', 1)[1]))
            identities = [_catalogue_identity(r[1]) for r in current]
            known = [_catalogue_identity(r[1]) for r in expected]
            if (len(current) == len(expected) == 5 and
                    [r[0] for r in current] == ['tvshow.widget.' + str(i) for i in range(1, 6)] and
                    all(known) and len(set(known)) == 5 and
                    identities[0] == known[0] and identities[3:] == known[3:] and
                    {identities[1], identities[2]} == {known[1], known[2]} and
                    identities[1][3:5] == NEW_RELEASES['tvshow'] and
                    identities[2][3:5] == POPULAR['tvshow'] and
                    all(r[3] == default[3] and 'Stacked' not in (r[4] or '')
                        for r, default in zip(current, [expected[0]] +
                            sorted(expected[1:3], key=lambda r:
                                _catalogue_identity(r[1])[3:5] != NEW_RELEASES['tvshow']) + expected[3:]))):
                _backup_database(database, os.path.join(folder, 'cpath_cache.before-next-episode-v1.db'))
                next_row = ('tvshow.widget.2', NEXT_EPISODES,
                            '[B][COLOR yellow]הפרק הבא[/COLOR][/B]',
                            'WidgetListBigEpisodes', 'BigEpisodes')
                updated = [current[0], next_row] + [
                    ('tvshow.widget.' + str(i + 1),) + row[1:]
                    for i, row in enumerate(current[1:], 2)]
                connection.executemany('DELETE FROM custom_paths WHERE cpath_setting=?',
                                       [(r[0],) for r in current])
                connection.executemany('INSERT INTO custom_paths VALUES (?,?,?,?,?)', updated)
                inserted = True
        except (ValueError, TypeError, IndexError):
            pass  # Unknown saved layout: leave it intact.
        connection.commit()
    _write(receipt, json.dumps({'version': 1, 'inserted': inserted}).encode('utf8'))
    return int(inserted)


def _write(path, payload):
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(path),
                prefix='.povil-widget-', suffix='.tmp', delete=False) as handle:
            pending = handle.name
            handle.write(payload)
        os.replace(pending, path)
        pending = None
    finally:
        if pending and os.path.isfile(pending):
            os.remove(pending)


def repair_helper(addons):
    path = os.path.join(addons, 'script.fentastic.helper', 'resources', 'lib',
                        'modules', 'cpath_maker.py')
    if not os.path.isfile(path):
        return False
    with open(path, 'r', encoding='utf-8-sig') as handle:
        source = handle.read()
    if source.count(OLD) != 1:
        return False  # Unknown upstream code or already repaired.
    changed = source.replace(OLD, NEW)
    start = changed.index('    def make_widget_xml(')
    end = changed.index('    def write_xml(', start)
    method = changed[start:end]
    for field in ('cpath_type', 'cpath_path', 'cpath_header'):
        anchor = '%s=%s,' % (field, field)
        if method.count(anchor) != 1:
            return False
        method = method.replace(anchor, '%s=__import__("html").escape(\n'
            '                    __import__("html").unescape(%s), quote=True),' % (field, field))
    changed = changed[:start] + method + changed[end:]
    ast.parse(changed)
    _write(path, changed.encode('utf-8'))
    return True


def _block(kind, path, header, list_id):
    node = ET.Element('include', {'content': kind})
    for name, value in (('content_path', path), ('widget_header', header),
                        ('widget_target', 'videos'), ('list_id', str(list_id))):
        ET.SubElement(node, 'param', {'name': name, 'value': value})
    return node


def _params(node):
    return {p.get('name'): p.get('value') for p in node.findall('param')}


def repair_saved_widgets(addons, userdata):
    """Restore missing/reset generated rows; keep user layout and row limits."""
    skin_dir = os.path.join(addons, 'skin.fentastic', 'xml')
    database = os.path.join(userdata, 'addon_data', 'script.fentastic.helper',
                            'cpath_cache.db')
    if not os.path.isdir(skin_dir) or not os.path.isfile(database):
        return 0
    with closing(sqlite3.connect('file:' + database.replace('\\', '/') + '?mode=ro',
                                uri=True, timeout=1)) as connection:
        rows = connection.execute('SELECT cpath_setting, cpath_path, '
                                  'cpath_header, cpath_type, cpath_label '
                                  'FROM custom_paths').fetchall()
    changed_files = 0
    for media, (include_name, base) in GROUPS.items():
        saved = []
        for key, path, header, kind, label in rows:
            if not isinstance(key, str) or not key.startswith(media + '.widget.'):
                continue
            try:
                index = int(key.rsplit('.', 1)[1])
            except ValueError:
                continue
            if not (1 <= index <= 10 and isinstance(path, str) and path and
                    isinstance(kind, str) and kind.startswith('WidgetList')):
                continue
            saved.append((index, html.unescape(path), html.unescape(header or ''),
                          kind, 'Stacked' in (label or '')))
        if not saved:
            continue  # Explicitly removed/custom empty layouts stay empty.
        path = os.path.join(skin_dir, 'script-fentastic-widget_' +
                            ('movies' if media == 'movie' else
                             'tvshows' if media == 'tvshow' else media) + '.xml')
        if os.path.isfile(path):
            # Invalid or unknown XML is left intact for diagnosis.
            try:
                tree = ET.parse(path)
            except (ET.ParseError, OSError):
                continue
            root = tree.getroot()
            group = root.find("include[@name='" + include_name + "']")
            if root.tag != 'includes' or group is None:
                continue
        else:
            root = ET.Element('includes')
            group = ET.SubElement(root, 'include', {'name': include_name})
        changed = False
        originals = list(group.findall('include'))
        for index, url, header, kind, stacked in sorted(saved):
            list_id = base + index
            expected = [_block('WidgetListCategoryStacked' if stacked else kind,
                               url, header, list_id)]
            if stacked:
                expected.append(_block(kind,
                    '$INFO[Window(Home).Property(fentastic.%s.path)]' % list_id,
                    '$INFO[Window(Home).Property(fentastic.%s.label)]' % list_id,
                    str(list_id) + '1'))
            for node in expected:
                params = _params(node)
                candidates = [old for old in group.findall('include')
                              if _params(old).get('list_id') == params['list_id']]
                if len(candidates) > 1:
                    continue  # Do not guess about an ambiguous custom layout.
                old = candidates[0] if candidates else None
                if old is not None and old.get('content') == node.get('content') and all(
                        _params(old).get(k) == v for k, v in params.items()):
                    continue
                # A one-time DB reorder moves row options with their route.
                matches = [n for n in originals if n.get('content') == node.get('content') and
                    _path_identity(_params(n).get('content_path')) == _path_identity(params['content_path'])]
                options = matches[0] if len(matches) == 1 else old
                if not matches and old is not None and any(
                        _path_identity(url) == _path_identity(_params(old).get('content_path'))
                        and base + slot != list_id for slot, url, *_ in saved):
                    options = None  # An inserted row must not inherit the moved row's options.
                if options is not None:
                    for extra in options.findall('param'):
                        if extra.get('name') not in params:
                            node.append(deepcopy(extra))  # Preserve limit/sort/custom options.
                if old is not None:
                    position = list(group).index(old)
                    group.remove(old)
                else:
                    position = len(group)
                    for offset, other in enumerate(group):
                        value = _params(other).get('list_id', '')
                        if len(value) == 5 and value.isdigit() and int(value) > list_id:
                            position = offset
                            break
                group.insert(position, node)
                changed = True
        if changed:
            payload = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            ET.fromstring(payload)
            _write(path, payload)
            changed_files += 1
    return changed_files


def repair(reload_skin=True):
    import xbmc
    import xbmcvfs
    try:
        addons = xbmcvfs.translatePath('special://home/addons/')
        userdata = xbmcvfs.translatePath('special://profile/')
        from resources.libs import profile_store
        shortcuts = 0
        try:
            shortcuts = profile_store.repair_build_shortcuts(addons, userdata)
        except Exception as exc:
            xbmc.log('[POV IL] Build shortcut repair deferred: ' + type(exc).__name__, xbmc.LOGWARNING)
        repair_helper(addons)
        paired = restore_catalogue_pair(addons, userdata)
        restored = restore_popular_defaults(addons, userdata)
        aligned = align_default_order(addons, userdata)
        episodes = seed_next_episode_default(addons, userdata)
        changed = repair_saved_widgets(addons, userdata)
        if restored:
            xbmc.log('[POV IL] Restored %s missing FENtastic popular default paths' % restored,
                     xbmc.LOGINFO)
        if paired:
            xbmc.log('[POV IL] Restored new/popular pairs in %s legacy FENtastic groups' % paired,
                     xbmc.LOGINFO)
        if changed:
            xbmc.log('[POV IL] Restored %s saved FENtastic widget includes' % changed,
                     xbmc.LOGINFO)
        if aligned:
            xbmc.log('[POV IL] Aligned %s FENtastic groups: new before popular' % aligned,
                     xbmc.LOGINFO)
        if episodes:
            xbmc.log('[POV IL] Added native next-episode previews to FENtastic TV defaults', xbmc.LOGINFO)
        if shortcuts:
            xbmc.log('[POV IL] Restored %s build shortcut folders/rows in active profile' % shortcuts,
                     xbmc.LOGINFO)
        if (changed or aligned or shortcuts or paired or episodes) and reload_skin and xbmc.getSkinDir() == 'skin.fentastic' and not xbmc.Player().isPlayingVideo():
            xbmc.executebuiltin('ReloadSkin()')
        return changed or aligned or shortcuts or paired or episodes
    except Exception as exc:
        xbmc.log('[POV IL] FENtastic widget repair deferred: %s' % exc, xbmc.LOGWARNING)
        return 0


def diagnostics():
    """Log only route names and counts, never custom URLs or account values."""
    import xbmc
    import xbmcvfs
    if xbmc.getSkinDir() != 'skin.fentastic':
        return
    userdata = xbmcvfs.translatePath('special://profile/')
    addons = xbmcvfs.translatePath('special://home/addons/')
    database = os.path.join(userdata, 'addon_data', 'script.fentastic.helper', 'cpath_cache.db')
    try:
        with closing(sqlite3.connect('file:' + database.replace('\\', '/') + '?mode=ro', uri=True)) as conn:
            rows = conn.execute('SELECT ' + FIELDS + ' FROM custom_paths').fetchall()
        home_active = xbmc.getCondVisibility('Window.IsActive(home)')
        report = {'home_active': home_active}
        report['pair_v2'] = os.path.isfile(os.path.join(
            os.path.dirname(database), 'povil-catalogue-pair-v2.json'))
        report['layout'] = {}
        for media, route in POPULAR.items():
            layout = []
            for row in rows:
                if not row[0].startswith(media + '.widget.'):
                    continue
                slot = row[0].rsplit('.', 1)[1]
                identity = _path_identity(row[1])
                role = 'custom'
                if identity:
                    if identity[3:5] == NEW_RELEASES[media]:
                        role = 'new'
                    elif identity[3:5] == route:
                        role = 'popular'
                    elif identity[3] == 'navigator.build_shortcut_folder_list':
                        role = 'shortcut_folder'
                layout.append({'slot': int(slot) if slot.isdigit() else None, 'role': role})
            report['layout'][media] = layout
            saved = [r for r in rows if r[0].startswith(media + '.widget.') and
                     _path_identity(r[1]) and _path_identity(r[1])[3:5] == route]
            summary = {'saved': len(saved), 'generated': 0, 'items': []}
            path = os.path.join(addons, 'skin.fentastic', 'xml', 'script-fentastic-widget_' +
                                ('movies' if media == 'movie' else 'tvshows') + '.xml')
            for node in ET.parse(path).findall('include/include'):
                values = _params(node)
                identity = _path_identity(values.get('content_path', ''))
                if not identity or identity[3:5] != route:
                    continue
                summary['generated'] += 1
                ident = values.get('list_id', '')
                if ident.isdigit():
                    summary['items'].append({'id': ident,
                        'count': xbmc.getInfoLabel('Container(%s).NumItems' % ident) if home_active else None,
                        'updating': xbmc.getCondVisibility('Container(%s).IsUpdating' % ident) if home_active else None})
            report[media] = summary
        xbmc.log('[POV IL] FENtastic popular widgets: ' + json.dumps(report, sort_keys=True), xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[POV IL] FENtastic widget diagnostics unavailable: ' + type(exc).__name__, xbmc.LOGWARNING)
