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
REMOVED_TOKEN = 'user_removed'
# How many of the user's own favourites to remember. More than one because any
# single anchor can itself be deleted; few because this is a hint, not a backup.
ANCHOR_COUNT = 5
_FAV_ACTION_RE = re.compile(r'<favourite\b[^>]*>(.*?)</favourite>', re.S)
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
    """{'state': ..., 'anchors': [...]} -- always a dict, never raises."""
    try:
        import json
        with open(_seen_path(), 'r', encoding='utf-8') as handle:
            data = json.loads(handle.read())
        return data if isinstance(data, dict) else {'state': REMOVED_TOKEN}
    except FileNotFoundError:
        return {}
    except Exception:
        # THERE IS A FILE AND WE CANNOT READ IT. Truncated by a power cut,
        # corrupted, or written by an older format. Treating that as "never
        # seeded" throws away a recorded deletion and puts the tile back --
        # so an unreadable record is read as the deletion it most likely is.
        # The cost of being wrong this way is a tile somebody never sees
        # again; the other way it is a tile they cannot get rid of.
        return {'state': REMOVED_TOKEN}


def _write_sidecar(state, anchors=None):
    try:
        import json
        path = _seen_path()
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        payload = {'state': state, 'anchors': list(anchors or [])}
        # ATOMIC, like the favourites.xml write below it. A half-written record
        # is unreadable, and an unreadable record now costs the user their
        # tile -- so it must never be possible to observe one.
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
        os.replace(tmp, path)
        return True
    except Exception as e:
        _log('could not record the tile state: {0}'.format(e), level='WARNING')
        return False


def _their_favourites(text):
    """The actions of every favourite in the file that is not ours."""
    return [a.strip() for a in _FAV_ACTION_RE.findall(text)
            if a.strip() and a.strip() != TILE_ACTION]


def _favourites_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath('special://userdata/' + FAVOURITES_REL)
    except Exception:
        return ''


def ensure_patched():
    """'no_kodi' | 'no_favourites' | 'already_present' | 'user_removed'
    | 'read_failed' | 'unparseable' | 'write_failed' | 'seeded'."""
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
    record = _sidecar()
    theirs = _their_favourites(text)

    if record.get('state') == REMOVED_TOKEN:
        # They told us to go away. Nothing reopens that.
        return 'user_removed'

    if has_tile:
        if not record.get('anchors'):
            # The tile is here but we have no anchors -- a fresh install whose
            # seed already carried it, so this patcher never ran. Record them
            # now, or the user's first deletion has nothing to be measured
            # against and would read as a wipe.
            _write_sidecar('offered', theirs[:ANCHOR_COUNT])
        return 'already_present'

    anchors = [a for a in record.get('anchors') or [] if isinstance(a, str)]
    if record and not anchors:
        # WE HAVE A RECORD BUT NOTHING TO MEASURE AGAINST -- their favourites
        # were only ours at seed time, or the anchor write failed. Without
        # anchors the two cases cannot be told apart, so fall back to the
        # safer one: we offered it once, and we do not offer again. Skipping
        # the check entirely, as this did, re-seeded on every single boot --
        # the v1 behaviour, for exactly the users least able to escape it.
        return 'already_seen'
    if anchors:
        survived = sum(1 for a in anchors if a in theirs)
        # A MAJORITY, NOT ALL. Requiring every anchor made MORE anchors mean
        # MORE false wipes: deleting our tile and one unrelated favourite in
        # the same sitting -- or months apart, since anchors are never
        # refreshed -- tripped it and put the tile back. A GUI delete of one
        # tile leaves the rest standing; the wizard's copyfile leaves almost
        # nothing of theirs. Half is a wide gap between those two.
        if survived * 2 >= len(anchors):
            # EVERY one of their favourites we remembered is still there, and
            # only ours is gone. That was them.
            #
            # ALL, not ANY. The per-skin seed the wizard copies over the file
            # contains the build's own service tiles, so an anchor can easily
            # be in BOTH their file and that seed -- and would survive the copy
            # and make a wipe look like a deletion. A wipe drops everything
            # that was theirs alone; a deletion of our tile drops nothing else.
            _write_sidecar(REMOVED_TOKEN)
            _log('the tile was removed by the user; not offering it again')
            return 'user_removed'
        # Not one of their favourites left -- this file was replaced wholesale,
        # so our tile went with it and they never asked for that.
        _log('favourites.xml was replaced; restoring the tile')

    closing = text.rfind('</favourites>')
    if closing == -1:
        # Not a favourites file we understand. Writing into it blind could
        # cost the user every tile they have.
        _log('favourites.xml has no </favourites>; leaving it alone',
             level='WARNING')
        return 'unparseable'

    updated = text[:closing] + TILE + '\n' + text[closing:]

    tmp = path + '.recent_updates.tmp'
    try:
        # A leftover DIRECTORY on this path blocks the write forever, silently,
        # because every failure here is swallowed.
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

    # RECORDED ONLY AFTER THE WRITE SUCCEEDED, and the anchors come from the
    # file as it was BEFORE we touched it -- their favourites, not ours.
    _write_sidecar('offered', theirs[:ANCHOR_COUNT])
    _log('seeded the "last ten updates" tile ({0} anchor(s) recorded)'
         .format(len(theirs[:ANCHOR_COUNT])))
    return 'seeded'

