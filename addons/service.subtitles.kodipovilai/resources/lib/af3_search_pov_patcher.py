# Repoint Arctic Fuse 3's Search/Discover rows at POV instead of
# TMDbHelper, so typed search returns POV results (Hebrew, and they play
# through POV's own source scraping) -- matching the home widgets.
#
# WHY a skin-file patch (not just a node): AF3's search rows are generated
# from the `searchwidgets` skinvariables node, but each row's PATH is
# resolved through skin.arctic.fuse.3/shortcuts/generator/data/setup/
# search_path.xml -- three rule-sets keyed on the row's `path` token:
#   * widget_path           -> the plugin path PREFIX (before the query)
#   * widget_path_end        -> the path SUFFIX (after the query)
#   * widget_search_variable -> which encoded-query var to append
# A raw POV plugin path placed directly in the node would hit the
# catch-all rule, which appends the UNENCODED query (Path_SearchTerm).
# POV reads its query via parse_qsl(sys.argv[2][1:]) -- a single URL
# decode -- so an unencoded Hebrew/multi-word query would be mis-parsed.
# We therefore add proper rules for two POV tokens so the generator
# appends Path_SearchTerm_SingleEncoded (exactly one level of encoding,
# which parse_qsl then decodes back to the real query).
#
# This patcher:
#   1. Adds, idempotently, rules for DefaultSearch-POVMovies and
#      DefaultSearch-POVTv into all three rule-sets of search_path.xml
#      (prefix = POV search path ending in &query=, suffix = empty,
#      encode var = Path_SearchTerm_SingleEncoded). The node rows then
#      use those tokens. Re-applied every startup so a skin update that
#      ships a fresh search_path.xml gets re-patched.
#   2. The matching node (skinvariables-shortcut-searchwidgets.json) is
#      written separately by af3_home_patcher's FILES dict.
#
# Marker-gated, idempotent, atomic write. Safe no-op if AF3/the file is
# absent or its shape changed.

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


AF3_SKIN_ID = 'skin.arctic.fuse.3'
SEARCH_PATH_REL = ('addons/' + AF3_SKIN_ID +
                   '/shortcuts/generator/data/setup/search_path.xml')

MARKER = '<!-- AI_SUBS_POV_SEARCH_v1 -->'

# POV search path prefixes (the generator appends the encoded query, then
# our empty suffix). Note: in search_path.xml, '&' is written as the
# double-escaped '&amp;amp;' because the value is XML text that the
# generator later parses again. We mirror the existing TMDb rows exactly.
_POV_MOVIE_PREFIX = ('plugin://plugin.video.pov/?mode=build_movie_list'
                     '&amp;amp;action=tmdb_movies_search&amp;amp;query=')
_POV_TV_PREFIX = ('plugin://plugin.video.pov/?mode=build_tvshow_list'
                  '&amp;amp;action=tmdb_tv_search&amp;amp;query=')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('af3_search_pov_patcher: ' + msg, level=level)
    except Exception:
        pass


def _search_path_file():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/')
    except Exception:
        return ''
    p = os.path.join(base, *SEARCH_PATH_REL.split('/'))
    return p if os.path.isfile(p) else ''


def _rule(token, value):
    """One generator rule block (matches the file's 12-space indent)."""
    return (
        '        <rule>\n'
        '            <condition>{{item_path}}=={0}</condition>\n'
        '            <value>{1}</value>\n'
        '        </rule>\n'.format(token, value))


def _inject_after(text, rules_open, blocks):
    """Insert `blocks` (str) right after the line `rules_open` (e.g.
    '<rules name="widget_path">'). Returns new text, or None if the
    anchor isn't found exactly once."""
    idx = text.find(rules_open)
    if idx == -1 or text.find(rules_open, idx + 1) != -1:
        return None
    # insert after the end of that line
    eol = text.find('\n', idx)
    if eol == -1:
        return None
    return text[:eol + 1] + blocks + text[eol + 1:]


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_af3' | 'no_file'
    | 'unmatched' | 'read_failed' | 'write_failed'."""
    path = _search_path_file()
    if not path:
        # distinguish "AF3 not installed" from "file missing"
        if xbmcvfs is None:
            return 'no_af3'
        try:
            af3 = xbmcvfs.translatePath(
                'special://home/addons/' + AF3_SKIN_ID + '/addon.xml')
        except Exception:
            return 'no_af3'
        return 'no_file' if os.path.isfile(af3) else 'no_af3'

    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in text:
        return 'already_patched'

    # Build the per-rule-set injections.
    path_rules = (
        _rule('DefaultSearch-POVMovies', _POV_MOVIE_PREFIX)
        + _rule('DefaultSearch-POVTv', _POV_TV_PREFIX))
    # suffix empty for both
    end_rules = (
        _rule('DefaultSearch-POVMovies', '')
        + _rule('DefaultSearch-POVTv', ''))
    # single-encoded query (POV decodes once via parse_qsl)
    var_rules = (
        _rule('DefaultSearch-POVMovies', 'Path_SearchTerm_SingleEncoded')
        + _rule('DefaultSearch-POVTv', 'Path_SearchTerm_SingleEncoded'))
    # target: videos for both
    target_rules = (
        _rule('DefaultSearch-POVMovies', 'videos')
        + _rule('DefaultSearch-POVTv', 'videos'))

    new_text = text
    for rules_open, blocks in (
            ('<rules name="widget_path">', path_rules),
            ('<rules name="widget_path_end">', end_rules),
            ('<rules name="widget_target">', target_rules),
            ('<rules name="widget_search_variable">', var_rules)):
        res = _inject_after(new_text, rules_open, blocks)
        if res is None:
            _log('rule-set anchor not found/ambiguous: {0} -- AF3 may '
                 'have changed search_path.xml; leaving it alone'.format(
                     rules_open), level='WARNING')
            return 'unmatched'
        new_text = res

    # Drop a marker comment right after the root open tag so re-runs skip.
    # The file starts with the <shortcuts>/<paths> root; put the marker on
    # its own line at the very top after the first '>'.
    first_gt = new_text.find('>')
    if first_gt != -1:
        new_text = (new_text[:first_gt + 1] + '\n' + MARKER
                    + new_text[first_gt + 1:])
    else:
        new_text = MARKER + '\n' + new_text

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_text)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _log('added POV movie/tv search rules to search_path.xml', 'INFO')
    return 'patched'
