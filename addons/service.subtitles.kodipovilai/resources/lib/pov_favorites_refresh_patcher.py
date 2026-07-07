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
# (refresh stays False on add) -> guarded refresh. Tabs match POV.
_FAV_CHOICE_OLD = (
    '\t\tnotification(32576) if action(mediatype, tmdb_id, title) else notification(32574)\n'
    '\t\tif refresh: container_refresh()'
)
_FAV_CHOICE_NEW = (
    '\t\tnotification(32576) if action(mediatype, tmdb_id, title) else notification(32574)\n'
    '\t\t' + _REFRESH
)

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
    except OSError as e:
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
    elif _FAV_CHOICE_OLD in new_content:             # fresh POV -> guarded
        new_content = new_content.replace(_FAV_CHOICE_OLD, _FAV_CHOICE_NEW, 1)

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
    except OSError as e:
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
