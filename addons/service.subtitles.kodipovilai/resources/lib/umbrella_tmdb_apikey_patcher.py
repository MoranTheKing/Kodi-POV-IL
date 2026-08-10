# Umbrella's search finds nothing when you type Hebrew. It is not TMDb, and
# it is not the language/region parameters -- TMDb answers a Hebrew query
# perfectly well. Umbrella never sends the request at all.
#
# menus/movies.py builds the search URL like this:
#
#     search_tmdb_link = '.../3/search/movie?api_key=%s&language=en-US' \
#                        '&query=%s&region=US&page=1'
#     url = self.search_tmdb_link % ('%s', quote_plus(q))
#
# -- the query is filled in now, the api_key `%s` is deliberately left for
# later. Then indexers/tmdb.py substitutes the key with %-formatting:
#
#     result = cache.get(self.get_request, self.tmdblist_hours,
#                        url % self.API_key)
#
# For "king of lions" that is fine: quote_plus leaves ASCII alone, the only
# `%` in the string is the `%s`. For "מלך הארי" quote_plus produces
# `%D7%9E%D7%9C%D7%9A+...`, and Python's %-formatting reads every one of
# those `%D7` / `%9E` groups as another conversion specifier. With a single
# argument supplied it raises immediately:
#
#     TypeError: not enough arguments for format string
#
# The enclosing `except: return` is bare and logs nothing, so the indexer
# returns None, the menu renders zero rows and shows "no results" -- with no
# network request and nothing in the Kodi log. In the field log this is
# visible as the difference between an English search (~2.2s, results) and a
# Hebrew one (~0.16s, straight to the notification).
#
# Umbrella already knows about this bug: TVshows.tmdb_list has a hand-rolled
# branch `if '%27' in url` that splits on '%s' instead of formatting, added
# because an apostrophe (`Assassin's` -> `%27`) breaks in exactly the same
# way. That patch treats one symptom -- every non-ASCII character has the
# same problem, and the movies indexer has no branch at all.
#
# The fix generalises theirs: one module-level helper that tries the stock
# `%` substitution first and only falls back to a literal replacement when
# the string turns out not to be a valid format string. Every URL that works
# today keeps its exact current behaviour, byte for byte; a URL that used to
# raise now gets its key substituted and is actually fetched. If the string
# is malformed for a reason we do NOT understand (not exactly one `%s`), the
# original exception is re-raised so the caller behaves as it does today.
#
# Marker-gated, compile()-checked before writing, atomic, revertible,
# re-applied on every boot so an Umbrella self-update cannot strip it.
# No-op when Umbrella is not installed.

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


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
TMDB_REL_PATH = 'resources/lib/indexers/tmdb.py'

MARKER = 'AI_SUBS_UMB_TMDB_APIKEY_v1'
HELPER_NAME = '_ai_apikey'

# The helper goes in at module level, immediately before the first class that
# uses it. `class TMDb:` is the base of every indexer class in the file.
#
# The `\r?` is not decoration. Upstream Umbrella ships this file LF, but the
# Umbrella pack THIS BUILD installs ships it CRLF -- and `$` in MULTILINE
# matches before a `\n`, not before a `\r`. Without the `\r?` the anchor
# matches the copy you download from GitHub and misses the copy that is
# actually on the user's device, which is exactly how the first attempt at
# this fix shipped doing nothing. Both spellings have to work here, because
# the same device flips from one to the other the moment Umbrella updates
# itself from its own repository.
_HELPER_ANCHOR_RE = re.compile(r'^class TMDb:[ \t]*\r?$', re.MULTILINE)

_HELPER_LINES = (
    '# ' + MARKER,
    'def ' + HELPER_NAME + '(_u, _k):',
    '\t"""Substitute the TMDb api_key into a url without letting percent-',
    '\tencoded query text (Hebrew -> %D7%9E..., an apostrophe -> %27) be',
    '\tread as format specifiers. Identical to `_u % _k` whenever that',
    '\tworks; the original error is re-raised for anything unexpected."""',
    '\ttry:',
    '\t\treturn _u % _k',
    '\texcept (TypeError, ValueError):',
    '\t\tif not isinstance(_u, str) or _u.count(\'%s\') != 1: raise',
    '\t\treturn _u.replace(\'%s\', _k)',
    '# END ' + MARKER,
)

# The trailing run is `(?:\r?\n)+`, not `\r?\n+`: the second spelling eats one
# CRLF and then stalls, because `\n+` cannot cross the next `\r`. That left the
# two blank lines behind on a CRLF file, so revert() was not byte-identical and
# every boot stacked another copy of the helper on top of the last.
_HELPER_REVERT_RE = re.compile(
    r'^#[ \t]*' + MARKER + r'[ \t]*\r?\n'
    r'(?:(?!#[ \t]*(?:END[ \t]+)?' + MARKER + r')[\s\S])*?'
    r'^#[ \t]*END[ \t]+' + MARKER + r'[ \t]*(?:\r?\n)+',
    re.MULTILINE,
)

# Every place the key is folded into a url held in a VARIABLE. String
# literals (`'...?api_key=%s' % self.API_key`) are left alone: they carry no
# user text, so they cannot hit this, and rewriting them would be noise.
_CALL_RE = re.compile(
    r'(?<![\w.])(?P<var>[A-Za-z_]\w*) % self\.API_key')
_CALL_REVERT_RE = re.compile(
    HELPER_NAME + r'\((?P<var>[A-Za-z_]\w*), self\.API_key\)')

# TVshows.tmdb_list's hand-rolled '%27' branch. With the helper in place it
# is dead weight, but it is also harmless and it is THEIR code -- we leave it
# exactly where it is. Removing it would make the revert non-trivial for no
# behavioural gain.


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_tmdb_apikey_patcher: ' + msg, level=level)
    except Exception:
        pass


def _tmdb_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, TMDB_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _invalidate_pyc(py_path):
    d = os.path.join(os.path.dirname(py_path), '__pycache__')
    if not os.path.isdir(d):
        return
    stem = os.path.basename(py_path)[:-3]
    try:
        names = os.listdir(d)
    except OSError:
        return
    for fn in names:
        if fn.startswith(stem + '.') and fn.endswith('.pyc'):
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass


def revert(content):
    """`content` with the edit removed, restoring upstream byte for byte."""
    out = _CALL_REVERT_RE.sub(
        lambda m: m.group('var') + ' % self.API_key', content)
    return _HELPER_REVERT_RE.sub('', out)


def ensure_patched():
    """Returns 'no_file' | 'read_failed' | 'unmatched' | 'compile_failed'
    | 'unchanged' | 'patched' | 'write_failed'. Never raises."""
    path = _tmdb_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    content = revert(original)

    m = _HELPER_ANCHOR_RE.search(content)
    if not m:
        _log('class TMDb anchor not found -- Umbrella may have changed; '
             'skipping', level='WARNING')
        return 'unmatched'

    eol = '\r\n' if '\r\n' in content[:4096] else '\n'
    helper = ''.join(ln + eol for ln in _HELPER_LINES) + eol + eol
    content = content[:m.start()] + helper + content[m.start():]

    # Rewrite the call sites AFTER the helper is in, so the count below
    # reflects the text we are actually about to write.
    content, n = _CALL_RE.subn(
        lambda mm: HELPER_NAME + '(' + mm.group('var') + ', self.API_key)',
        content)
    if not n:
        _log('no `<url> % self.API_key` call sites found -- skipping',
             level='WARNING')
        return 'unmatched'

    try:
        compile(content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'
    if content == original:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
    _invalidate_pyc(path)
    _log('non-ASCII TMDb search repaired ({0} call sites)'.format(n),
         level='INFO')
    return 'patched'
