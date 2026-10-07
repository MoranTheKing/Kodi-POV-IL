"""Keep helper-generated widgets consistent with the user's saved paths.

The paths database is authoritative. A one-time migration restores missing
popular defaults in an otherwise unchanged build layout. Empty/custom layouts
and existing saved paths are preserved. No provider fetch is needed.
"""
import ast
from contextlib import closing
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


def restore_popular_defaults(addons, userdata, archive=None, expected_sha=None):
    """Migrate missing default DB rows; preserve later deliberate removals."""
    folder = os.path.join(userdata, 'addon_data', 'script.fentastic.helper')
    database = os.path.join(folder, 'cpath_cache.db')
    receipt = os.path.join(folder, 'povil-popular-defaults-v1.json')
    if os.path.isfile(receipt) or not os.path.isfile(database):
        return 0
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
            defaults = connection.execute('SELECT ' + FIELDS + ' FROM custom_paths').fetchall()
        with closing(sqlite3.connect(database, timeout=1)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute('SELECT ' + FIELDS + ' FROM custom_paths').fetchall()
            missing = _missing_popular(rows, defaults)
            if missing:
                backup = os.path.join(folder, 'cpath_cache.before-popular-v1.db')
                if not os.path.isfile(backup):
                    # A separate reader avoids backup() waiting on our writer.
                    with closing(sqlite3.connect(database)) as reader:
                        with closing(sqlite3.connect(backup)) as dest:
                            reader.backup(dest)
                connection.executemany('INSERT INTO custom_paths VALUES (?,?,?,?,?)', missing)
            connection.commit()
        _write(receipt, json.dumps({'version': 1, 'restored': [r[0] for r in missing]}).encode('utf8'))
        return len(missing)
    finally:
        if pending and os.path.isfile(pending):
            os.remove(pending)


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
                if old is not None:
                    for extra in old.findall('param'):
                        if extra.get('name') not in params:
                            node.append(extra)  # Preserve limit/sort/custom options.
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
        repair_helper(addons)
        restored = restore_popular_defaults(addons, userdata)
        changed = repair_saved_widgets(addons, userdata)
        if restored:
            xbmc.log('[POV IL] Restored %s missing FENtastic popular default paths' % restored,
                     xbmc.LOGINFO)
        if changed:
            xbmc.log('[POV IL] Restored %s saved FENtastic widget includes' % changed,
                     xbmc.LOGINFO)
            if reload_skin and xbmc.getSkinDir() == 'skin.fentastic' and not xbmc.Player().isPlayingVideo():
                xbmc.executebuiltin('ReloadSkin()')
        return changed
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
        for media, route in POPULAR.items():
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
