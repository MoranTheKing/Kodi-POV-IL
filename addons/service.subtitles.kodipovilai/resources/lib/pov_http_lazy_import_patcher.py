"""Keep POV's HTTP stack cold while a valid catalogue cache can answer.

POV imports ``requests`` and constructs an HTTP session as soon as either its
TMDb or Trakt API module is imported.  A home widget must import those modules
even when POV's own unexpired SQLite cache already contains every value it
needs.  On a 32-bit cold interpreter that eagerly loads more than a hundred
unrelated networking/encoding modules before Kodi can draw the first poster.

This patch replaces only the eager module/session objects with thread-safe
lazy proxies.  Existing call sites, cache keys, expiries, request parameters,
retry policy and failure handling stay byte-for-byte unchanged.  A cache hit
never imports requests; a miss creates the same configured Session on first
access and follows POV's normal live request path.  Unknown upstream shapes
are refused intact.
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
MARKER = '# AI_SUBS_POV_LAZY_HTTP_IMPORTS_v1'
END_MARKER = '# AI_SUBS_POV_LAZY_HTTP_IMPORTS_END'

TARGETS = (
    ('resources/lib/indexers/tmdb_api.py', 'tmdb'),
    ('resources/lib/indexers/trakt_api.py', 'trakt'),
)

_IMPORT_RE = re.compile(r'^import requests[ \t]*(?=\r?$)', re.MULTILINE)
_FAMILY_RE = re.compile(
    r'^# AI_SUBS_POV_LAZY_HTTP_IMPORTS_v\d+[ \t]*\r?\n'
    r'.*?'
    r'^# AI_SUBS_POV_LAZY_HTTP_IMPORTS_END[ \t]*(?=\r?$)',
    re.MULTILINE | re.DOTALL,
)
_PROXY_SESSION_RE = re.compile(
    r'^session = _PovLazySession\(\)[ \t]*(?=\r?$)', re.MULTILINE)

_STOCK_SESSIONS = {
    'tmdb': (
        'session = requests.Session()\n'
        'retry = requests.adapters.Retry(total=None, status=1, '
        'status_forcelist=(429, 502, 503, 504))\n'
        "session.mount('https://api.themoviedb.org', "
        'requests.adapters.HTTPAdapter(pool_maxsize=100, '
        'max_retries=retry))'
    ),
    'trakt': (
        'session = requests.Session()\n'
        "session.headers.update({'User-Agent': "
        'kodi_utils.xbmc.getUserAgent()})\n'
        'retry = requests.adapters.Retry(total=None, status=1, '
        'status_forcelist=(429, 502, 503, 504))\n'
        "session.mount('https://api.trakt.tv', "
        'requests.adapters.HTTPAdapter(pool_maxsize=100, '
        'max_retries=retry))'
    ),
}


def _log(message, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log(
            'pov_http_lazy_import_patcher: ' + message, level=level)
    except Exception:
        pass


def _addon_path(relative):
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


def _session_setup(kind):
    if kind == 'tmdb':
        return [
            '_retry = _module.adapters.Retry(total=None, status=1, '
            'status_forcelist=(429, 502, 503, 504))',
            "_session.mount('https://api.themoviedb.org', "
            '_module.adapters.HTTPAdapter(pool_maxsize=100, '
            'max_retries=_retry))',
        ]
    if kind == 'trakt':
        return [
            "_session.headers.update({'User-Agent': "
            'kodi_utils.xbmc.getUserAgent()})',
            '_retry = _module.adapters.Retry(total=None, status=1, '
            'status_forcelist=(429, 502, 503, 504))',
            "_session.mount('https://api.trakt.tv', "
            '_module.adapters.HTTPAdapter(pool_maxsize=100, '
            'max_retries=_retry))',
        ]
    raise ValueError('unknown target kind: ' + str(kind))


def _lazy_block(kind, eol='\n'):
    lines = [
        MARKER,
        'from threading import Lock as _PovHttpLock',
        '',
        'class _PovLazyRequests:',
        '\tdef __init__(self):',
        '\t\tself._module = None',
        '\t\tself._lock = _PovHttpLock()',
        '',
        '\tdef _load(self):',
        '\t\tif self._module is None:',
        '\t\t\twith self._lock:',
        '\t\t\t\tif self._module is None:',
        '\t\t\t\t\timport requests as _module',
        '\t\t\t\t\tself._module = _module',
        '\t\treturn self._module',
        '',
        '\tdef __getattr__(self, name):',
        '\t\treturn getattr(self._load(), name)',
        '',
        'class _PovLazySession:',
        '\tdef __init__(self):',
        '\t\tself._session = None',
        '\t\tself._lock = _PovHttpLock()',
        '',
        '\tdef _load(self):',
        '\t\tif self._session is None:',
        '\t\t\twith self._lock:',
        '\t\t\t\tif self._session is None:',
        '\t\t\t\t\t_module = requests._load()',
        '\t\t\t\t\t_session = _module.Session()',
    ]
    lines.extend('\t\t\t\t\t' + line for line in _session_setup(kind))
    lines.extend([
        '\t\t\t\t\tself._session = _session',
        '\t\treturn self._session',
        '',
        '\tdef __getattr__(self, name):',
        '\t\treturn getattr(self._load(), name)',
        '',
        'requests = _PovLazyRequests()',
        END_MARKER,
    ])
    return eol.join(lines)


def _with_eol(text, eol):
    return text.replace('\n', eol)


def _normalise_old_generated(original, kind, eol):
    family = list(_FAMILY_RE.finditer(original))
    sessions = list(_PROXY_SESSION_RE.finditer(original))
    if not family and not sessions:
        return original, None
    if len(family) != 1 or len(sessions) != 1:
        return original, 'unmatched'
    restored = (original[:family[0].start()] + 'import requests'
                + original[family[0].end():])
    sessions = list(_PROXY_SESSION_RE.finditer(restored))
    if len(sessions) != 1:
        return original, 'unmatched'
    stock = _with_eol(_STOCK_SESSIONS[kind], eol)
    restored = (restored[:sessions[0].start()] + stock
                + restored[sessions[0].end():])
    return restored, None


def _has_valid_current_block(original, kind, eol):
    """Accept only the exact generated block plus its one proxy binding."""
    family = list(_FAMILY_RE.finditer(original))
    sessions = list(_PROXY_SESSION_RE.finditer(original))
    return (
        original.count(MARKER) == 1
        and original.count(END_MARKER) == 1
        and len(family) == 1
        and family[0].group(0) == _lazy_block(kind, eol)
        and len(sessions) == 1
    )


def _patch_file(path, kind):
    try:
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            original = handle.read()
    except Exception as exc:
        _log('{0}: read failed: {1}'.format(os.path.basename(path), exc),
             level='WARNING')
        return 'read_failed'
    eol = '\r\n' if original.count('\r\n') > (original.count('\n') // 2) else '\n'
    if MARKER in original:
        if _has_valid_current_block(original, kind, eol):
            return 'unchanged'
        _log('{0}: current marker exists without its complete generated '
             'block'.format(os.path.basename(path)), level='WARNING')
        return 'unmatched'
    clean, error = _normalise_old_generated(original, kind, eol)
    if error:
        _log('{0}: malformed older generated block'.format(
            os.path.basename(path)), level='WARNING')
        return error
    imports = list(_IMPORT_RE.finditer(clean))
    stock = _with_eol(_STOCK_SESSIONS[kind], eol)
    if len(imports) != 1 or clean.count(stock) != 1:
        _log('{0}: expected one import/session anchor, found {1}/{2}'.format(
            os.path.basename(path), len(imports), clean.count(stock)),
            level='WARNING')
        return 'unmatched'
    updated = (clean[:imports[0].start()] + _lazy_block(kind, eol)
               + clean[imports[0].end():])
    updated = updated.replace(stock, 'session = _PovLazySession()', 1)
    try:
        compile(updated, path, 'exec')
    except SyntaxError as exc:
        _log('{0}: compile failed: {1}'.format(os.path.basename(path), exc),
             level='WARNING')
        return 'compile_failed'
    if not _atomic_write(path, updated):
        _log('{0}: write failed'.format(os.path.basename(path)),
             level='WARNING')
        return 'write_failed'
    _drop_pyc(path)
    return 'patched'


def ensure_patched():
    """Apply both narrow lazy-import rewrites; never raise into startup."""
    results = {}
    changed = False
    try:
        for relative, kind in TARGETS:
            path = _addon_path(relative)
            key = os.path.basename(relative)
            if not path or not os.path.isfile(path):
                results[key] = 'no_file'
                continue
            status = _patch_file(path, kind)
            results[key] = status
            changed = changed or status == 'patched'
        if changed:
            try:
                from resources.lib import pov_reload
                pov_reload.note_patched()
            except Exception:
                pass
            _log('HTTP modules now load only for an actual live request')
        return results
    except Exception as exc:
        _log('unexpected failure: {0}'.format(exc), level='WARNING')
        results['_status'] = 'failed'
        return results
