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

MARKER = '# AI_SUBS_FAV_REFRESH_v2'
MARKER_MANAGE = '# AI_SUBS_FAV_REFRESH_MANAGE_v1'

# The safe v2 refresh line: container refresh only, no widget_refresh.
_REFRESH = 'container_refresh()  ' + MARKER \
    + ': refresh open list on add too (widget_refresh removed -- it crashed Kodi on add)'

# The exact tail the crashing v1 (0.2.70) appended after container_refresh().
# Stripping it turns a v1-patched line back into the safe v2 line.
_V1_TAIL = '; kodi_utils.widget_refresh()  # AI_SUBS_FAV_REFRESH' \
    ': refresh open list + home widgets on add too, not just remove'
_V1_TAIL_REPLACEMENT = '  ' + MARKER \
    + ': container refresh only (widget_refresh removed -- it crashed Kodi on add)'

# dialogs.py favorites_choice -- POV-local favorites. Original gated line
# (refresh stays False on add) -> unconditional refresh. Tabs match POV.
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
# an ADD shows immediately (POV only refreshed on remove, and Trakt/MDBList
# never refreshed at all). kodi_utils is already imported in this module.
_MANAGE_OLD = '\t\treturn self.execute_toggle(choice, action_add)\n'
_MANAGE_NEW = (
    '\t\t_ai_toggle_result = self.execute_toggle(choice, action_add)  '
    + MARKER_MANAGE + '\n'
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

    new_content = content
    applied = 0
    if _V1_TAIL in new_content:
        applied += new_content.count(_V1_TAIL)
        new_content = new_content.replace(_V1_TAIL, _V1_TAIL_REPLACEMENT)
    if _FAV_CHOICE_OLD in new_content:
        new_content = new_content.replace(_FAV_CHOICE_OLD, _FAV_CHOICE_NEW, 1)
        applied += 1

    if applied == 0:
        _log('dialogs.py: no favorites add-refresh anchor matched -- shape '
             'changed upstream, skipping', level='WARNING')
        return 'unmatched'
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
    if _MANAGE_OLD not in content:
        _log('list_helper.py: manage() toggle anchor not found -- shape '
             'changed upstream, skipping', level='WARNING')
        return 'unmatched'
    new_content = content.replace(_MANAGE_OLD, _MANAGE_NEW, 1)
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
