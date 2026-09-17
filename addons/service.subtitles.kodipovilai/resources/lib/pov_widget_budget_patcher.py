"""Bound POV home-widget work without changing normal catalogue browsing.

Kodi's skin-side ``limit`` only limits what a widget *shows*. POV still fetches
metadata, artwork, watched state and context menus for the complete page before
Kodi discards the hidden items. On 32-bit devices several rows doing that
together are a large avoidable part of the home-screen spinner.

This patcher gives build-owned FENtastic and NOX media rows an explicit
``widget_limit`` and teaches POV's movie/TV builders to honour it before their
metadata workers run. POV must both report an external/widget browse and carry
the explicit parameter, so normal lists, search and playback are unchanged.
"""

import os
import re
import xml.etree.ElementTree as ET

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


HOST = 'plugin.video.pov'
POV_ADDON_ID = HOST
MARKER = '# AI_SUBS_POV_WIDGET_BUDGET_v1'
_END_MARKER = '# AI_SUBS_POV_WIDGET_BUDGET_END'

POV_TARGETS = (
    'resources/lib/menus/movies.py',
    'resources/lib/menus/tvshows.py',
    'resources/lib/menus/episodes.py',
)

# Twelve is a full TV screen plus useful horizontal browsing while avoiding
# 40% of the work on POV's usual 20-item API page. AF3 owns a stricter seven-
# item limit in its node data; af3_home_patcher tags those URLs directly.
SKIN_TARGETS = (
    ('skin.fentastic', 'xml/script-fentastic-widget_movies.xml', 12),
    ('skin.fentastic', 'xml/script-fentastic-widget_tvshows.xml', 12),
    ('skin.povil.nox', 'xml/script-nox-widget_movies.xml', 12),
    ('skin.povil.nox', 'xml/script-nox-widget_tvshows.xml', 12),
    ('skin.povil.nox', 'xml/script-nox-widget_kids.xml', 12),
)

_ADD_ITEMS_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<guard>if self\.list:[ \t]*)?'
    r'kodi_utils\.add_items\('
    r'__handle__, (?P<worker>worker\(\)|self\.worker\(\))\)[ \t]*(?=\r?$)',
    re.MULTILINE,
)
_OLD_BLOCK_RE = re.compile(
    r'^[ \t]*# AI_SUBS_POV_WIDGET_BUDGET_v\d+[ \t]*\r?\n'
    r'.*?^[ \t]*# AI_SUBS_POV_WIDGET_BUDGET_END[ \t]*\r?\n',
    re.MULTILINE | re.DOTALL,
)
_INCLUDE_RE = re.compile(r'<include\b[^>]*>.*?</include>',
                         re.IGNORECASE | re.DOTALL)
_CONTENT_PATH_RE = re.compile(
    r'(?P<head><param\s+name=["\']content_path["\']\s+value=["\'])'
    r'(?P<url>[^"\']*)'
    r'(?P<tail>["\'][^>]*/>)',
    re.IGNORECASE | re.DOTALL,
)
_LIMIT_PARAM_RE = re.compile(
    r'<param\s+name=["\']limit["\']\s+value=["\'][^"\']*["\']\s*/>',
    re.IGNORECASE,
)


def _log(message, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_widget_budget_patcher: ' + message, level=level)
    except Exception:
        pass


def _addon_path(addon_id, relative=''):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + addon_id + '/')
    except Exception:
        return ''
    return os.path.join(base, *relative.split('/')) if relative else base


def _drop_pyc(path):
    try:
        pycache = os.path.join(os.path.dirname(path), '__pycache__')
        stem = os.path.splitext(os.path.basename(path))[0]
        if os.path.isdir(pycache):
            for name in os.listdir(pycache):
                if name.startswith(stem + '.') and name.endswith('.pyc'):
                    try:
                        os.remove(os.path.join(pycache, name))
                    except OSError:
                        pass
        legacy = path + 'c'
        if os.path.isfile(legacy):
            os.remove(legacy)
    except OSError:
        pass


def _atomic_write(path, body):
    tmp = path + '.kpovtmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as handle:
            handle.write(body)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _budget_block(indent, worker, eol='\n'):
    worker_ref = worker[:-2]
    restore_worker = (
        indent + '\t\t\tself.worker = _pov_widget_original_worker' + eol
        if worker_ref == 'self.worker' else '')
    return (
        indent + MARKER + eol
        # POV removes watched items inside the metadata worker. Applying a
        # producer budget before that filter could leave a short row with no
        # backfill, so preserve POV's full-page behaviour for that setting.
        + indent + 'if self.is_widget and not self.widget_hide_watched:' + eol
        + indent + '\ttry:' + eol
        + indent + "\t\t_pov_widget_limit = int(self.params.get('widget_limit', 0) or 0)" + eol
        + indent + '\texcept (TypeError, ValueError):' + eol
        + indent + '\t\t_pov_widget_limit = 0' + eol
        + indent + '\tif _pov_widget_limit > 0 and self.list:' + eol
        + indent + '\t\t_pov_widget_source = self.list' + eol
        + indent + '\t\t_pov_widget_target = min(_pov_widget_limit, 50, len(_pov_widget_source))' + eol
        + indent + '\t\t_pov_widget_original_worker = ' + worker_ref + eol
        + indent + '\t\tdef _pov_widget_worker():' + eol
        + restore_worker
        + indent + '\t\t\t_pov_widget_count = _pov_widget_target' + eol
        + indent + '\t\t\ttry:' + eol
        + indent + '\t\t\t\twhile True:' + eol
        + indent + '\t\t\t\t\tself.list = _pov_widget_source[:_pov_widget_count]' + eol
        + indent + '\t\t\t\t\tself.items = []' + eol
        + indent + '\t\t\t\t\tself.append = self.items.append' + eol
        + indent + '\t\t\t\t\t_pov_widget_items = _pov_widget_original_worker()' + eol
        + indent + '\t\t\t\t\tif len(_pov_widget_items) >= _pov_widget_target or _pov_widget_count >= len(_pov_widget_source): break' + eol
        + indent + '\t\t\t\t\t_pov_widget_count = min(len(_pov_widget_source), max(_pov_widget_count * 2, _pov_widget_count + _pov_widget_target - len(_pov_widget_items)))' + eol
        + indent + '\t\t\t\treturn _pov_widget_items[:_pov_widget_target]' + eol
        + indent + '\t\t\tfinally:' + eol
        + indent + '\t\t\t\tself.list = _pov_widget_source' + eol
        + indent + '\t\t' + worker_ref + ' = _pov_widget_worker' + eol
        + indent + _END_MARKER + eol
        + indent + 'kodi_utils.add_items(__handle__, ' + worker + ')'
    )


def _patch_pov_file(path):
    try:
        # newline='' keeps the host's line endings visible.  Several POV
        # releases ship CRLF and normalising the whole module during a tiny
        # runtime patch makes later patch anchors unnecessarily fragile.
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            original = handle.read()
    except Exception as exc:
        _log('{0}: read failed: {1}'.format(os.path.basename(path), exc),
             level='WARNING')
        return 'read_failed'

    clean = _OLD_BLOCK_RE.sub('', original)
    matches = list(_ADD_ITEMS_RE.finditer(clean))
    if len(matches) != 1:
        _log('{0}: expected one add-items anchor, found {1}'.format(
            os.path.basename(path), len(matches)), level='WARNING')
        return 'unmatched'
    match = matches[0]
    eol = '\r\n' if original.count('\r\n') > (original.count('\n') // 2) else '\n'
    indent = match.group('indent')
    if match.group('guard'):
        replacement = (indent + 'if self.list:' + eol
                       + _budget_block(indent + '\t', match.group('worker'),
                                       eol=eol))
    else:
        replacement = _budget_block(
            indent, match.group('worker'), eol=eol)
    updated = clean[:match.start()] + replacement + clean[match.end():]
    try:
        compile(updated, path, 'exec')
    except SyntaxError as exc:
        _log('{0}: compile failed: {1}'.format(os.path.basename(path), exc),
             level='WARNING')
        return 'compile_failed'
    if updated == original:
        return 'unchanged'
    if not _atomic_write(path, updated):
        _log('{0}: write failed'.format(os.path.basename(path)),
             level='WARNING')
        return 'write_failed'
    _drop_pyc(path)
    return 'patched'


def _patch_widget_include(block, limit):
    match = _CONTENT_PATH_RE.search(block)
    if match is None:
        return block
    url = match.group('url')
    if not url.startswith('plugin://plugin.video.pov/?'):
        return block
    if not ('mode=build_movie_list' in url
            or 'mode=build_tvshow_list' in url):
        return block
    if not re.search(r'(?:&amp;|&)widget_limit=', url):
        url += '&amp;widget_limit={0}'.format(limit)
        block = (block[:match.start('url')] + url
                 + block[match.end('url'):])
    if _LIMIT_PARAM_RE.search(block):
        return block
    close = re.search(r'(?P<newline>\r?\n)(?P<indent>[ \t]*)</include>[ \t]*$',
                      block)
    if close is None:
        return block
    param_match = re.search(r'\r?\n(?P<indent>[ \t]*)<param\b', block)
    param_indent = (param_match.group('indent') if param_match
                    else close.group('indent') + '    ')
    addition = (close.group('newline') + param_indent
                + '<param name="limit" value="{0}"/>'.format(limit))
    return block[:close.start()] + addition + block[close.start():]


def _patch_skin_file(path, limit):
    try:
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            original = handle.read()
    except Exception as exc:
        _log('{0}: read failed: {1}'.format(os.path.basename(path), exc),
             level='WARNING')
        return 'read_failed'
    updated = _INCLUDE_RE.sub(
        lambda match: _patch_widget_include(match.group(0), limit), original)
    if updated == original:
        return 'unchanged'
    try:
        ET.fromstring(updated.encode('utf-8'))
    except ET.ParseError as exc:
        _log('{0}: XML validation failed: {1}'.format(os.path.basename(path), exc),
             level='WARNING')
        return 'xml_failed'
    if not _atomic_write(path, updated):
        _log('{0}: write failed'.format(os.path.basename(path)),
             level='WARNING')
        return 'write_failed'
    return 'patched'


def ensure_patched():
    """Return per-target statuses; never raise into the startup service."""
    results = {}
    pov_changed = False
    try:
        for relative in POV_TARGETS:
            path = _addon_path(POV_ADDON_ID, relative)
            key = 'pov/' + os.path.basename(relative)
            if not path or not os.path.isfile(path):
                results[key] = 'no_file'
                continue
            status = _patch_pov_file(path)
            results[key] = status
            pov_changed = pov_changed or status == 'patched'
        for addon_id, relative, limit in SKIN_TARGETS:
            path = _addon_path(addon_id, relative)
            key = addon_id + '/' + os.path.basename(relative)
            if not path or not os.path.isfile(path):
                results[key] = 'no_file'
                continue
            results[key] = _patch_skin_file(path, limit)
        if pov_changed:
            try:
                from resources.lib import pov_reload
                pov_reload.note_patched()
            except Exception:
                pass
        if any(value == 'patched' for value in results.values()):
            _log('applied bounded widget work: {0}'.format(', '.join(
                '{0}={1}'.format(key, value)
                for key, value in sorted(results.items()))))
        return results
    except Exception as exc:
        _log('unexpected failure: {0}'.format(exc), level='WARNING')
        results['_status'] = 'failed'
        return results
