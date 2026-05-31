# Repoint Arctic Fuse 3's DISCOVER GRID (window 1105 / container 501)
# from TMDbHelper to POV, so it shows Hebrew POV content with posters and
# clicking an item plays through POV's source scraping.
#
# The search ROWS were already repointed (af3_search_pov_patcher +
# searchwidgets node) and work. This handles the discover GRID, which is
# wired differently and more deeply to TMDbHelper. Two skin files:
#
# 1) Custom_1105_Search.xml line 3 -- the window's onload sets the grid's
#    content path. Default points at TMDbHelper:
#      SetProperty(TMDbHelper.UserDiscover.FolderPath,
#        plugin://plugin.video.themoviedb.helper/?info=discover&with_id=
#        True&tmdb_type=movie, Home)
#    We change ONLY the path to POV popular movies (Hebrew, warm posters):
#      plugin://plugin.video.pov/?mode=build_movie_list&
#        action=tmdb_movies_popular&name=32461&iconImage=dvd.png
#    (We patch the onload itself -- deterministic -- instead of racing to
#    pre-seed the Home property from the service at boot, which the
#    _is_af3_active() gate made unreliable.)
#    Line 4 sets the grid's display name; we set it to a Hebrew label.
#
# 2) Includes_Search.xml line 54 -- the grid's content binding appends a
#    TMDbHelper-only suffix:
#      $INFO[...folderpath]$INFO[Control.GetLabel(3000).index(1),
#        &with_text_query=,]
#    POV doesn't understand &with_text_query, so as soon as the user types
#    in the search box the grid path becomes invalid. We strip the suffix
#    so the grid stays a clean POV popular grid (the POV search ROWS, not
#    this grid, serve typed queries). Result: the grid is a stable Hebrew
#    POV "discover/popular" row, clickable straight into POV sources.
#
# Marker-gated, idempotent, atomic, re-applied each startup (a skin update
# re-ships the originals). Exact-string match; safe no-op if AF3 absent or
# the lines changed.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


AF3_SKIN_ID = 'skin.arctic.fuse.3'
CUSTOM_1105_REL = 'addons/' + AF3_SKIN_ID + '/1080i/Custom_1105_Search.xml'
INCLUDES_SEARCH_REL = 'addons/' + AF3_SKIN_ID + '/1080i/Includes_Search.xml'

MARKER = '<!-- AI_SUBS_POV_DISCOVER_v5_rollback -->'
# Older markers (our #207 v1 + Codex's broken v2/v3). When any of these is
# present we STRIP it and re-apply, so a device stuck on a Codex build is
# forced back to the #207 target. This is the "restore to PR #207 even for
# existing users" guarantee.
OLD_MARKERS = (
    '<!-- AI_SUBS_POV_DISCOVER_v1 -->',
    '<!-- AI_SUBS_POV_DISCOVER_v2 -->',
    '<!-- AI_SUBS_POV_DISCOVER_v3 -->',
)

# The POV grid path the discover grid should show (popular movies, Hebrew,
# posters warm from normal browsing). '&' is plain here -- this is the
# value of a SetProperty inside an onload, same escaping as the original
# TMDbHelper line (which uses &amp; in XML for the literal &).
_POV_GRID_PATH = ('plugin://plugin.video.pov/?mode=build_movie_list'
                  '&amp;action=tmdb_movies_popular'
                  '&amp;name=32461&amp;iconImage=dvd.png')

# Codex's combined-search content paths it wrote into the skin (v2/v3).
# We must recognise them to roll a Codex device back to the #207 target.
_CODEX_V2_CONTENT = (
    'plugin://plugin.video.pov/?mode=ai_pov_combined_search'
    '&amp;name=Search%20Results&amp;query='
    '$VAR[Path_SearchTerm_SingleEncoded]')
_CODEX_V3_CONTENT = (
    'plugin://plugin.video.pov/?mode=ai_pov_combined_search'
    '&amp;media_type=all&amp;name=Discover&amp;query='
    '$VAR[Path_SearchTerm_SingleEncoded]')

# --- Custom_1105_Search.xml exact replacements (LF line endings) ---
_C1105_OLD_PATH = (
    'SetProperty(TMDbHelper.UserDiscover.FolderPath,'
    'plugin://plugin.video.themoviedb.helper/?info=discover'
    '&amp;with_id=True&amp;tmdb_type=movie,Home)')
_C1105_NEW_PATH = (
    'SetProperty(TMDbHelper.UserDiscover.FolderPath,'
    + _POV_GRID_PATH + ',Home)')
# The #207/Codex path is already the POV grid path -- so a device may
# already have _C1105_NEW_PATH in place. Accept BOTH the original
# TMDbHelper line and the already-POV line as the "from" state.
_C1105_PATH_CANDIDATES = (_C1105_OLD_PATH, _C1105_NEW_PATH)

_C1105_OLD_NAME = (
    'SetProperty(TMDbHelper.UserDiscover.FolderPath.Name,'
    '$LOCALIZE[467] $LOCALIZE[342],Home)')
_C1105_NEW_NAME = (
    'SetProperty(TMDbHelper.UserDiscover.FolderPath.Name,גלה,Home)')
_C1105_NAME_CANDIDATES = (_C1105_OLD_NAME, _C1105_NEW_NAME)

# --- Includes_Search.xml content (the #207 target = bare folderpath) ---
_INCSRCH_OLD_CONTENT = (
    '<param name="content">'
    '$INFO[window(home).property(tmdbhelper.userdiscover.folderpath)]'
    '$INFO[Control.GetLabel(3000).index(1),&amp;with_text_query=,]'
    '</param>')
_INCSRCH_NEW_CONTENT = (
    '<param name="content">'
    '$INFO[window(home).property(tmdbhelper.userdiscover.folderpath)]'
    '</param>')
# Codex replaced this with its combined-search content. Accept the
# original, our #207 target, and Codex's v2/v3 as the "from" state, and
# force them all to the #207 target.
_INCSRCH_CONTENT_CANDIDATES = (
    _INCSRCH_OLD_CONTENT,
    _INCSRCH_NEW_CONTENT,
    '<param name="content">' + _CODEX_V2_CONTENT + '</param>',
    '<param name="content">' + _CODEX_V3_CONTENT + '</param>',
)

# Codex also flipped the discover-tab onclick/visible (v3). Restore the
# stock TMDbHelper onclick + the stock visible expression (the #207 file
# never touched these, so the stock values are the target).
_INCSRCH_V3_ONCLICK = '<onclick>SetFocus(501)</onclick>'
_INCSRCH_STOCK_ONCLICK = (
    '<onclick>RunPlugin(plugin://plugin.video.themoviedb.helper/?info='
    'user_discover$INFO[Window(Home).Property(TMDbHelper.UserDiscover.'
    'Folderpath.ParamString),&amp;,])</onclick>')
_INCSRCH_V3_VISIBLE = '<visible>true</visible>'
_INCSRCH_STOCK_VISIBLE = (
    '<visible>!Integer.IsEqual(Container(501).NumItems,0)</visible>')



def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('af3_discover_pov_patcher: ' + msg, level=level)
    except Exception:
        pass


def _path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _patch_file(path, replacements, label):
    """Force the file to the #207 target from ANY prior state. Each
    replacement is (old, new) where `old` may be a string OR a tuple of
    candidate strings (the first present one is replaced). Already-correct
    replacements are skipped, not failed. Strips our old markers so a
    Codex device is re-rolled. Returns 'patched' | 'already_patched' |
    'unmatched' | 'read_failed' | 'write_failed'."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(label, e), level='WARNING')
        return 'read_failed'

    # Already at the current target AND no stale marker to clean up.
    has_old_marker = any(m in text for m in OLD_MARKERS)
    if MARKER in text and not has_old_marker:
        return 'already_patched'

    new_text = text
    # Drop our markers (current + old) so we can re-stamp cleanly.
    for m in (MARKER,) + OLD_MARKERS:
        new_text = new_text.replace(m + '\n', '').replace(m, '')

    any_change = False
    for old, new in replacements:
        candidates = old if isinstance(old, tuple) else (old,)
        if new in new_text:
            # already the target for this slot -- nothing to do
            any_change = True  # treat as satisfied
            continue
        matched = next((c for c in candidates if c in new_text), None)
        if matched is None:
            _log('{0}: no candidate for a slot found -- AF3 may have '
                 'changed this file; leaving it alone'.format(label),
                 level='WARNING')
            return 'unmatched'
        new_text = new_text.replace(matched, new, 1)
        any_change = True

    if not any_change:
        return 'unmatched'

    # stamp the current marker after the first '>' (root tag).
    g = new_text.find('>')
    if g != -1:
        new_text = new_text[:g + 1] + '\n' + MARKER + new_text[g + 1:]

    if new_text == text:
        return 'already_patched'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_text)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(label, e), level='WARNING')
        return 'write_failed'
    return 'patched'


def ensure_patched():
    """Returns a short summary. Never raises."""
    c1105 = _path(CUSTOM_1105_REL)
    incsrch = _path(INCLUDES_SEARCH_REL)
    if not c1105 and not incsrch:
        return 'no_af3'

    results = []
    if c1105:
        st = _patch_file(c1105, (
            (_C1105_PATH_CANDIDATES, _C1105_NEW_PATH),
            (_C1105_NAME_CANDIDATES, _C1105_NEW_NAME),
        ), 'Custom_1105_Search.xml')
        results.append('1105=' + st)
    if incsrch:
        st = _patch_file(incsrch, (
            (_INCSRCH_CONTENT_CANDIDATES, _INCSRCH_NEW_CONTENT),
            # restore Codex's v3 onclick/visible flips to stock (no-op if
            # already stock, since 'new in text' short-circuits).
            ((_INCSRCH_V3_ONCLICK, _INCSRCH_STOCK_ONCLICK),
             _INCSRCH_STOCK_ONCLICK),
            ((_INCSRCH_V3_VISIBLE, _INCSRCH_STOCK_VISIBLE),
             _INCSRCH_STOCK_VISIBLE),
        ), 'Includes_Search.xml')
        results.append('search=' + st)

    summary = ', '.join(results)
    if any('=patched' in r for r in results):
        _log('discover grid repointed to POV (' + summary + ')', 'INFO')
    return summary
