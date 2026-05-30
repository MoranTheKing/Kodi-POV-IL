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
# Fix: drop the gate so container_refresh() fires on add as well as
# remove (mirroring how it already behaves on remove).
#
# v2 history -- IMPORTANT: v1 (AI subs 0.2.70) ALSO called POV's
# kodi_utils.widget_refresh() here to reload the home-screen widget
# tiles. That turned out to CRASH Kodi when adding to a list (its
# UpdateLibrary(video, special://skin/foo) trick is why POV itself
# gates widget_refresh behind an opt-in setting and never calls it
# from a context-menu action). v2 removes the widget_refresh() call
# entirely and keeps only container_refresh() -- exactly what POV
# already does safely on remove, just extended to add. The home
# widget tile still refreshes on the next return to the home screen
# because the list cache is busted on add. This patcher also heals
# installs that already received the crashing v1 line.
#
# Self-healing: ensure_patched() runs every Kodi startup. Idempotent
# via the v2 marker; converts both pristine POV and any v1-patched
# install to the safe v2 form; skips+logs if upstream shape changed.

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

MARKER = '# AI_SUBS_FAV_REFRESH_v2'

# The safe v2 refresh line: container refresh only, no widget_refresh.
_REFRESH = 'container_refresh()  ' + MARKER \
    + ': refresh open list on add too (widget_refresh removed -- it crashed Kodi on add)'

# The exact tail the crashing v1 (0.2.70) appended after container_refresh().
# Stripping it turns a v1-patched line back into the safe v2 line.
_V1_TAIL = '; kodi_utils.widget_refresh()  # AI_SUBS_FAV_REFRESH' \
    ': refresh open list + home widgets on add too, not just remove'
_V1_TAIL_REPLACEMENT = '  ' + MARKER \
    + ': container refresh only (widget_refresh removed -- it crashed Kodi on add)'

# Pristine-POV anchors: original gated line -> safe v2 line. Anchored
# with neighbouring lines so each of the three sites is unique. Tabs
# match POV's source.
REPLACEMENTS = (
    # tmdb_manager_choice -- favorites / watchlist
    (
        '\t\t\ttmdb_api.clear_tmdbl_cache()\n'
        '\t\t\tif not action: container_refresh()\n'
        '\t\t\treturn notification(32576)',
        '\t\t\ttmdb_api.clear_tmdbl_cache()\n'
        '\t\t\t' + _REFRESH + '\n'
        '\t\t\treturn notification(32576)',
    ),
    # tmdb_manager_choice -- custom list
    (
        '\t\ttmdb_api.clear_tmdbl_cache()\n'
        '\t\tif not action: container_refresh()\n'
        '\t\tnotification(32576)',
        '\t\ttmdb_api.clear_tmdbl_cache()\n'
        '\t\t' + _REFRESH + '\n'
        '\t\tnotification(32576)',
    ),
    # favorites_choice -- POV-local favorites
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
    dialogs.py, WITHOUT the crashing widget_refresh() call. Heals both
    pristine POV and any install that received the v1 (0.2.70) line.
    Idempotent (skip if v2 marker present), defensive (apply each
    transform independently; skip+log if nothing matches).
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

    # Step 1: heal any crashing v1 line (remove widget_refresh, retag v2).
    if _V1_TAIL in new_content:
        n = new_content.count(_V1_TAIL)
        new_content = new_content.replace(_V1_TAIL, _V1_TAIL_REPLACEMENT)
        applied += n

    # Step 2: patch any still-pristine gated lines straight to v2.
    for old, new in REPLACEMENTS:
        if old in new_content:
            new_content = new_content.replace(old, new, 1)
            applied += 1

    if applied == 0:
        _log('no add-refresh anchors matched (pristine or v1) -- '
             'dialogs.py shape changed upstream, skipping', level='WARNING')
        return 'unmatched'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('healed/patched {0} add-refresh site(s) to safe v2 '
             '(container_refresh only)'.format(applied), level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
