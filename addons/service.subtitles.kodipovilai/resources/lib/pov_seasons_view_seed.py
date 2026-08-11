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
#   * ONE forced say per skin, then never again. The first time this runs in a
#     given skin the poster view is written over whatever is there, including a
#     value the user appears to have chosen. That is deliberate and it is the
#     build owner's call: the seasons screen has been landing on view numbers
#     nobody picked -- one skin's id applied in another, or a stale row from an
#     older build -- so "a row is already there" is not evidence that anybody
#     chose it. After that one say, a view the user moves to is theirs and is
#     never touched again.
#
# THE ID IS PER SKIN AND POV'S TABLE IS NOT. `views` is
# (view_type TEXT, view_id TEXT, UNIQUE (view_type)) -- no skin column -- so
# one number is applied in every skin, and the same number means different
# layouts in different skins. 51 is Poster in Estuary, in FENtastic and in
# NOX (all three derive their numbering from Estuary), but Arctic Fuse 3
# numbers its own views and 512 is its Poster Wall; its 51 does not exist.
#
# So the marker records what we wrote FOR EACH SKIN, not just the last value:
# on a device that switches between skins the row in the shared table keeps
# being overwritten by the skin now running, and "is this still ours?" can
# only be answered against every value we have ever written, not the most
# recent one. Get that wrong and switching skins once makes the build think
# the user chose the number the other skin left behind.
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

# "skin.fentastic=51,skin.arctic.fuse.3=512" -- which skins we have had our
# one forced say in, and what we wrote in each. Empty means we have never
# written one anywhere.
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


def _done():
    """{skin id: the view id we wrote in that skin}. Never raises."""
    raw = ''
    if kodi_utils is not None:
        try:
            raw = (kodi_utils.get_setting(MARKER_SETTING, '') or '').strip()
        except Exception:
            raw = ''
    out = {}
    for part in raw.split(','):
        skin, _sep, view_id = part.strip().partition('=')
        skin, view_id = skin.strip(), view_id.strip()
        if skin and view_id:
            out[skin] = view_id
    return out


def _remember(done):
    """Write only on a change: this runs on a timer, and rewriting our own
    settings.xml every tick for the life of the box buys nothing."""
    if kodi_utils is None:
        return
    value = ','.join('%s=%s' % (s, v) for s, v in sorted(done.items()))
    try:
        if (kodi_utils.get_setting(MARKER_SETTING, '') or '').strip() == value:
            return
        kodi_utils.set_setting(MARKER_SETTING, value)
    except Exception:
        pass


# The skin this process has already settled, if any. Purely in-memory, and
# that is the point: it exists so the once-a-minute tick does not open POV's
# views.db once a minute forever. Nothing but POV's own Set View can change
# that row while the skin stays put, and when it does we would only be
# standing aside anyway -- so one look per skin per Kodi session is the whole
# of what this needs. A skin change clears it because that is the one event
# that makes the row wrong.
_SETTLED_SKIN = [None]


def ensure_seeded():
    """Returns 'no_pov' | 'unknown_skin' | 'seen' | 'seeded' | 'overrode'
    | 'reseeded' | 'already' | 'user_choice' | 'failed'. Never raises."""
    skin = _current_skin()
    want = POSTER_VIEWS.get(skin)
    if not want:
        # A skin we do not ship, or the skin is not readable yet. Guessing a
        # view number for an unknown skin is how you land somebody on a
        # layout that does not exist.
        return 'unknown_skin'
    if _SETTLED_SKIN[0] == skin:
        return 'seen'

    path = _db_path()
    if not path:
        return 'no_pov'

    done = _done()
    first_say = skin not in done
    current = None
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

        if not first_say:
            if current == want:
                _publish(want)      # cheap, and covers a property lost to a
                _SETTLED_SKIN[0] = skin      # POV service that never ran
                return 'already'             # this boot
            if current is not None and current not in set(done.values()):
                # We have already had our say in this skin and the row is no
                # longer any value we wrote -- in this skin or in another one
                # that shares the table. That is the user picking a view, and
                # it stands.
                _SETTLED_SKIN[0] = skin
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

    done[skin] = want
    _remember(done)
    _publish(want)
    _SETTLED_SKIN[0] = skin
    if current == want:
        result = 'already'
    elif current is None:
        result = 'seeded'
    elif first_say:
        result = 'overrode'
    else:
        result = 'reseeded'
    if result != 'already':
        _log('season list will open in {0}\'s poster view ({1}){2}'.format(
            skin, want,
            {'overrode': ' -- replacing ' + str(current),
             'reseeded': ' -- skin changed'}.get(result, '')),
            level='INFO')
    return result
