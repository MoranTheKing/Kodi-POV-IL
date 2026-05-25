# Self-healing migration of two home-screen tiles in
# userdata/favourites.xml so users who haven't customized their
# favorites bar get the new TMDB-default home tiles without having
# to reinstall the build (which would wipe their connected
# services like Gemini / TMDB tokens).
#
# Strategy: surgical string replacement. Each tile is identified by
# its EXACT shipped line (name + thumb + ActivateWindow URL). If the
# line is present verbatim, replace it with the TMDB equivalent. If
# the line was edited (different name, different URL, different
# thumb), leave it alone -- that means the user touched it, and we
# don't second-guess their choice.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None


FAVOURITES_RELATIVE = 'favourites.xml'

OLD_LINES = (
    '    <favourite name="[B]הסדרות שלי (Trakt)[/B]" '
    'thumb="special://home/media/build_icons/Twilight/Shows/My_Shows.png">'
    'ActivateWindow(10025,"plugin://plugin.video.pov/?'
    'action=trakt_collection&amp;iconImage=special%3a%2f%2fhome%2f'
    'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
    'media%2ftrakt.png&amp;mode=build_tvshow_list&amp;'
    'name=TV%20Shows",return)</favourite>',
    '    <favourite name="[B]הסרטים שלי (Trakt)[/B]" '
    'thumb="special://home/media/build_icons/Twilight/Movies/My_Movies.png">'
    'ActivateWindow(10025,"plugin://plugin.video.pov/?'
    'action=trakt_collection&amp;iconImage=special%3a%2f%2fhome%2f'
    'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
    'media%2ftrakt.png&amp;mode=build_movie_list&amp;'
    'name=Movies",return)</favourite>',
)

NEW_LINES = (
    '    <favourite name="[B]הסדרות שלי (TMDB)[/B]" '
    'thumb="special://home/media/build_icons/Twilight/Shows/My_Shows.png">'
    'ActivateWindow(10025,"plugin://plugin.video.pov/?'
    'action=tmdb_favorites&amp;iconImage=special%3a%2f%2fhome%2f'
    'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
    'media%2ftmdb.png&amp;mode=build_tvshow_list&amp;'
    'name=TV%20Show%20Favorites",return)</favourite>',
    '    <favourite name="[B]הסרטים שלי (TMDB)[/B]" '
    'thumb="special://home/media/build_icons/Twilight/Movies/My_Movies.png">'
    'ActivateWindow(10025,"plugin://plugin.video.pov/?'
    'action=tmdb_favorites&amp;iconImage=special%3a%2f%2fhome%2f'
    'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
    'media%2ftmdb.png&amp;mode=build_movie_list&amp;'
    'name=Movie%20Favorites",return)</favourite>',
)


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
    """Replace any Trakt-collection home tiles still matching the
    shipped baseline with TMDB-favorites equivalents. Returns a
    summary string for logging.
    """
    path = _favourites_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return 'read_failed'

    new_content = content
    rewrites = 0
    for old, new in zip(OLD_LINES, NEW_LINES):
        if new in new_content:
            # Already migrated for this tile -- skip.
            continue
        if old not in new_content:
            # User customized this tile (or it was never present) --
            # leave alone.
            continue
        new_content = new_content.replace(old, new, 1)
        rewrites += 1

    if rewrites == 0:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        return 'patched_{0}'.format(rewrites)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return 'write_failed'
