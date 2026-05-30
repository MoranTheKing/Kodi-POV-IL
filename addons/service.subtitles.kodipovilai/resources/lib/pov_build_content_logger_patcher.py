# Instrument POV's per-item list builders so the SWALLOWED exception
# that empties favorites lists becomes visible in kodi.log.
#
# Why this exists (after a very long diagnostic chain):
#   The favorites lists (TMDB / Trakt / POV-local, movies AND shows)
#   render EMPTY, while normal browsing works. We proved on-device:
#     - auth valid, live GET /3/movie/<fav> returns 200
#     - watched.db path correct, get_favorites returns all 6 rows
#     - movie_meta(<fav id>) returns a FULL meta dict (all keys present,
#       blank_entry False) and every meta-dependent op we replayed
#       offline (director/genre/writer.split, country, duration) works.
#   So build_movie_content SHOULD succeed -- yet the live list is empty
#   in ~218ms. The only way that happens: build_movie_content raises in
#   the LIVE Kodi context (one of the listitem ops we cannot simulate
#   offline -- make_listitem / setArt / getVideoInfoTag / setCast /
#   setCountries / setRating / etc.) and the error is eaten by the bare
#   `except: pass` at the end of the method (menus/movies.py:174,
#   menus/tvshows.py:183).
#
# This patcher rewrites those two bare `except: pass` lines into
#   `except Exception as e: kodi_utils.logger('POV_BUILD_ITEM_ERROR', ...)`
# so the NEXT time a favorites list is opened, kodi.log contains the
# exact exception type, message, and the tmdb_id it died on. That single
# log line identifies the bug precisely -- no more guessing.
#
# It changes NO behaviour other than logging (the except still catches
# and the item is still skipped, exactly as before). Marker-gated,
# idempotent, atomic write, drops stale .pyc. Logs WARNING and leaves
# the file alone if the expected shape isn't found (POV refactor guard).

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
# (relative path, pyc prefix, the unique line that ENDS the build body
# and immediately precedes the bare `except: pass` we want to instrument)
TARGETS = (
    ('resources/lib/menus/movies.py', 'movies',
     'self.append((url_params, listitem, False))'),
    ('resources/lib/menus/tvshows.py', 'tvshows',
     'self.append((url_params, listitem, self.is_folder))'),
)

# v2: also instrument run()'s OUTER `except: pass` -- the one that wraps
# the whole method (import of the read function, the function() call, the
# list comprehension, AND build_*_results incl. the .sort() at
# movies.py:189). favorites lists come back empty in ~213ms with NO
# POV_BUILD_ITEM_ERROR, which means the failure is OUTSIDE
# build_*_content -- caught here. This except sits immediately BEFORE the
# `kodi_utils.set_category(...)` line, so we locate it by that follower.
OUTER_TARGETS = (
    ('resources/lib/menus/movies.py', 'movies',
     'kodi_utils.set_category(__handle__, ls(params_get('),
    ('resources/lib/menus/tvshows.py', 'tvshows',
     'kodi_utils.set_category(__handle__, ls(params_get('),
)

MARKER = '# AI_SUBS_POV_BUILD_LOGGER_v2'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_build_content_logger_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _pov_base():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''


def _make_replacement(indent, label, ctx_expr):
    """Build the `except Exception as _e: log` block at `indent`.
    label distinguishes ITEM vs RUN; ctx_expr is a python expr (bytes-
    safe text) giving extra context, evaluated under its own try."""
    return (
        '\n' + indent + MARKER + '\n'
        + indent + 'except Exception as _e:\n'
        + indent + '\ttry: kodi_utils.logger("' + label + '",'
        ' "%s | %s" % (repr(_e), ' + ctx_expr + '))\n'
        + indent + '\texcept Exception: pass'
    )


def _patch_file(base, rel, pyc_prefix, item_anchor, outer_anchor):
    """Instrument BOTH the per-item build except (after item_anchor) and
    run()'s outer except (the bare `except: pass` immediately BEFORE
    outer_anchor) in one read/write. Returns a status string."""
    path = os.path.join(base, rel)
    if not os.path.isfile(path):
        return 'no_file'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(rel, e), level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    # --- (1) per-item except: first bare `except: pass` AFTER item_anchor
    ia = content.find(item_anchor.encode('utf-8'))
    if ia == -1:
        _log('item anchor not found in {0}'.format(rel), level='WARNING')
        return 'unmatched'
    m_item = re.search(rb'\n(?P<indent>[ \t]+)except:\s*pass', content[ia:])
    if not m_item:
        _log('no item `except: pass` in {0}'.format(rel), level='WARNING')
        return 'unmatched'
    item_start = ia + m_item.start()
    item_end = ia + m_item.end()
    item_indent = m_item.group('indent').decode('utf-8')

    # --- (2) outer except: the bare `except: pass` immediately BEFORE
    # outer_anchor (set_category line). Search the region preceding it.
    oa = content.find(outer_anchor.encode('utf-8'))
    if oa == -1:
        _log('outer anchor not found in {0}'.format(rel), level='WARNING')
        return 'unmatched'
    # last `except: pass` before oa
    outer_matches = list(re.finditer(
        rb'\n(?P<indent>[ \t]+)except:\s*pass', content[:oa]))
    if not outer_matches:
        _log('no outer `except: pass` in {0}'.format(rel), level='WARNING')
        return 'unmatched'
    m_outer = outer_matches[-1]
    outer_start = m_outer.start()
    outer_end = m_outer.end()
    outer_indent = m_outer.group('indent').decode('utf-8')

    item_repl = _make_replacement(
        item_indent, 'POV_BUILD_ITEM_ERROR', '"tag=%s" % repr(tag)').encode(
        'utf-8')
    outer_repl = _make_replacement(
        outer_indent, 'POV_RUN_ERROR',
        '"action=%s list_len=%s" % (repr(self.action),'
        ' repr(len(getattr(self, "list", []))))').encode('utf-8')

    # Apply the LATER offset first so earlier offsets stay valid. The
    # item except (line ~174) comes before the outer except (line ~319),
    # so replace outer first.
    if outer_start > item_start:
        new_content = (content[:outer_start] + outer_repl
                       + content[outer_end:])
        new_content = (new_content[:item_start] + item_repl
                       + new_content[item_end:])
    else:
        new_content = (content[:item_start] + item_repl
                       + content[item_end:])
        new_content = (new_content[:outer_start] + outer_repl
                       + new_content[outer_end:])

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(rel, e), level='WARNING')
        return 'write_failed'

    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith(pyc_prefix + '.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass
    return 'patched'


def ensure_patched():
    """Instrument both the per-item and outer excepts in movies.py and
    tvshows.py. Returns a short summary string. Never raises."""
    base = _pov_base()
    if not base or not os.path.isdir(base):
        return 'no_pov'
    item_map = {t[1]: t[2] for t in TARGETS}
    outer_map = {t[1]: t[2] for t in OUTER_TARGETS}
    rel_map = {t[1]: t[0] for t in TARGETS}
    results = []
    for pyc_prefix in ('movies', 'tvshows'):
        try:
            st = _patch_file(base, rel_map[pyc_prefix], pyc_prefix,
                             item_map[pyc_prefix], outer_map[pyc_prefix])
        except Exception as e:
            st = 'error:%r' % e
        results.append('%s=%s' % (pyc_prefix, st))
    summary = ', '.join(results)
    if any('=patched' in r for r in results):
        _log('instrumented item+outer excepts (%s) -- next favorites open '
             'logs POV_BUILD_ITEM_ERROR and/or POV_RUN_ERROR' % summary,
             level='INFO')
    return summary
