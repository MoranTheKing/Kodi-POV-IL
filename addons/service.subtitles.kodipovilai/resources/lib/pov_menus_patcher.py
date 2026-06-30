# Adds our custom "My Movies" / "My Series" merged personal lists to POV by
# SURGICALLY injecting four list actions into plugin.video.pov's menu list
# builders -- instead of copying whole override files over POV (which is how
# this used to work and which broke hard when POV 6.07 refactored its menus
# from functions to classes: the stale 5.12-shaped override clobbered POV's
# good 6.07 movies.py/tvshows.py and emptied every list).
#
# The home-screen personal-area tiles (set by pov_navigator_patcher) point at
# the actions:
#     tmdb_my_movies / trakt_my_movies      (movies page)
#     tmdb_my_tvshows / trakt_my_tvshows    (tv shows page)
# POV has no such actions natively, so without this patch those tiles build an
# empty list. Each action is a MERGE of the user's personal lists:
#     tmdb_my_*  = TMDB favorites + watchlist        (dedup by tmdb id)
#     trakt_my_* = Trakt collection + watchlist + favorites (dedup by ids)
# mirroring exactly how POV's own tmdb_personal / trakt_personal branches
# fetch and shape their data, so everything downstream (threaded metadata
# build, sort, render) is reused untouched.
#
# Injection point: menus/movies.py and menus/tvshows.py, class Menu.run(),
# right before the dispatch chain `if self.action in Menu.tmdb_main:` -- we
# prepend our own `if self.action in (...):` branch and turn POV's leading
# `if` into an `elif`, so the chain stays intact and stock actions are
# byte-for-byte unchanged. Marker-gated, revert-then-reapply (so our own
# version bumps don't stack), compile()-checked before writing (never break
# POV), atomic, .pyc invalidated, re-applied every boot.
#
# Defensive no-ops: if POV isn't installed, if the anchor is absent (POV
# refactored again -> the tiles just fall back to POV's empty list until we
# re-anchor), or if the file still carries our OLD whole-file override
# (`_flex_call`) -- in which case the next POV self-update restores POV's
# native menu file and this injector takes over on the boot after that.

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

MARKER = '# AI_SUBS_POV_MY_LISTS_v1'
# Substring that only our OLD whole-file override carries; if we see it, the
# device file is the stale override sitting on a 6.07 core -- don't touch it,
# the next POV self-update restores the native file.
STALE_OVERRIDE_MARK = '_flex_call'

# (relative path, tmdb media-type, trakt media-type, action suffix)
TARGETS = (
    ('resources/lib/menus/movies.py', 'movie', 'movies', 'movies'),
    ('resources/lib/menus/tvshows.py', 'tv', 'shows', 'tvshows'),
)

# POV's dispatch chain always opens with this line (3 tabs inside run()).
_ANCHOR = '\t\t\tif self.action in Menu.tmdb_main:'

# Strip a previously injected block (marker line .. the elif we converted the
# anchor into) so we can re-apply cleanly across our own version bumps.
_REVERT_RE = re.compile(
    r'[ \t]*' + re.escape(MARKER) + r'\n.*?\n\t\t\telif self\.action in Menu\.tmdb_main:',
    re.DOTALL,
)


_BLOCK_TEMPLATE = (
    '\t\t\t{marker}\n'
    "\t\t\tif self.action in ('tmdb_my_{suffix}', 'trakt_my_{suffix}'):\n"
    '\t\t\t\ttry:\n'
    "\t\t\t\t\tif self.action[:5] == 'tmdb_':\n"
    '\t\t\t\t\t\tfrom indexers.tmdb_api import tmdb_favorites as _ai_f, tmdb_watchlist as _ai_w\n'
    '\t\t\t\t\t\t_ai_seen, _ai_list = set(), []\n'
    '\t\t\t\t\t\tfor _ai_fn in (_ai_f, _ai_w):\n'
    "\t\t\t\t\t\t\tfor _ai_i in _ai_fn('{tmdb}', page_no)[0]:\n"
    "\t\t\t\t\t\t\t\tif _ai_i['id'] not in _ai_seen:\n"
    "\t\t\t\t\t\t\t\t\t_ai_seen.add(_ai_i['id']); _ai_list.append(_ai_i['id'])\n"
    '\t\t\t\t\t\tself.list = _ai_list\n'
    '\t\t\t\t\telse:\n'
    "\t\t\t\t\t\tself.id_type = 'trakt_dict'\n"
    '\t\t\t\t\t\tfrom indexers.trakt_api import trakt_collection as _ai_c, trakt_watchlist as _ai_tw, trakt_favorites as _ai_tf\n'
    '\t\t\t\t\t\t_ai_seen, _ai_list = set(), []\n'
    '\t\t\t\t\t\tfor _ai_fn in (_ai_c, _ai_tw, _ai_tf):\n'
    "\t\t\t\t\t\t\tfor _ai_i in _ai_fn('{trakt}', page_no)[0]:\n"
    "\t\t\t\t\t\t\t\t_ai_k = _ai_i['media_ids'].get('tmdb') or _ai_i['media_ids'].get('imdb') or repr(_ai_i['media_ids'])\n"
    '\t\t\t\t\t\t\t\tif _ai_k not in _ai_seen:\n'
    "\t\t\t\t\t\t\t\t\t_ai_seen.add(_ai_k); _ai_list.append(_ai_i['media_ids'])\n"
    '\t\t\t\t\t\tself.list = _ai_list\n'
    '\t\t\t\texcept Exception: pass\n'
    '\t\t\telif self.action in Menu.tmdb_main:'
)


def _block(tmdb_mt, trakt_mt, suffix):
    """The injected branch for one file. 3-tab base indent (run() body)."""
    return _BLOCK_TEMPLATE.format(
        marker=MARKER, suffix=suffix, tmdb=tmdb_mt, trakt=trakt_mt)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_menus_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_base():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''


def _invalidate_pyc(py_path):
    d = os.path.join(os.path.dirname(py_path), '__pycache__')
    if not os.path.isdir(d):
        return
    stem = os.path.basename(py_path)[:-3]
    for fn in os.listdir(d):
        if fn.startswith(stem + '.') and fn.endswith('.pyc'):
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass


def _patch_one(path, tmdb_mt, trakt_mt, suffix):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            original = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(path, e), level='WARNING')
        return 'read_failed'

    if STALE_OVERRIDE_MARK in original:
        _log('{0}: stale whole-file override detected -- leaving for POV '
             'self-update to restore native menu, will inject next boot'
             .format(os.path.basename(path)), level='WARNING')
        return 'stale_override'

    # Revert any prior injection so we re-apply our current version cleanly.
    content = _REVERT_RE.sub('\t\t\tif self.action in Menu.tmdb_main:', original)

    if _ANCHOR not in content:
        _log('{0}: dispatch anchor not found -- POV may have changed; '
             'skipping'.format(os.path.basename(path)), level='WARNING')
        return 'unmatched'

    content = content.replace(_ANCHOR, _block(tmdb_mt, trakt_mt, suffix), 1)

    # SAFETY: never write a file that doesn't compile.
    try:
        compile(content, path, 'exec')
    except SyntaxError as e:
        _log('{0}: patched content would not compile -- skipping ({1})'
             .format(os.path.basename(path), e), level='WARNING')
        return 'compile_failed'

    if content == original:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(os.path.basename(path), e),
             level='WARNING')
        return 'write_failed'
    _invalidate_pyc(path)
    return 'patched'


def ensure_patched():
    """Inject the merged My Movies / My Series personal-list actions into
    POV's movies.py and tvshows.py list builders. Returns a {filename:
    status} dict. Never raises."""
    base = _pov_base()
    if not base or not os.path.isdir(base):
        return {'_status': 'no_pov'}

    results = {}
    for rel, tmdb_mt, trakt_mt, suffix in TARGETS:
        path = os.path.join(base, *rel.split('/'))
        name = os.path.basename(path)
        if not os.path.isfile(path):
            results[name] = 'no_target'
            continue
        results[name] = _patch_one(path, tmdb_mt, trakt_mt, suffix)

    if any(v == 'patched' for v in results.values()):
        _log('injected merged personal-list actions ({0})'.format(
            ', '.join('%s=%s' % (k, v) for k, v in results.items())),
            level='INFO')
    return results
