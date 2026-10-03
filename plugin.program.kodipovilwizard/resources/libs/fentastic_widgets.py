"""Keep helper-generated widgets consistent with the user's saved paths.

The paths database is authoritative. Never seed an empty database, change a
saved path, or fetch provider results to repair a generated skin include.
"""
import ast
from contextlib import closing
import html
import os
import sqlite3
import tempfile
import xml.etree.ElementTree as ET

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
        changed = repair_saved_widgets(addons, userdata)
        if changed:
            xbmc.log('[POV IL] Restored %s saved FENtastic widget includes' % changed,
                     xbmc.LOGINFO)
            if reload_skin and xbmc.getSkinDir() == 'skin.fentastic' and not xbmc.Player().isPlayingVideo():
                xbmc.executebuiltin('ReloadSkin()')
        return changed
    except Exception as exc:
        xbmc.log('[POV IL] FENtastic widget repair deferred: %s' % exc, xbmc.LOGWARNING)
        return 0
