# Self-healing patch of POV's modules/dialogs.py so that ADDING an
# item to a list refreshes the open container -- not just removing.
#
# Symptom users hit: open "My Movies"/"My Shows" (or any TMDB
# Favorites / Watchlist / custom list / POV-local favorites list),
# add a title from the context menu, get the "added" notification --
# but the item doesn't appear. It only shows up after navigating
# away and back. Removing an item, by contrast, refreshes instantly.
#
# Root cause (POV core, identical across every shipped POV version):
# in modules/dialogs.py the container refresh after a successful
# write is gated on the REMOVE branch only:
#   - tmdb_manager_choice (favorites/watchlist):  `if not action: container_refresh()`
#   - tmdb_manager_choice (custom list):          `if not action: container_refresh()`
#   - favorites_choice    (POV-local favorites):  `if refresh: container_refresh()`  (refresh stays False on add)
# `action`/`refresh` is True/None-ish on add, so container_refresh()
# never fires on add. The list cache IS busted on add (clear_tmdbl_cache
# for TMDB, direct DB write for POV-local), so a fresh navigation shows
# the item -- but the currently-open container is never reloaded.
#
# Fix: drop the gate so the refresh fires on add as well as remove
# (mirroring how it already behaves on remove), and also call POV's
# own kodi_utils.widget_refresh() so the *home-screen widget tiles*
# ("My Movies"/"My Shows") reload too -- Container.Refresh alone only
# reloads the open list, not a home widget. (POV uses widget_refresh()
# the same way in entry.py after a Trakt/MDBList sync.) Three surgical,
# context-anchored string replacements; idempotent via a marker.
#
# Self-healing: ensure_patched() runs every Kodi startup. If upstream
# POV rewrites dialogs.py and wipes our marker we re-apply; if the
# surrounding shape changed so our anchors no longer match we skip
# that anchor silently and log -- POV keeps working, the add just
# goes back to needing a manual refresh.

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

MARKER = '# AI_SUBS_FAV_REFRESH'

# Each entry: (old_substring, new_substring). The old strings are
# anchored with their neighbouring lines so each match is unique
# (two of them share the literal `if not action: container_refresh()`
# but at different indentation / context). Tabs match POV's source.
_REFRESH = 'container_refresh(); kodi_utils.widget_refresh()  ' + MARKER \
    + ': refresh open list + home widgets on add too, not just remove'

REPLACEMENTS = (
    # tmdb_manager_choice -- favorites / watchlist add+remove
    (
        '\t\t\ttmdb_api.clear_tmdbl_cache()\n'
        '\t\t\tif not action: container_refresh()\n'
        '\t\t\treturn notification(32576)',
        '\t\t\ttmdb_api.clear_tmdbl_cache()\n'
        '\t\t\t' + _REFRESH + '\n'
        '\t\t\treturn notification(32576)',
    ),
    # tmdb_manager_choice -- custom list add+remove
    (
        '\t\ttmdb_api.clear_tmdbl_cache()\n'
        '\t\tif not action: container_refresh()\n'
        '\t\tnotification(32576)',
        '\t\ttmdb_api.clear_tmdbl_cache()\n'
        '\t\t' + _REFRESH + '\n'
        '\t\tnotification(32576)',
    ),
    # favorites_choice -- POV-local favorites add+remove
    (
        '\t\tnotification(32576) if action(mediatype, tmdb_id, title) else notification(32574)\n'
        '\t\tif refresh: container_refresh()',
        '\t\tnotification(32576) if action(mediatype, tmdb_id, title) else notification(32574)\n'
        '\t\t' + _REFRESH,
    ),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_favorites_refresh_patcher: ' + msg, level=level)
    except Exception:
        pass


def _dialogs_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, DIALOGS_REL_PATH)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Make container_refresh() fire on add as well as remove in POV's
    dialogs.py. Idempotent (skip if marker present), defensive (apply
    each anchor independently; skip+log any that no longer match).
    """
    path = _dialogs_path()
    if not path:
        _log('dialogs.py not found', level='INFO')
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER in content:
        return 'unchanged'

    new_content = content
    applied = 0
    missed = 0
    for old, new in REPLACEMENTS:
        if old in new_content:
            new_content = new_content.replace(old, new, 1)
            applied += 1
        else:
            missed += 1

    if applied == 0:
        _log('no add-refresh anchors matched -- dialogs.py shape '
             'changed upstream, skipping', level='WARNING')
        return 'unmatched'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('patched {0}/{1} add-refresh anchors (missed {2})'.format(
            applied, len(REPLACEMENTS), missed), level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
