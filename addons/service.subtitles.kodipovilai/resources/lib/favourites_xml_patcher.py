# Self-healing migration of two home-screen tiles in
# userdata/favourites.xml so users who haven't customized their
# favorites bar get the new TMDB-default home tiles without having
# to reinstall the build (which would wipe their connected
# services like Gemini / TMDB tokens).
#
# Uses regex matching instead of byte-exact line match so we
# tolerate variations in whitespace, attribute order, or quote
# styles that Kodi may introduce when it rewrites the file (e.g.
# after the user reorders tiles via the GUI). Each pattern is
# strict about identity -- the visible label AND the action+mode
# combination AND the plugin URL must all match -- so legitimate
# user customizations (renamed tile, different action, custom
# plugin) are left alone.

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


FAVOURITES_RELATIVE = 'favourites.xml'

# (regex, replacement) -- one pair per tile to migrate. The regex
# is non-greedy and stops at the closing </favourite>, so it can
# never accidentally swallow a neighbouring favourite element.
PATTERNS = (
    # TV shows: any <favourite> element whose name is exactly
    # "[B]הסדרות שלי (Trakt)[/B]" and whose URL has the trakt_collection
    # action with build_tvshow_list mode.
    (
        re.compile(
            r'<favourite\s[^>]*?name="\[B\]הסדרות שלי \(Trakt\)\[/B\]"[^>]*>'
            r'(?:(?!</favourite>).)*?action=trakt_collection'
            r'(?:(?!</favourite>).)*?mode=build_tvshow_list'
            r'(?:(?!</favourite>).)*?</favourite>',
            re.DOTALL,
        ),
        '<favourite name="[B]הסדרות שלי (TMDB)[/B]" '
        'thumb="special://home/media/build_icons/Twilight/Shows/'
        'My_Shows.png">'
        'ActivateWindow(10025,"plugin://plugin.video.pov/?'
        'action=tmdb_favorites&amp;iconImage=special%3a%2f%2fhome%2f'
        'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
        'media%2ftmdb.png&amp;mode=build_tvshow_list&amp;'
        'name=TV%20Show%20Favorites",return)</favourite>',
    ),
    # Movies: same logic with build_movie_list.
    (
        re.compile(
            r'<favourite\s[^>]*?name="\[B\]הסרטים שלי \(Trakt\)\[/B\]"[^>]*>'
            r'(?:(?!</favourite>).)*?action=trakt_collection'
            r'(?:(?!</favourite>).)*?mode=build_movie_list'
            r'(?:(?!</favourite>).)*?</favourite>',
            re.DOTALL,
        ),
        '<favourite name="[B]הסרטים שלי (TMDB)[/B]" '
        'thumb="special://home/media/build_icons/Twilight/Movies/'
        'My_Movies.png">'
        'ActivateWindow(10025,"plugin://plugin.video.pov/?'
        'action=tmdb_favorites&amp;iconImage=special%3a%2f%2fhome%2f'
        'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
        'media%2ftmdb.png&amp;mode=build_movie_list&amp;'
        'name=Movie%20Favorites",return)</favourite>',
    ),
)

# Short-circuit tokens: if these are already present in the file
# we know that tile has been migrated and we can skip touching it.
NEW_TOKEN_SHOWS = 'הסדרות שלי (TMDB)'
NEW_TOKEN_MOVIES = 'הסרטים שלי (TMDB)'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('favourites_xml_patcher: ' + msg, level=level)
    except Exception:
        pass


def _favourites_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://profile/')
    except Exception:
        return ''
    p = os.path.join(base, FAVOURITES_RELATIVE)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    path = _favourites_path()
    if not path:
        _log('no favourites.xml found', level='INFO')
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    # Quick check: if both tiles already migrated, nothing to do.
    if NEW_TOKEN_SHOWS in content and NEW_TOKEN_MOVIES in content:
        _log('both tiles already migrated -- no-op', level='DEBUG')
        return 'unchanged'

    new_content = content
    rewrites = 0
    pattern_results = []
    for i, (pattern, replacement) in enumerate(PATTERNS):
        tile_label = ('shows', 'movies')[i]
        # Skip if this tile already migrated.
        token = (NEW_TOKEN_SHOWS, NEW_TOKEN_MOVIES)[i]
        if token in new_content:
            pattern_results.append('{0}=already'.format(tile_label))
            continue
        new_content, n = pattern.subn(replacement, new_content, count=1)
        if n == 0:
            pattern_results.append('{0}=no_match'.format(tile_label))
        else:
            pattern_results.append('{0}=patched'.format(tile_label))
            rewrites += n

    _log('scan: ' + ', '.join(pattern_results), level='INFO')

    if rewrites == 0:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('wrote {0} rewrites to {1}'.format(rewrites, path),
             level='INFO')
        return 'patched_{0}'.format(rewrites)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
