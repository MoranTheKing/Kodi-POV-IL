"""Defer POV account backends that an ordinary catalogue read does not use.

POV's ``caches/watched_cache.py`` imports the complete Trakt and MDBList API
modules, both account caches and the local-list API at module import time.
Every movie/TV directory imports ``watched_cache`` merely to read the already
synced watched SQLite file, so a fresh Kodi Python interpreter parses those
unrelated backends before it can draw a single item. The effect is most visible
on 32-bit ARM, where each click starts a cold interpreter because the build
keeps language-invoker reuse off for stability.

Replace only the exact upstream import block with transparent forwarding
functions. The real module is imported on the first operation that actually
needs it (marking watched, remote progress, or dropped-list lookup). Function
arguments and return values pass through unchanged. Unknown upstream shapes
are left untouched.
"""

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
TARGET_REL = 'resources/lib/caches/watched_cache.py'
MARKER = '# AI_SUBS_POV_LAZY_WATCHED_IMPORTS_v1'

_IMPORT_BLOCK_RE = re.compile(
    r'^from caches\.mdbl_cache import clear_mdbl_collection_watchlist_data\r?\n'
    r'^from caches\.trakt_cache import clear_trakt_collection_watchlist_data\r?\n'
    r'^from indexers import metadata\r?\n'
    r'^from indexers\.local_api import local_get_hidden_items\r?\n'
    r'^from indexers\.mdblist_api import mdbl_watched_unwatched, mdbl_progress, mdbl_get_hidden_items\r?\n'
    r'^from indexers\.trakt_api import trakt_watched_unwatched, trakt_progress, trakt_get_hidden_items, trakt_official_status(?=\r?$)',
    re.MULTILINE,
)
_GENERATED_BLOCK_RE = re.compile(
    r'^from indexers import metadata\r?\n'
    r'\r?\n'
    r'^# AI_SUBS_POV_LAZY_WATCHED_IMPORTS_v\d+\r?\n'
    r'.*?(?=^from modules import )',
    re.MULTILINE | re.DOTALL,
)

_FORWARDERS = (
    ('clear_mdbl_collection_watchlist_data', 'caches.mdbl_cache'),
    ('clear_trakt_collection_watchlist_data', 'caches.trakt_cache'),
    ('local_get_hidden_items', 'indexers.local_api'),
    ('mdbl_watched_unwatched', 'indexers.mdblist_api'),
    ('mdbl_progress', 'indexers.mdblist_api'),
    ('mdbl_get_hidden_items', 'indexers.mdblist_api'),
    ('trakt_watched_unwatched', 'indexers.trakt_api'),
    ('trakt_progress', 'indexers.trakt_api'),
    ('trakt_get_hidden_items', 'indexers.trakt_api'),
    ('trakt_official_status', 'indexers.trakt_api'),
)


def _log(message, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log(
            'pov_watched_lazy_import_patcher: ' + message, level=level)
    except Exception:
        pass


def _addon_path(relative=TARGET_REL):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    return os.path.join(base, *relative.split('/'))


def _drop_pyc(path):
    try:
        pycache = os.path.join(os.path.dirname(path), '__pycache__')
        stem = os.path.splitext(os.path.basename(path))[0] + '.'
        if os.path.isdir(pycache):
            for name in os.listdir(pycache):
                if name.startswith(stem) and name.endswith('.pyc'):
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


def _replacement(eol='\n'):
    lines = [
        'from indexers import metadata',
        '',
        MARKER,
        'def _pov_lazy_watched_call(module_name, function_name, args, kwargs):',
        '\tfunction = getattr(__import__(module_name, fromlist=[function_name]), function_name)',
        '\treturn function(*args, **kwargs)',
    ]
    for function_name, module_name in _FORWARDERS:
        lines.extend((
            '',
            'def {0}(*args, **kwargs):'.format(function_name),
            "\treturn _pov_lazy_watched_call('{0}', '{1}', args, kwargs)".format(
                module_name, function_name),
        ))
    return eol.join(lines)


def _patch_file(path):
    try:
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            original = handle.read()
    except Exception as exc:
        _log('read failed: {0}'.format(exc), level='WARNING')
        return 'read_failed'
    if MARKER in original:
        return 'unchanged'
    eol = '\r\n' if original.count('\r\n') > (original.count('\n') // 2) else '\n'
    generated = list(_GENERATED_BLOCK_RE.finditer(original))
    if generated:
        if len(generated) != 1:
            _log('expected one old generated block, found {0}'.format(
                len(generated)), level='WARNING')
            return 'unmatched'
        updated = (original[:generated[0].start()] + _replacement(eol) + eol
                   + original[generated[0].end():])
    else:
        matches = list(_IMPORT_BLOCK_RE.finditer(original))
        if len(matches) != 1:
            _log('expected one import block, found {0}'.format(len(matches)),
                 level='WARNING')
            return 'unmatched'
        updated = (original[:matches[0].start()] + _replacement(eol)
                   + original[matches[0].end():])
    try:
        compile(updated, path, 'exec')
    except SyntaxError as exc:
        _log('compile failed: {0}'.format(exc), level='WARNING')
        return 'compile_failed'
    if not _atomic_write(path, updated):
        _log('write failed', level='WARNING')
        return 'write_failed'
    _drop_pyc(path)
    return 'patched'


def ensure_patched():
    """Apply the narrow lazy-import rewrite and never raise into startup."""
    path = _addon_path()
    if not path or not os.path.isfile(path):
        return 'no_file'
    try:
        status = _patch_file(path)
        if status == 'patched':
            try:
                from resources.lib import pov_reload
                pov_reload.note_patched()
            except Exception:
                pass
            _log('deferred unused Trakt/MDBList watched backends')
        return status
    except Exception as exc:
        _log('unexpected failure: {0}'.format(exc), level='WARNING')
        return 'failed'
