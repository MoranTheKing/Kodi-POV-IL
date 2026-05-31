# Repoint Arctic Fuse 3's DISCOVER GRID (window 1105 / container 501)
# from TMDbHelper to POV. v1 made this a stable POV popular grid. v2 makes
# the grid respond to the typed search term and returns mixed movie + TV
# POV results via our ai_pov_combined_search route.
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

MARKER = '<!-- AI_SUBS_POV_DISCOVER_v2 -->'
OLD_MARKERS = (
    '<!-- AI_SUBS_POV_DISCOVER_v1 -->',
    '<!-- AI_SUBS_POV_DISCOVER_v3 -->',
)

# The fallback POV grid path for an empty search box.
_POV_GRID_PATH = ('plugin://plugin.video.pov/?mode=build_movie_list'
                  '&amp;action=tmdb_movies_popular'
                  '&amp;name=32461&amp;iconImage=dvd.png')
_POV_COMBINED_SEARCH_CONTENT = (
    'plugin://plugin.video.pov/?mode=ai_pov_combined_search'
    '&amp;name=Search%20Results&amp;query='
    '$VAR[Path_SearchTerm_SingleEncoded]')

# --- Custom_1105_Search.xml exact replacements (LF line endings) ---
_C1105_OLD_PATH = (
    'SetProperty(TMDbHelper.UserDiscover.FolderPath,'
    'plugin://plugin.video.themoviedb.helper/?info=discover'
    '&amp;with_id=True&amp;tmdb_type=movie,Home)')
_C1105_NEW_PATH = (
    'SetProperty(TMDbHelper.UserDiscover.FolderPath,'
    + _POV_GRID_PATH + ',Home)')
_C1105_V1_PATH = _C1105_NEW_PATH

_C1105_OLD_NAME = (
    'SetProperty(TMDbHelper.UserDiscover.FolderPath.Name,'
    '$LOCALIZE[467] $LOCALIZE[342],Home)')
_C1105_NEW_NAME = (
    'SetProperty(TMDbHelper.UserDiscover.FolderPath.Name,גלה,Home)')

_C1105_V1_NAME = _C1105_NEW_NAME

# --- Includes_Search.xml: strip the &with_text_query suffix on line 54 ---
_INCSRCH_OLD_CONTENT = (
    '<param name="content">'
    '$INFO[window(home).property(tmdbhelper.userdiscover.folderpath)]'
    '$INFO[Control.GetLabel(3000).index(1),&amp;with_text_query=,]'
    '</param>')
_INCSRCH_NEW_CONTENT = (
    '<param name="content">'
    + _POV_COMBINED_SEARCH_CONTENT +
    '</param>')
_INCSRCH_V1_CONTENT = (
    '<param name="content">'
    '$INFO[window(home).property(tmdbhelper.userdiscover.folderpath)]'
    '</param>')
_INCSRCH_V3_CONTENT = (
    '<param name="content">'
    'plugin://plugin.video.pov/?mode=ai_pov_combined_search'
    '&amp;media_type=all&amp;name=Discover&amp;query='
    '$VAR[Path_SearchTerm_SingleEncoded]'
    '</param>')
_INCSRCH_V3_DISCOVER_LABEL = '<label>גלה</label>'
_INCSRCH_DEFAULT_DISCOVER_LABEL = '<label>$LOCALIZE[31066]</label>'
_INCSRCH_V3_DISCOVER_ONCLICK = '<onclick>SetFocus(501)</onclick>'
_INCSRCH_DEFAULT_DISCOVER_ONCLICK = (
    '<onclick>RunPlugin(plugin://plugin.video.themoviedb.helper/?info=user_discover'
    '$INFO[Window(Home).Property(TMDbHelper.UserDiscover.Folderpath.ParamString),&amp;,])</onclick>')
_INCSRCH_V3_DISCOVER_VISIBLE = '<visible>true</visible>'
_INCSRCH_DEFAULT_DISCOVER_VISIBLE = (
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
    """Apply (old,new) replacements to a file, marker-gated. Returns
    'patched' | 'already_patched' | 'unmatched' | 'read_failed'
    | 'write_failed'."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(label, e), level='WARNING')
        return 'read_failed'

    needs_rollback_cleanup = any(old_marker in text for old_marker in OLD_MARKERS)
    if MARKER in text and not needs_rollback_cleanup:
        return 'already_patched'
    for old_marker in (MARKER,) + OLD_MARKERS:
        text = text.replace(old_marker, '')

    new_text = text
    for old, new in replacements:
        if isinstance(old, tuple):
            matched = None
            for candidate in old:
                if candidate in new_text:
                    matched = candidate
                    break
            if not matched:
                _log('{0}: expected string not found -- AF3 may have changed '
                     'this file; leaving it alone'.format(label),
                     level='WARNING')
                return 'unmatched'
            new_text = new_text.replace(matched, new, 1)
            continue
        if old not in new_text:
            _log('{0}: expected string not found -- AF3 may have changed '
                 'this file; leaving it alone'.format(label),
                 level='WARNING')
            return 'unmatched'
        new_text = new_text.replace(old, new, 1)

    # marker after the first '>' (root tag) so re-runs skip.
    g = new_text.find('>')
    if g != -1:
        new_text = new_text[:g + 1] + '\n' + MARKER + new_text[g + 1:]

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
            ((_C1105_OLD_PATH, _C1105_V1_PATH), _C1105_NEW_PATH),
        ), 'Custom_1105_Search.xml')
        results.append('1105=' + st)
    if incsrch:
        st = _patch_file(incsrch, (
            ((_INCSRCH_OLD_CONTENT, _INCSRCH_V1_CONTENT, _INCSRCH_NEW_CONTENT,
              _INCSRCH_V3_CONTENT), _INCSRCH_NEW_CONTENT),
            ((_INCSRCH_V3_DISCOVER_ONCLICK, _INCSRCH_DEFAULT_DISCOVER_ONCLICK),
             _INCSRCH_DEFAULT_DISCOVER_ONCLICK),
            ((_INCSRCH_V3_DISCOVER_VISIBLE, _INCSRCH_DEFAULT_DISCOVER_VISIBLE),
             _INCSRCH_DEFAULT_DISCOVER_VISIBLE),
        ), 'Includes_Search.xml')
        results.append('search=' + st)

    summary = ', '.join(results)
    if any('=patched' in r for r in results):
        _log('discover grid repointed to POV (' + summary + ')', 'INFO')
    return summary
