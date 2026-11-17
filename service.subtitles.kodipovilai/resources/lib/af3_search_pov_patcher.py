# MoranSubs by MoranTheKing - https://github.com/MoranTheKing/Kodi-POV-IL
# SPDX-License-Identifier: GPL-3.0-or-later (additional terms: LICENSE.txt)
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

# Arctic Fuse 3 3.5 moved search to SkinVariables' multisearch: search_path.xml
# is gone, and a row's `path` token is looked up in this JSON table instead
# ({query} = the search text, percent-encoded once -- what POV reads).
MULTISEARCH_PATHS_REL = ('addons/' + AF3_SKIN_ID +
                         '/shortcuts/skinvariables-multisearch-paths.json')

_MARKER_BASE = '<!-- AI_SUBS_POV_SEARCH_v3_rollback'


def _marker(provider):
    """The marker carries the PROVIDER, so choosing a different search add-on
    makes the already-patched check miss and the rules get re-injected. A
    marker that ignored the provider would leave AF3 searching whatever it was
    first patched with, for ever."""
    return '{0}_{1} -->'.format(_MARKER_BASE, provider)


def _any_marker_re():
    import re as _re
    return _re.compile(_re.escape(_MARKER_BASE) + r'[^>]*-->\n?')


# Kept for the modules that import it by name; the POV spelling is the one
# every device carries today.
MARKER = _marker('pov')
# Older markers: our #207 v1 marker plus any Codex search markers. When any
# of these (or a Codex artifact below) is present we STRIP everything and
# re-inject ONLY the #207 rules, forcing a device stuck on a Codex build
# back to the PR #207 target. This is the "restore to #207 even for
# existing users" guarantee.
OLD_MARKERS = (
    '<!-- AI_SUBS_POV_SEARCH_v1 -->',
    '<!-- AI_SUBS_POV_SEARCH_v2 -->',
    '<!-- AI_SUBS_POV_SEARCH_v3 -->',
    # v2_rollback shipped movie+tv only; bumping to v3_rollback re-injects the
    # added People (actor/director) + Collections search rows for everyone.
    '<!-- AI_SUBS_POV_SEARCH_v2_rollback -->',
)

# Any of these in the file means a Codex build wrote combined-search /
# POVDiscover rules we must strip before re-injecting the #207 set.
_CODEX_ARTIFACTS = (
    'DefaultSearch-POVDiscover',
    'ai_pov_combined_search',
)

# Matches ANY of our injected POV rule blocks (POVMovies, POVTv, and
# Codex's POVDiscover) in any of the four rule-sets, regardless of value,
# so we can strip them all and re-inject only the #207 set. The blocks are
# written by _rule() at a fixed 8/12-space indent.
_POV_RULE_RE = re.compile(
    r'        <rule>\n'
    r'            <condition>\{item_path\}=='
    r'DefaultSearch-POV(?:Discover|Movies|Tv|People|Collections)</condition>\n'
    r'            <value>.*?</value>\n'
    r'        </rule>\n',
    re.DOTALL)

# Search path prefixes (the generator appends the encoded query, then our
# empty suffix). Note: in search_path.xml, '&' is written as the
# double-escaped '&amp;amp;' because the value is XML text that the
# generator later parses again. We mirror the existing TMDb rows exactly.
#
# Which add-on they point at is the user's choice; search_provider owns the
# table for both providers and the fallback when Umbrella is not installed.
# POV's four are repeated here as the fallback for the (impossible in the
# build, possible in a standalone install) case where that module is absent.
_POV_FALLBACK = {
    'Movies': ('plugin://plugin.video.pov/?mode=build_movie_list'
               '&amp;amp;action=tmdb_movies_search&amp;amp;query='),
    'Tv': ('plugin://plugin.video.pov/?mode=build_tvshow_list'
           '&amp;amp;action=tmdb_tv_search&amp;amp;query='),
    # People search (actors AND directors): POV's router does
    # person_search(params['query']) (entry.py mode=person_search).
    'People': ('plugin://plugin.video.pov/?mode=person_search'
               '&amp;amp;query='),
    # Movie collections: same shape as movie search, action=..._collections
    # (menus/movies.py handles tmdb_movies_search_collections).
    'Collections': ('plugin://plugin.video.pov/?mode=build_movie_list'
                    '&amp;amp;action=tmdb_movies_search_collections'
                    '&amp;amp;query='),
}


def _provider_and_prefixes():
    """(provider name, {row: path prefix}) for the chosen search add-on."""
    try:
        from resources.lib import search_provider
        return search_provider.current(), search_provider.af3_prefixes()
    except Exception:
        return 'pov', _POV_FALLBACK


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


def _multisearch_paths_file():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/')
    except Exception:
        return ''
    p = os.path.join(base, *MULTISEARCH_PATHS_REL.split('/'))
    return p if os.path.isfile(p) else ''


INCLUDES_SEARCH_REL = 'addons/' + AF3_SKIN_ID + '/1080i/Includes_Search.xml'
# The search window's five drop-down labels end in this arrow (U+2304). The
# build's Hebrew font for Arctic Fuse 3 has no such glyph: each showed as an
# empty box.
_DROPDOWN_GLYPH = u' \u2304</label>'


def _strip_dropdown_glyph():
    """'patched' when the arrow was removed from the labels, else
    'already_patched' (nothing to remove, or the file cannot be handled --
    a box beside a label is not worth failing the search over)."""
    if xbmcvfs is None:
        return 'already_patched'
    tmp = ''
    try:
        path = os.path.join(xbmcvfs.translatePath('special://home/'),
                            *INCLUDES_SEARCH_REL.split('/'))
        with open(path, 'r', encoding='utf-8', newline='') as f:
            text = f.read()
        if _DROPDOWN_GLYPH not in text:
            return 'already_patched'
        tmp = path + '.aitmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(text.replace(_DROPDOWN_GLYPH, u'</label>'))
        os.replace(tmp, path)
        return 'patched'
    except Exception as e:
        _log('search labels: the arrow could not be removed: {0}'.format(e), level='WARNING')
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return 'already_patched'


def _ensure_multisearch_paths(path):
    """Arctic Fuse 3 3.5+: define the build's search tokens in the skin's
    multisearch table. The rows themselves (the searchwidgets node, written
    by af3_home_patcher) keep the same DefaultSearch-POV* tokens as before.
    A skin update ships a fresh table, so this runs at every start; a
    change of the search add-on changes the wanted values and rewrites it."""
    import json
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        _log('multisearch paths: read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    try:
        table = json.loads(text)
    except ValueError:
        table = None
    if not isinstance(table, dict) or not any(
            isinstance(v, str) and '{query' in v for v in table.values()):
        _log('multisearch paths: not the table this patcher knows; leaving '
             'it alone', level='WARNING')
        return 'unmatched'
    provider, prefixes = _provider_and_prefixes()
    # the prefixes are written for search_path.xml, where '&' is escaped twice
    wanted = dict(
        ('DefaultSearch-POV' + row,
         prefix.replace('&amp;amp;', '&').replace('&amp;', '&') + '{query}')
        for row, prefix in prefixes.items())
    if all(table.get(token) == value for token, value in wanted.items()):
        return 'already_patched'
    table.update(wanted)
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(table, f, indent=4, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('multisearch paths: write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
    _log('search tokens defined in the multisearch table ({0})'.format(provider), 'INFO')
    return 'patched'


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
        multisearch = _multisearch_paths_file()
        if multisearch:
            status = _ensure_multisearch_paths(multisearch)
            if status in ('patched', 'already_patched') and _strip_dropdown_glyph() == 'patched':
                return 'patched'
            return status
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
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    provider, prefixes = _provider_and_prefixes()
    marker = _marker(provider)

    # Already exactly at the target for THIS provider (its marker, no stale
    # marker and no Codex artifact to clean up) -> nothing to do.
    has_old = any(m in text for m in OLD_MARKERS)
    has_codex = any(a in text for a in _CODEX_ARTIFACTS)
    if marker in text and not has_old and not has_codex:
        return 'already_patched'

    # Strip ALL of our prior POV rule blocks (POVMovies/POVTv AND Codex's
    # POVDiscover) from every rule-set, and drop every marker we've ever
    # stamped -- including the other provider's, and the un-suffixed one every
    # device carries today -- returning the file to a clean stock state before
    # we re-inject below.
    text = _POV_RULE_RE.sub('', text)
    text = _any_marker_re().sub('', text)
    for m in OLD_MARKERS:
        text = text.replace(m + '\n', '').replace(m, '')

    # Build the per-rule-set injections (movies, tv, people, collections).
    # The TOKENS keep their historical DefaultSearch-POV* spelling whatever the
    # provider is: they are opaque keys shared with the searchwidgets node
    # written by af3_home_patcher, and renaming them would break every row.
    path_rules = (
        _rule('DefaultSearch-POVMovies', prefixes['Movies'])
        + _rule('DefaultSearch-POVTv', prefixes['Tv'])
        + _rule('DefaultSearch-POVPeople', prefixes['People'])
        + _rule('DefaultSearch-POVCollections', prefixes['Collections']))
    # suffix empty for all
    end_rules = (
        _rule('DefaultSearch-POVMovies', '')
        + _rule('DefaultSearch-POVTv', '')
        + _rule('DefaultSearch-POVPeople', '')
        + _rule('DefaultSearch-POVCollections', ''))
    # single-encoded query (POV decodes once via parse_qsl)
    var_rules = (
        _rule('DefaultSearch-POVMovies', 'Path_SearchTerm_SingleEncoded')
        + _rule('DefaultSearch-POVTv', 'Path_SearchTerm_SingleEncoded')
        + _rule('DefaultSearch-POVPeople', 'Path_SearchTerm_SingleEncoded')
        + _rule('DefaultSearch-POVCollections', 'Path_SearchTerm_SingleEncoded'))
    # target: videos for all
    target_rules = (
        _rule('DefaultSearch-POVMovies', 'videos')
        + _rule('DefaultSearch-POVTv', 'videos')
        + _rule('DefaultSearch-POVPeople', 'videos')
        + _rule('DefaultSearch-POVCollections', 'videos'))

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
        new_text = (new_text[:first_gt + 1] + '\n' + marker
                    + new_text[first_gt + 1:])
    else:
        new_text = marker + '\n' + new_text

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

    _log('added {0} movie/tv/people/collections search rules to '
         'search_path.xml'.format(provider), 'INFO')
    return 'patched'
