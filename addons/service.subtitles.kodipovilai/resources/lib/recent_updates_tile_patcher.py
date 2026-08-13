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
# TWO RECORDS, BECAUSE THERE ARE TWO QUESTIONS, and each single-record shape
# got one of them wrong.
#
# A comment inside favourites.xml alone: the wizard's update_favourites_xml_file
# copies a static per-skin seed straight over that file on every skin switch,
# so the comment went with it and a tile the user had DELETED came back.
#
# A sidecar alone: it says "we have offered this once", which is true forever --
# so when that same skin switch removed the tile from a user who had NEVER
# touched it, nothing ever put it back. Silent, permanent, and triggered by a
# menu entry this build puts in front of everyone.
#
# So the comment answers "is this still a favourites.xml WE edited", and the
# sidecar answers "did the user tell us to go away". Together they separate a
# deliberate deletion (our marker still there, our tile gone) from an external
# wipe (our marker gone too), which is exactly what favourites_xml_patcher does
# with its anchor tile.
#
# The one case this cannot see: deleting the tile and switching skin with no
# service run in between. The tile returns once; delete it again and the next
# start records it for good.

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
# Written into favourites.xml beside the tile. Its ABSENCE is the signal: this
# file is no longer one we edited, so anything of ours missing from it was
# removed by the copy, not by the user.
EDIT_MARKER = '<!-- AI_SUBS_FAVOURITES_RECENT_UPDATES_v2 -->'
REMOVED_TOKEN = 'user_removed'
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


def _sidecar():
    try:
        with open(_seen_path(), 'r', encoding='utf-8') as handle:
            return handle.read().strip()
    except Exception:
        return ''


def _user_removed_it():
    try:
        return _sidecar() == REMOVED_TOKEN
    except Exception:
        # Cannot tell -> assume they removed it. Guessing the other way re-adds
        # a tile somebody deleted, which is the worse of the two.
        return True


def _write_sidecar(token):
    try:
        path = _seen_path()
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(token + '\n')
        return True
    except Exception as e:
        _log('could not record the tile state: {0}'.format(e), level='WARNING')
        return False


def _favourites_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath('special://userdata/' + FAVOURITES_REL)
    except Exception:
        return ''


def _stamp_marker(path, text):
    """Add our marker to a favourites.xml that already carries the tile."""
    closing = text.rfind('</favourites>')
    if closing == -1:
        return False
    updated = text[:closing] + '    ' + EDIT_MARKER + '\n' + text[closing:]
    tmp = path + '.recent_updates.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as handle:
            handle.write(updated)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


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

    has_tile = TILE_ACTION in text
    has_marker = EDIT_MARKER in text

    if _user_removed_it():
        # They told us to go away. Nothing reopens that.
        return 'user_removed'

    if has_tile:
        if not has_marker:
            # Present but unmarked -- a fresh seed that already carried it, or
            # our marker was stripped. Mark it so a later deletion is readable
            # as a deletion rather than as a wipe.
            _stamp_marker(path, text)
        return 'already_present'

    if has_marker:
        # OUR file, OUR tile gone: the user removed it. Record that durably,
        # because the marker itself will not survive the next skin switch.
        _write_sidecar(REMOVED_TOKEN)
        _log('the tile was removed by the user; not restoring it again')
        return 'user_removed'

    # No tile and no marker: this favourites.xml is not one we edited -- a
    # first run, or a file the skin switch replaced wholesale. Seed it.
    closing = text.rfind('</favourites>')
    if closing == -1:
        # Not a favourites file we understand. Writing into it blind could
        # cost the user every tile they have.
        _log('favourites.xml has no </favourites>; leaving it alone',
             level='WARNING')
        return 'unparseable'

    # If a tile with this action somehow exists already, do not add a second --
    # just record that the offer has been made.
    updated = (text[:closing] + TILE + '\n    ' + EDIT_MARKER + '\n'
               + text[closing:])

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

    # RECORDED ONLY AFTER THE WRITE SUCCEEDED.
    _write_sidecar('offered')
    _log('seeded the "last ten updates" tile')
    return 'seeded'
