# Seeds ONE home tile: "10 העדכונים האחרונים", opening the wizard's archive of
# the last ten update notes.
#
# OFFERED ONCE, NEVER RE-OFFERED. The marker records that the build has put the
# tile in front of this user, not that the tile is currently there. So a user
# who deletes it keeps it deleted -- through the next update, the next start,
# and every one after. Restoring a tile somebody removed is the same class of
# rudeness as re-enabling an add-on they switched off, and this build has just
# finished apologising for that one.
#
# The marker lives inside favourites.xml, next to the ones the sibling patchers
# write, so "has the build offered this?" survives exactly as long as the file
# it is a statement about. A user who wipes favourites.xml gets the tile again,
# which is right: that is a new favourites.xml, not their edited one.

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


FAVOURITES_REL = 'favourites.xml'
SEEN_MARKER = '<!-- AI_SUBS_FAVOURITES_RECENT_UPDATES_SEEN_v1 -->'
TILE_NAME = '[B][COLOR yellow]10 העדכונים האחרונים[/COLOR][/B]'
TILE_THUMB = 'special://home/media/build_icons/Wizard/wizard_pov_il.png'
TILE_ACTION = ('RunPlugin("plugin://plugin.program.kodipovilwizard/'
               '?mode=recentupdates")')
TILE = ('    <favourite name="{0}" thumb="{1}">{2}</favourite>'
        .format(TILE_NAME, TILE_THUMB, TILE_ACTION))


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('recent_updates_tile: ' + msg, level=level)
    except Exception:
        pass


def _favourites_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath('special://userdata/' + FAVOURITES_REL)
    except Exception:
        return ''


def ensure_patched():
    """'no_kodi' | 'no_favourites' | 'already_seen' | 'read_failed'
    | 'unparseable' | 'write_failed' | 'seeded'."""
    if xbmcvfs is None:
        return 'no_kodi'
    path = _favourites_path()
    if not path or not os.path.isfile(path):
        # Nothing to add a tile to. The wizard seeds favourites.xml; when it
        # has not yet, the next run finds it and seeds then.
        return 'no_favourites'
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            text = handle.read()
    except Exception as e:
        _log('could not read favourites.xml: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if SEEN_MARKER in text:
        # Offered before. Whether the tile is there or the user removed it is
        # none of our business now.
        return 'already_seen'

    closing = text.rfind('</favourites>')
    if closing == -1:
        # Not a favourites file we understand. Writing into it blind could
        # cost the user every tile they have.
        _log('favourites.xml has no </favourites>; leaving it alone',
             level='WARNING')
        return 'unparseable'

    # If a tile with this action somehow exists already, do not add a second --
    # just record that the offer has been made.
    addition = TILE + '\n' if TILE_ACTION not in text else ''
    updated = (text[:closing] + addition + '    ' + SEEN_MARKER + '\n'
               + text[closing:])

    tmp = path + '.recent_updates.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as handle:
            handle.write(updated)
        os.replace(tmp, path)
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        _log('could not write favourites.xml: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _log('seeded the "last ten updates" tile{0}'.format(
        '' if addition else ' marker (tile was already present)'))
    return 'seeded'
