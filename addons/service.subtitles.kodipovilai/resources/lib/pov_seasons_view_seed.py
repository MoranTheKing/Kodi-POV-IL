# Open POV's season list in a view that actually draws a poster.
#
# The report was "the per-season posters only work in NOX". They do not work
# only in NOX -- they work everywhere, and the screen simply was not showing
# any poster at all. POV hands every season its own artwork:
#
#     listitem.setArt({'poster': poster, 'icon': poster, 'thumb': poster,
#                      'season.poster': poster, 'tvshow.poster': poster, ...})
#         -- POV 6.08.06 resources/lib/menus/seasons.py
#
# where `poster` is that season's own TMDb poster_path, and TMDb returns a
# distinct one per season in Hebrew (checked live against six shows: none of
# them returns null for `he`). Estuary, FENtastic and NOX then resolve posters
# through a byte-identical `PosterVar`, and Arctic Fuse 3 prefers
# ListItem.Art(poster) outright. There is nothing wrong with the artwork.
#
# What differs is the VIEW. The screenshot from the field is FENtastic's
# Advanced List (630) -- a column of season labels beside one landscape still,
# with no poster anywhere in the layout. A poster the layout never draws is
# indistinguishable from a poster that is missing.
#
# So this seeds POV's own "view for seasons" with a poster view, once, and
# only for somebody who has never chosen one:
#
#   * POV keeps the choice in views.db as (view_type, view_id), and applies it
#     from set_view_mode(). Writing the row is exactly what POV's own "Set
#     View" writes, so nothing here is a patch to POV -- it is the same table,
#     the same key, the same value.
#   * a row we did not write is a decision the user made in POV's own UI, and
#     is never touched, not now and not later.
#
# THE ID IS PER SKIN AND POV'S TABLE IS NOT. `views` is
# (view_type TEXT, view_id TEXT, UNIQUE (view_type)) -- no skin column -- so
# one number is applied in every skin, and the same number means different
# layouts in different skins. 51 is Poster in Estuary, in FENtastic and in
# NOX (all three derive their numbering from Estuary), but Arctic Fuse 3
# numbers its own views and 512 is its Poster Wall; its 51 does not exist.
# That is why the value is rewritten when the skin changes, and why we track
# what WE last wrote: our own value may be replaced with the one that suits
# the skin now running, and anything else may not.
#
# Deliberately narrow: `view.seasons` only. The season screen is what was
# reported; movies, shows and episodes keep whatever they have.

import os
import sqlite3

try:
    import xbmc
except Exception:
    xbmc = None

try:
    import xbmcgui
except Exception:
    xbmcgui = None

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


VIEWS_DB = 'special://profile/addon_data/plugin.video.pov/views.db'
VIEW_TYPE = 'view.seasons'

# Skin id -> the view in that skin that draws a poster per item.
#   skin.estuary      View_51_Poster.xml
#   skin.fentastic    View_51_Poster.xml   (uses ListItem.Art(poster))
#   skin.povil.nox    View_51_Poster.xml
#   skin.arctic.fuse.3  View_512_Poster_Wall (Includes_Views.xml)
POSTER_VIEWS = {
    'skin.estuary': '51',
    'skin.fentastic': '51',
    'skin.povil.nox': '51',
    'skin.arctic.fuse.3': '512',
}

# Holds the view id WE last wrote, so ours can be replaced and the user's
# cannot. Empty means we have never written one.
MARKER_SETTING = '_pov_seasons_view_v1'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_seasons_view_seed: ' + msg, level=level)
    except Exception:
        pass


def _db_path():
    if xbmcvfs is None:
        return ''
    try:
        p = xbmcvfs.translatePath(VIEWS_DB)
    except Exception:
        return ''
    # Never create it. sqlite3.connect() happily makes an empty file, and a
    # zero-byte views.db in POV's profile is a way to break POV that did not
    # exist before we arrived.
    return p if p and os.path.isfile(p) else ''


def _current_skin():
    if xbmc is None:
        return ''
    try:
        return (xbmc.getSkinDir() or '').strip()
    except Exception:
        return ''


def _publish(view_id):
    """Set the window property POV reads the view from.

    POV loads views.db into window properties exactly once, from its own
    service at Kodi start (entry.viewsSetWindowProperties), and set_view_mode()
    then reads only the property. So a row written after that point would sit
    unused until the next restart -- and POV's own Set View writes the property
    for the same reason. Window(10000) and the 'pov_' prefix are POV's, from
    kodi_utils.set_view_property()."""
    if xbmcgui is None:
        return
    try:
        xbmcgui.Window(10000).setProperty('pov_%s' % VIEW_TYPE, view_id)
    except Exception:
        pass


def _ours():
    if kodi_utils is None:
        return ''
    try:
        return (kodi_utils.get_setting(MARKER_SETTING, '') or '').strip()
    except Exception:
        return ''


def _remember(view_id):
    if kodi_utils is None:
        return
    try:
        kodi_utils.set_setting(MARKER_SETTING, view_id)
    except Exception:
        pass


def ensure_seeded():
    """Returns 'no_pov' | 'unknown_skin' | 'seeded' | 'reseeded'
    | 'already' | 'user_choice' | 'failed'. Never raises."""
    skin = _current_skin()
    want = POSTER_VIEWS.get(skin)
    if not want:
        # A skin we do not ship, or the skin is not readable yet. Guessing a
        # view number for an unknown skin is how you land somebody on a
        # layout that does not exist.
        return 'unknown_skin'

    path = _db_path()
    if not path:
        return 'no_pov'

    con = None
    try:
        con = sqlite3.connect(path, timeout=5, isolation_level=None)
        cur = con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS views """
                    """(view_type TEXT, view_id TEXT, UNIQUE (view_type))""")
        cur.execute("""SELECT view_id FROM views WHERE view_type = ?""",
                    (VIEW_TYPE,))
        row = cur.fetchone()
        current = (row[0] or '').strip() if row else None

        if current == want:
            _publish(want)      # cheap, and covers a property lost to a
            return 'already'    # POV service that never ran this boot
        if current is not None and current != _ours():
            # Either the user picked this in POV's own Set View, or they
            # changed ours afterwards. Both are answers, and we do not get to
            # give a second one.
            return 'user_choice'

        cur.execute("""INSERT OR REPLACE INTO views VALUES (?, ?)""",
                    (VIEW_TYPE, want))
    except sqlite3.Error as e:
        _log('views.db not writable ({0}) -- leaving POV alone'.format(e),
             level='WARNING')
        return 'failed'
    finally:
        if con is not None:
            try:
                con.close()
            except sqlite3.Error:
                pass

    _remember(want)
    _publish(want)
    result = 'seeded' if current is None else 'reseeded'
    _log('season list will open in {0}\'s poster view ({1}){2}'.format(
        skin, want, '' if result == 'seeded' else ' -- skin changed'),
        level='INFO')
    return result
