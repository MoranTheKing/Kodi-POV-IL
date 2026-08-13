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
# THE MARKER IS A SIDECAR, NOT A COMMENT INSIDE favourites.xml. That was the
# first shape and it was wrong: the wizard's update_favourites_xml_file() copies
# a static per-skin seed straight over userdata/favourites.xml on every skin
# switch, unconditionally. The marker went with it, so a user who deleted the
# tile and then switched skin -- an ordinary menu action -- got it back on the
# next start. favourites_xml_patcher moved its own delete-tracking to a sidecar
# for exactly this reason; this now does the same.
#
# A user who wipes their addon_data as well gets the offer again, which is
# right: that is a new profile, not their edited one.

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
SEEN_FILE = ('special://profile/addon_data/service.subtitles.kodipovilai/'
             'recent_updates_tile_seen.txt')
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


def _seen_path():
    try:
        return xbmcvfs.translatePath(SEEN_FILE)
    except Exception:
        return ''


def _already_offered():
    try:
        return os.path.isfile(_seen_path())
    except Exception:
        # Cannot tell -> assume offered. Guessing "no" would re-add a tile the
        # user may have deleted, which is the one outcome to avoid.
        return True


def _mark_offered():
    try:
        path = _seen_path()
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('1\n')
        return True
    except Exception as e:
        _log('could not record the offer: {0}'.format(e), level='WARNING')
        return False


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

    if _already_offered():
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
    updated = text[:closing] + addition + text[closing:]

    tmp = path + '.recent_updates.tmp'
    try:
        # A leftover DIRECTORY on this path blocks the write forever, silently,
        # because every failure here is swallowed. The wizard hit exactly this
        # on a sibling record file and had to add a cleanup; cheaper to clear
        # it than to strand the tile.
        if os.path.isdir(tmp):
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
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

    # RECORDED ONLY AFTER THE WRITE SUCCEEDED. Marking first and failing to
    # write would mean the tile was never offered and never will be.
    _mark_offered()
    _log('seeded the "last ten updates" tile{0}'.format(
        '' if addition else ' (tile was already present)'))
    return 'seeded'
