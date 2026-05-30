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

MARKER = '# AI_SUBS_POV_BUILD_LOGGER_v1'


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


def _patch_one(base, rel, pyc_prefix, anchor):
    """Instrument the FIRST `except: pass` that follows `anchor` in the
    file at base/rel. Returns a status string."""
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

    anchor_b = anchor.encode('utf-8')
    a_idx = content.find(anchor_b)
    if a_idx == -1:
        _log('anchor not found in {0}; POV may have refactored'.format(rel),
             level='WARNING')
        return 'unmatched'

    # Find the bare `except: pass` that comes right after the anchor.
    # Match its exact indentation so we can replace in place.
    tail = content[a_idx:]
    m = re.search(rb'\n(?P<indent>[ \t]+)except:\s*pass', tail)
    if not m:
        _log('no bare `except: pass` after anchor in {0}'.format(rel),
             level='WARNING')
        return 'unmatched'

    indent = m.group('indent').decode('utf-8')
    # Replacement: keep catching + skipping the item (unchanged
    # behaviour), but log the exception + the id it died on first.
    replacement = (
        '\n' + indent + MARKER + '\n'
        + indent + 'except Exception as _e:\n'
        + indent + '\ttry: kodi_utils.logger("POV_BUILD_ITEM_ERROR",'
        ' "%s on tag=%s" % (repr(_e), repr(tag)))\n'
        + indent + '\texcept Exception: pass'
    )
    abs_start = a_idx + m.start()
    abs_end = a_idx + m.end()
    new_content = content[:abs_start] + replacement.encode('utf-8') \
        + content[abs_end:]

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
    """Instrument both movies.py and tvshows.py build bodies. Returns a
    short summary string. Never raises."""
    base = _pov_base()
    if not base or not os.path.isdir(base):
        return 'no_pov'
    results = []
    for rel, pyc_prefix, anchor in TARGETS:
        try:
            st = _patch_one(base, rel, pyc_prefix, anchor)
        except Exception as e:
            st = 'error:%r' % e
        results.append('%s=%s' % (pyc_prefix, st))
    summary = ', '.join(results)
    if any('=patched' in r for r in results):
        _log('instrumented build bodies (%s) -- next favorites open will '
             'log POV_BUILD_ITEM_ERROR with the real exception' % summary,
             level='INFO')
    return summary
