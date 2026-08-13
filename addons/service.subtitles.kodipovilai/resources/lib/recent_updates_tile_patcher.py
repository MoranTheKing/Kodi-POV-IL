# Seeds ONE home tile: "10 העדכונים האחרונים", opening the wizard's archive of
# the last ten update notes.
#
# OFFERED ONCE, NEVER RE-OFFERED. A user who deletes the tile keeps it
# deleted -- through the next update, the next start, and every one after.
# Restoring a tile somebody removed is the same rudeness as re-enabling an
# add-on they switched off, which this build spent another commit apologising
# for. But a tile removed by something OTHER than the user has to come back,
# and the wizard removes it routinely: update_favourites_xml_file() copies a
# static per-skin seed over the whole file on every skin switch.
#
# SO ASK THE WIZARD, DO NOT READ THE TEA LEAVES. Five designs tried to work
# out which of the two had happened from favourites.xml alone, and every one
# failed in one direction or the other:
#
#   1. A comment marker in the file -- the skin-switch copy took it, so a
#      DELETED tile came back.
#   2. A sidecar saying "offered once" -- survives the copy, so a tile the copy
#      removed was never restored.
#   3. Both together -- Kodi re-serialises favourites.xml from memory on ANY
#      GUI favourites edit, so the comment died in the same write that removed
#      the tile. Broken for the primary deletion path, day one.
#   4. Anchors: remember some of the user's own favourites, and judge by how
#      many survived. Defeated by a favourites list made only of build-seeded
#      tiles, which also live in the seed and survive the copy.
#   5. Compare the file against the shipped seed -- exact for a fresh copy, but
#      after a wipe-and-restore the file IS the seed plus our tile, so deleting
#      the tile returns it to exactly the seed and reads as another wipe.
#
# The writer knew the whole time. update_favourites_xml_file is the only thing
# that replaces the file, so it bumps a counter as it does; this records that
# counter when it seeds, and later:
#
#   counter moved   -> the file was replaced -> put the tile back
#   counter did not -> nobody replaced it    -> that was the user -> never again
#
# A fact, for the price of one integer. The anchors remain only as a fallback
# for a device whose wizard predates the counter -- which, since both ship in
# the same quickfix, is essentially none.
#
# All of it rests on ONE invariant: the tile never exists without a record. An
# absent record has to mean "never offered", or no first run could ever seed
# anything -- so the record is written FIRST and the tile only follows a good
# write, which makes that meaning true by construction rather than by hope.

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
# BESIDE THE WIZARD'S COUNTER, NOT IN OUR OWN addon_data. Kodi ships a
# "Clear data" button on every add-on's settings screen, and it wipes exactly
# one folder: that add-on's. With this record living in ours, a user who
# deleted the tile and later cleared this add-on's data -- a normal
# troubleshooting step, unrelated to favourites -- lost the record while the
# counter and favourites.xml both survived, and the tile they had deleted came
# back. Keeping the record next to the counter it is compared against means one
# action cannot take one without the other.
SEEN_FILE = ('special://profile/addon_data/plugin.program.kodipovilwizard/'
             'recent_updates_tile_seen.txt')
REMOVED_TOKEN = 'user_removed'
# How many of the user's own favourites to remember. More than one because any
# single anchor can itself be deleted; few because this is a hint, not a backup.
ANCHOR_COUNT = 5
# The wizard bumps this every time it replaces userdata/favourites.xml with a
# per-skin seed, which is the only thing that does. Comparing it against the
# value we saw when we last seeded turns "who removed the tile" from a guess
# into a fact. The anchors below stay as a fallback for a device where the
# wizard is older than this and never writes the file.
REPLACED_FILE = ('special://profile/addon_data/'
                 'plugin.program.kodipovilwizard/favourites_replaced.txt')


def _replacement_count():
    """How many times the wizard has replaced favourites.xml.

    NO FILE MEANS ZERO, not "unknown". The wizard that writes it ships in the
    same quickfix as this patcher, so on any device running this code the file
    is simply absent until the first skin switch -- and reading that as unknown
    would send every ordinary device down the guessing path this exists to
    replace. A wizard too old to write it at all leaves the count at zero
    forever, which reads any missing tile as a deletion: the milder direction,
    and only reachable by mixing versions that ship together.
    """
    try:
        import xbmcvfs
        path = xbmcvfs.translatePath(REPLACED_FILE)
    except Exception:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return int((handle.read() or '0').strip() or 0)
    except FileNotFoundError:
        return 0
    except Exception:
        return None
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
        # The counter goes in with the anchors: what matters later is not its
        # value but whether it has MOVED since this moment.
        payload = {'state': state, 'anchors': list(anchors or []),
                   'replaced': _replacement_count()}
        # ATOMIC, like the favourites.xml write below it. A half-written record
        # is unreadable, and an unreadable record now costs the user their
        # tile -- so it must never be possible to observe one.
        tmp = path + '.tmp'
        # A stray DIRECTORY here blocks every future write, silently and
        # forever, because the failure is swallowed -- and a record that can
        # never be written is a deletion that can never be remembered. The
        # favourites.xml write below has this guard; this one needs it more.
        if os.path.isdir(tmp):
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        with open(tmp, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
        os.replace(tmp, path)
        return True
    except Exception as e:
        _log('could not record the tile state: {0}'.format(e), level='WARNING')
        return False


def _forget_sidecar():
    """Undo a record we just wrote, when the write it was covering failed.

    Best effort by design: if the removal itself fails, the record stays and
    says "offered" for a tile that never got written, so the next run reads a
    deletion the user never made and stops offering. That costs one user one
    tile. The opposite -- leaving the tile with no record -- costs them a tile
    they cannot remove, on every start, forever.
    """
    try:
        os.remove(_seen_path())
    except Exception:
        pass


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


def _guess_from_anchors(record, theirs):
    """The old, inferential answer. Only for a device whose wizard predates the
    replacement counter -- it is a guess, and every version of this guess has
    been wrong in one direction or the other."""
    anchors = [a for a in record.get('anchors') or [] if isinstance(a, str)]
    if not anchors:
        # Nothing to measure against, and no counter either. Fall back to the
        # safer of the two: offered once, not offered again. Re-seeding here,
        # as an earlier version did, put the tile back on every single boot.
        return 'already_seen'
    survived = sum(1 for a in anchors if a in theirs)
    # A majority, not all: requiring every anchor made MORE anchors mean MORE
    # false wipes, since deleting one unrelated favourite tripped it.
    if survived * 2 >= len(anchors):
        _write_sidecar(REMOVED_TOKEN)
        _log('the tile was removed by the user; not offering it again')
        return 'user_removed'
    return None


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

    now = _replacement_count()
    then = record.get('replaced')
    if record and now is not None and isinstance(then, int):
        if now <= then:
            # Nobody replaced the file since we seeded, and the tile is gone.
            # That was the user, whichever way they did it.
            _write_sidecar(REMOVED_TOKEN)
            _log('the tile was removed by the user; not offering it again')
            return 'user_removed'
        _log('favourites.xml was replaced {0} time(s) since we seeded it; '
             'restoring the tile'.format(now - then))
    elif record:
        verdict = _guess_from_anchors(record, theirs)
        if verdict:
            return verdict

    closing = text.rfind('</favourites>')
    if closing == -1:
        # Not a favourites file we understand. Writing into it blind could
        # cost the user every tile they have.
        _log('favourites.xml has no </favourites>; leaving it alone',
             level='WARNING')
        return 'unparseable'

    # RECORDED BEFORE THE TILE GOES IN, NOT AFTER -- and the seeding depends on
    # it. "No record" is read as "never offered", which is the only reading that
    # lets a first run ever seed anything; the danger is that it is also what a
    # LOST record looks like, and a lost record turns the user's deletion back
    # into a fresh offer on the next start. That reading cannot be made safe by
    # inspection, so it is made true by construction: while the record is
    # written first and the tile only follows a successful write, a tile can
    # never exist without a record, and absence really does mean we never got as
    # far as offering. Writing it afterwards -- as this did until now -- left
    # exactly one crack, a failed record write after a good favourites write,
    # and every start after that re-seeded a tile the user kept deleting.
    # The anchors come from the file as it was BEFORE we touch it: their
    # favourites, not ours.
    if not _write_sidecar('offered', theirs[:ANCHOR_COUNT]):
        # Offering something we cannot remember offering is how the tile
        # becomes impossible to get rid of. Rather not offer it.
        return 'write_failed'

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
        # Put the record back the way we found it. Left in place it would say
        # "offered" for a tile that is not there, and the next run would read
        # that as a deletion by a user who was never shown anything.
        _forget_sidecar()
        _log('could not write favourites.xml: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _log('seeded the "last ten updates" tile ({0} anchor(s) recorded)'
         .format(len(theirs[:ANCHOR_COUNT])))
    return 'seeded'

