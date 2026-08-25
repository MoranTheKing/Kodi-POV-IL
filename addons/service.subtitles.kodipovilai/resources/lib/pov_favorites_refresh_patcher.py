# Self-healing patch so that ADDING an item to a list refreshes the open
# container -- not just removing.
#
# Symptom users hit: open "My Movies"/"My Shows" (or any TMDB/Trakt/MDBList
# Favorites / Watchlist / custom list / POV-local favorites list), add a
# title from the context menu, get the "added" notification -- but the item
# doesn't appear. It only shows up after navigating away and back. Removing
# an item, by contrast, refreshes instantly.
#
# Root cause: POV's list-manager flow only fires container_refresh() on the
# REMOVE branch. The list cache IS busted on add, so a fresh navigation
# shows the item -- but the currently-open container is never reloaded.
#
# POV 6.07 refactored the three per-service "manager_choice" functions
# (modules/dialogs.py) into manager classes that all share one entry point:
#   indexers/list_helper.py  BaseListManager.manage()
#     -> return self.execute_toggle(choice, action_add)
# so the unified, version-resilient fix is to refresh right after that
# toggle (covers TMDB / Trakt / MDBList add AND remove in one place). The
# POV-local Favorites path is separate (modules/dialogs.py favorites_choice)
# and still carries the old `if refresh: container_refresh()` add-gate, so we
# keep patching that site too.
#
# v2 history -- IMPORTANT: an early version (AI subs 0.2.70) ALSO called
# POV's kodi_utils.widget_refresh() here, which CRASHED Kodi when adding to
# a list. We removed that; this patcher also heals installs that still carry
# the crashing line.
#
# Self-healing: ensure_patched() runs every Kodi startup. Each file is
# patched independently and idempotently (own marker), atomic write, and
# skipped+logged if the upstream shape changed.

import os
import re as _re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
DIALOGS_REL_PATH = 'resources/lib/modules/dialogs.py'
LIST_HELPER_REL_PATH = 'resources/lib/indexers/list_helper.py'

MARKER = '# AI_SUBS_FAV_REFRESH_v3'
MARKER_MANAGE = '# AI_SUBS_FAV_REFRESH_MANAGE_v2'

# v3 change: the refresh is now GUARDED. Firing Container.Refresh after an add
# re-invokes the OPEN container's plugin GetDirectory. For a normal browse list
# (saved TMDB/Trakt/MDBList list, watchlist, genre, popular) that re-fetch is
# cheap and correct -- it's what makes the added item appear. But when the open
# container is a SEARCH-results list (e.g. .../?mode=build_tvshow_list&
# action=tmdb_tv_search&query=...), re-running that GetDirectory re-entrantly
# from the add-to-list RunPlugin FAILS ("Error getting plugin://") / crashes
# the screen -- and refreshing a search wouldn't show the added item anyway
# (you're viewing search results, not the list). So we skip the refresh when
# the open container path is a search. Reading Container.FolderPath via
# __import__('xbmc') needs no extra import in the patched module.
_GUARD = ("if 'search' not in "
          "(__import__('xbmc').getInfoLabel('Container.FolderPath') or '').lower(): ")

# The guarded v3 refresh (container refresh only, and not for search).
_REFRESH = _GUARD + 'container_refresh()  ' + MARKER \
    + ': refresh open list on add, but NOT for search containers'

# ---- prior forms we upgrade from (so already-patched devices get the guard) ----
# Legacy crashing v1 (0.2.70) line (container_refresh + widget_refresh).
_FAV_V1 = ('container_refresh(); kodi_utils.widget_refresh()  # AI_SUBS_FAV_REFRESH'
           ': refresh open list + home widgets on add too, not just remove')
# v2 line (container refresh only, UNguarded).
_FAV_V2 = ('container_refresh()  # AI_SUBS_FAV_REFRESH_v2'
           ': refresh open list on add too (widget_refresh removed -- it crashed Kodi on add)')

# dialogs.py favorites_choice -- POV-local favorites. Original gated line
# (refresh stays False on add) -> guarded refresh.
#
# MATCHED AS A PATTERN, NOT A LITERAL, AND THAT IS THE POINT. This was two
# exact strings with two tabs of indentation and `action(mediatype, tmdb_id,
# title)`. POV 6.08.12 changed BOTH: it moved favourites into the new
# indexers/local_api.py, so the call became `action('favorites', mediatype,
# tmdb_id, title)`, and it flattened the enclosing block, so the indentation
# dropped to one tab. The literal stopped matching and the device log said so
# every boot -- "no favorites add-refresh anchor matched" -- while the feature
# quietly did nothing.
#
# Swapping in a new literal would buy exactly one POV release. What actually
# identifies this line is its SHAPE: notification(32576) on success of some
# action(...) call, notification(32574) otherwise, followed by the gated
# refresh on the next line at the same indentation. That is what we match, so
# a further argument or a change of nesting cannot break it again.
#
# The indentation is captured and reused rather than assumed, and the sibling
# dropped_choice() that 6.08.12 added is NOT touched: it calls
# container_refresh() unconditionally already, so it needs nothing from us --
# and requiring `if refresh:` in the pattern is what keeps us out of it.
#
# AND THEN POV 6.08.14 CHANGED THE NOTIFY CALLS, which is the second time this
# line has moved and exactly what the paragraph above predicted:
#
#   6.08.13  notification(32576) if action(...) else notification(32574)
#   6.08.14  kodi_utils.notify_success() if action(...) else kodi_utils.notify_error()
#
# The identifying shape is unchanged -- a success/failure expression over one
# action(...) call, with the gated refresh underneath at the same indentation.
# So the notify halves are matched loosely (any call that is not `action(`)
# and the STRUCTURE carries the identification, which is what the pattern was
# for. The `if refresh: container_refresh()` line underneath is what actually
# pins it: nothing else in dialogs.py has it.
_FAV_CHOICE_RE = _re.compile(
    r'^(?P<ind>[ \t]+)(?P<ok>[A-Za-z_][A-Za-z0-9_.]*\([^\n()]*\))'
    r' if action\((?P<args>[^\n()]*)\) else '
    r'(?P<bad>[A-Za-z_][A-Za-z0-9_.]*\([^\n()]*\))\n'
    r'(?P=ind)if refresh: container_refresh\(\)$', _re.M)


def _fav_choice_sub(match):
    """Keep POV's own line verbatim; replace only the refresh under it."""
    return (match.group(0).split('\n')[0] + '\n'
            + match.group('ind') + _REFRESH)

# indexers/list_helper.py BaseListManager.manage() -- the single shared toggle
# point for TMDB / Trakt / MDBList managers. Refresh right after the toggle so
# an ADD shows immediately (POV only refreshed on remove), but guarded so a
# search container is never re-fetched. kodi_utils is imported in this module.
_MANAGE_OLD = '\t\treturn self.execute_toggle(choice, action_add)\n'
_MANAGE_NEW = (
    '\t\t_ai_toggle_result = self.execute_toggle(choice, action_add)  '
    + MARKER_MANAGE + '\n'
    '\t\t' + _GUARD + 'kodi_utils.container_refresh()\n'
    '\t\treturn _ai_toggle_result\n'
)
# The prior UNguarded v1 manage block (upgrade it to the guarded v2 block).
_MANAGE_V1 = (
    '\t\t_ai_toggle_result = self.execute_toggle(choice, action_add)  '
    '# AI_SUBS_FAV_REFRESH_MANAGE_v1\n'
    '\t\tkodi_utils.container_refresh()\n'
    '\t\treturn _ai_toggle_result\n'
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_favorites_refresh_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _write(path, new_content):
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        return True
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e), level='WARNING')
        return False


def _patch_dialogs():
    """POV-local favorites add-refresh in modules/dialogs.py. Also heals the
    crashing v1 widget_refresh line if present. Returns a short status."""
    path = _pov_path(DIALOGS_REL_PATH)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        _log('dialogs read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER in content:
        return 'unchanged'

    # Normalise whatever prior form is present to the guarded v3 refresh.
    new_content = content
    if _FAV_V1 in new_content:                       # legacy crashing v1
        new_content = new_content.replace(_FAV_V1, _REFRESH)
    elif _FAV_V2 in new_content:                     # unguarded v2 -> guarded
        new_content = new_content.replace(_FAV_V2, _REFRESH)
    else:                                            # fresh POV -> guarded
        hits = len(_FAV_CHOICE_RE.findall(new_content))
        if hits == 1:
            new_content = _FAV_CHOICE_RE.sub(_fav_choice_sub, new_content, 1)
        elif hits > 1:
            # Two call sites matching this shape means POV grew a second one we
            # have not looked at. Patching "the first" would be a guess.
            _log('dialogs.py: favorites add-refresh shape matched {0} times, '
                 'expected 1 -- not editing'.format(hits), level='WARNING')

    if new_content == content:
        _log('dialogs.py: no favorites add-refresh anchor matched -- shape '
             'changed upstream, skipping', level='WARNING')
        return 'unmatched'
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('dialogs.py: patched content would not compile -- skipping '
             '({0})'.format(e), level='WARNING')
        return 'compile_failed'
    return 'patched' if _write(path, new_content) else 'write_failed'


def _patch_list_helper():
    """Unified TMDB/Trakt/MDBList manager add-refresh in
    indexers/list_helper.py BaseListManager.manage(). Returns a short
    status."""
    path = _pov_path(LIST_HELPER_REL_PATH)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        _log('list_helper read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER_MANAGE in content:
        return 'unchanged'
    if _MANAGE_V1 in content:                        # unguarded v1 -> guarded v2
        new_content = content.replace(_MANAGE_V1, _MANAGE_NEW, 1)
    elif _MANAGE_OLD in content:                     # fresh POV -> guarded v2
        new_content = content.replace(_MANAGE_OLD, _MANAGE_NEW, 1)
    else:
        _log('list_helper.py: manage() toggle anchor not found -- shape '
             'changed upstream, skipping', level='WARNING')
        return 'unmatched'
    # SAFETY: never write a file that doesn't compile.
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('list_helper.py: patched content would not compile -- '
             'skipping ({0})'.format(e), level='WARNING')
        return 'compile_failed'
    return 'patched' if _write(path, new_content) else 'write_failed'


def ensure_patched():
    """Make the open container refresh on add as well as remove, across both
    POV's list-manager classes (list_helper.py) and the POV-local favorites
    path (dialogs.py). Idempotent, defensive, never raises."""
    d = _patch_dialogs()
    m = _patch_list_helper()
    summary = 'dialogs={0}, manage={1}'.format(d, m)
    if 'patched' in (d, m):
        _log('add-refresh applied (' + summary + ')', level='INFO')
    return summary
