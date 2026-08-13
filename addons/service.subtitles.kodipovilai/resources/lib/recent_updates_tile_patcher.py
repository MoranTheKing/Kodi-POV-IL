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
# For the same reason the record is kept in BOTH add-ons' folders and marked
# SEEDING until the tile is really in the file: a "Clear data" click must not
# be able to reach every copy, and a power cut must not be able to look like a
# deletion.

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
# IN BOTH add-ons' addon_data, because Kodi's per-add-on "Clear data" button
# wipes exactly one folder and there is such a button on EVERY add-on. Keeping
# one copy meant a single click could take the record while favourites.xml
# survived, and a tile the user had deleted came back:
#
#   record in OUR folder      -> "Clear data" on the subtitle add-on took it.
#   record beside the counter -> "Clear data" on the WIZARD took it, together
#                                with the counter -- and both gone reads as a
#                                fresh install, which is the same bug one
#                                add-on over.
#
# Two copies, and no single button can reach both. The counter is mirrored the
# same way and for the same reason -- a count that could be reset to zero by
# one click was just as fatal as a record that could be deleted by one, because
# a zero reads as "the file was never replaced" and turns every tile the wizard
# removed into a tile the user removed. Neither fact is now losable in one act.
SEEN_FILES = (
    'special://profile/addon_data/plugin.program.kodipovilwizard/'
    'recent_updates_tile_seen.txt',
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'recent_updates_tile_seen.txt',
)
REMOVED_TOKEN = 'user_removed'
# Written before the tile, replaced by OFFERED once the tile is really in the
# file. Anything that kills the process in between -- a power cut, a force
# close -- leaves this behind, and it is the only thing that distinguishes
# "we never finished offering" from "they deleted what we offered".
SEEDING_TOKEN = 'seeding'
OFFERED_TOKEN = 'offered'
# How many times an unfinished seed may be retried before it stops being read
# as unfinished. One genuine power cut needs one retry; a state that retries
# forever is a tile the user can never delete.
SEED_ATTEMPT_LIMIT = 2
# How many of the user's own favourites to remember. More than one because any
# single anchor can itself be deleted; few because this is a hint, not a backup.
ANCHOR_COUNT = 5
# The wizard bumps these every time it replaces userdata/favourites.xml with a
# per-skin seed, which is the only thing that does. Comparing the count against
# the value we saw when we last seeded turns "who removed the tile" from a
# guess into a fact. One copy per add-on folder, for the same reason the record
# is kept twice: one "Clear data" click must not be able to take it. A wiped
# copy reads as zero, so the HIGHEST of them is the count -- a copy that was
# reset cannot drag the other backwards.
REPLACED_FILES = (
    'special://profile/addon_data/plugin.program.kodipovilwizard/'
    'favourites_replaced.txt',
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'favourites_replaced.txt',
)
REPLACED_FILE = REPLACED_FILES[0]


def _counter_state():
    """(count, trustworthy).

    ABSENT AND UNREADABLE ARE NOT THE SAME THING, and conflating them cost an
    innocent user their tile. No file at all means zero replacements -- on any
    device running this code the file is simply absent until the first skin
    switch, and calling that "unknown" would send every ordinary device down
    the guessing path the counter exists to replace. But a file that IS there
    and cannot be read is damage, and reading damage as zero says "nobody has
    replaced favourites.xml" about a device where somebody may well have. That
    verdict is permanent, so it must not be reached by guessing.

    A copy we CAN read settles it: the count only ever grows, so the highest
    readable copy is a fact even if the other is corrupt.
    """
    values = []
    damaged = False
    for ref in REPLACED_FILES:
        try:
            import xbmcvfs
            path = xbmcvfs.translatePath(ref)
        except Exception:
            continue
        if not path:
            continue
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                values.append(int((handle.read() or '0').strip() or 0))
        except FileNotFoundError:
            continue
        except Exception:
            # There, and unreadable. Corrupt, truncated by a power cut, or
            # half-written -- on the SD cards these boxes run from, not exotic.
            damaged = True
    if values:
        return max(values), True
    if damaged:
        return 0, False
    return 0, True


def _replacement_count():
    """The count alone, for recording alongside a record we are writing."""
    if xbmcvfs is None:
        return None
    return _counter_state()[0]
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


def _seen_paths():
    """Every copy of the record, most authoritative first."""
    out = []
    for ref in SEEN_FILES:
        try:
            path = xbmcvfs.translatePath(ref)
        except Exception:
            continue
        if path:
            out.append(path)
    return out


def _read_one(path):
    """One copy: a dict, or None if there is no file there at all."""
    try:
        import json
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.loads(handle.read())
        return data if isinstance(data, dict) else {'state': REMOVED_TOKEN}
    except FileNotFoundError:
        return None
    except Exception:
        # THERE IS A FILE AND WE CANNOT READ IT. Truncated by a power cut,
        # corrupted, or written by an older format. Treating that as "never
        # seeded" throws away a recorded deletion and puts the tile back --
        # so an unreadable record is read as the deletion it most likely is.
        # The cost of being wrong this way is a tile somebody never sees
        # again; the other way it is a tile they cannot get rid of.
        return {'state': REMOVED_TOKEN}


def _sidecar():
    """The record, from whichever copies survive. Always a dict, never raises.

    Empty only when EVERY copy is gone, which no single "Clear data" can do.
    """
    copies = [_read_one(path) for path in _seen_paths()]
    present = [c for c in copies if c is not None]
    if not present:
        return {}
    for copy in present:
        # A recorded deletion outranks everything. If any surviving copy says
        # the user removed the tile, that is the answer -- the other copy is
        # not a second opinion, it is a copy that got wiped and came back.
        if copy.get('state') == REMOVED_TOKEN:
            return copy
    count, trustworthy = _counter_state()
    if copies and copies[0] is not None:
        record = dict(copies[0])
        if not trustworthy:
            # Every copy of the count is there and unreadable. Reading that as
            # zero says "nobody replaced favourites.xml" about a device where
            # somebody may well have -- and the verdict it leads to is
            # permanent. The record itself is fine; only the number is damage.
            record['counter_lost'] = True
        return record
    survivor = dict(present[0])
    if not trustworthy or not count:
        # The copy beside the counter is gone, and the count is either
        # unreadable or back at zero -- so whatever took the record took the
        # count with it. Comparing a snapshot against a zero that means "wiped"
        # rather than "never replaced" would read EVERY missing tile as a
        # deletion, including the ones the wizard removed itself. That is not
        # the conservative answer, it is a meaningless one. Say so, and let the
        # caller fall back to the anchors, which is the case they exist for.
        survivor['counter_lost'] = True
    return survivor


def _write_sidecar(state, anchors=None, attempts=0, require_all=False):
    """Write every copy.

    require_all decides what "success" means, and the two callers need
    different answers. Recording a DELETION: one copy beats none, always take
    it. Recording that we are about to OFFER: one copy is not the mechanism,
    it is the mechanism with its redundancy quietly gone, and one "Clear data"
    click on the surviving folder brings a deleted tile back -- the very bug
    the second copy exists to prevent. So an offer that cannot be remembered
    twice is not made at all.
    """
    import json
    # The counter goes in with the anchors: what matters later is not its
    # value but whether it has MOVED since this moment. Read ONCE, so both
    # copies carry the same number even if the wizard bumps it mid-write.
    payload = json.dumps({'state': state, 'anchors': list(anchors or []),
                          'replaced': _replacement_count(),
                          'seed_attempts': int(attempts or 0)},
                         ensure_ascii=False)
    written = 0
    for path in _seen_paths():
        try:
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            # ATOMIC, like the favourites.xml write below it. A half-written
            # record is unreadable, and an unreadable record now costs the user
            # their tile -- so it must never be possible to observe one.
            # The pid keeps two processes off one scratch path. Without it
            # both write the same tmp, one replaces it, and the other's
            # replace fails on a file that is no longer there -- a write lost
            # for no reason but a shared name.
            tmp = '{0}.{1}.tmp'.format(path, os.getpid())
            # A stray DIRECTORY here blocks every future write, silently and
            # forever, because the failure is swallowed -- and a record that
            # can never be written is a deletion that can never be remembered.
            # The favourites.xml write below has this guard; this needs it more.
            if os.path.isdir(tmp):
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
            with open(tmp, 'w', encoding='utf-8') as handle:
                handle.write(payload)
            os.replace(tmp, path)
            written += 1
        except Exception as e:
            # Take the scratch file with us. A rename that fails once will
            # usually fail again, and the name carries the pid -- so left
            # alone, every restart adds another one, forever.
            try:
                os.remove('{0}.{1}.tmp'.format(path, os.getpid()))
            except Exception:
                pass
            _log('could not record the tile state at {0}: {1}'
                 .format(path, e), level='WARNING')
    if require_all:
        # Against the CONSTANT, not against _seen_paths(): if a path failed to
        # resolve, that list is shorter, and "every copy landed" would be
        # satisfied by the one that did -- the redundancy gone, silently, in
        # the exact check written to prevent that.
        return written == len(SEEN_FILES)
    return written > 0


def _sidecar_is_whole():
    """True when every copy is on disk. A missing one is healed on sight."""
    paths = _seen_paths()
    return bool(paths) and all(os.path.exists(p) for p in paths)


def _forget_sidecar():
    """Undo a record we just wrote, when the write it was covering failed.

    Best effort by design: if a removal fails, that copy stays and claims a
    tile was offered that never got written, so the next run reads a deletion
    the user never made and stops offering. That costs one user one tile. The
    opposite -- leaving the tile with no record -- costs them a tile they
    cannot remove, on every start, forever.
    """
    for path in _seen_paths():
        try:
            os.remove(path)
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


def _guess_from_anchors(record, theirs, may_record=True):
    """The old, inferential answer. Only for a device whose wizard predates the
    replacement counter, or one where the counter cannot be read -- it is a
    guess, and every version of this guess has been wrong in one direction or
    the other.

    may_record is what stops a guess hardening into a fact. Recording
    REMOVED_TOKEN is permanent: the first check on every later start returns
    on it and never looks at the counter again. That is the right weight for
    an answer read off the counter, and far too much for one read off a
    handful of favourites that the skin seed may itself contain -- the seeds
    share tiles, so a "surviving" anchor can be a build tile that survives
    everything. So with no readable counter the tile is still not restored --
    the promise is that a deletion sticks, and this start cannot prove it was
    not one -- but nothing is written down, and the next start decides again,
    on facts if the counter has come back."""
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
        if may_record:
            _write_sidecar(REMOVED_TOKEN)
            _log('the tile was removed by the user; not offering it again')
        else:
            _log('the tile is gone and the replacement count cannot be read; '
                 'leaving it alone this start, without recording a verdict')
        return 'user_removed'
    return None


def ensure_patched():
    """'no_kodi' | 'no_favourites' | 'already_present' | 'user_removed'
    | 'already_seen' | 'read_failed' | 'unparseable' | 'write_failed'
    | 'seeded'."""
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
        if (not record.get('anchors')
                or record.get('state') != OFFERED_TOKEN
                or not _sidecar_is_whole()):
            # Three repairs in one write, all of them "the tile is here and the
            # record does not say so properly":
            #   no anchors     -- a fresh install whose seed already carried the
            #                     tile, so this never ran. Without anchors the
            #                     user's first deletion has nothing to be
            #                     measured against and would read as a wipe.
            #   still SEEDING  -- the tile went in but the second record write
            #                     did not. Settle it now.
            #   a copy missing -- one "Clear data" took it. Put it back while
            #                     the tile is here to prove it belongs.
            _write_sidecar(OFFERED_TOKEN, theirs[:ANCHOR_COUNT])
        return 'already_present'

    now = _replacement_count()
    then = record.get('replaced')
    try:
        attempts = int(record.get('seed_attempts') or 0)
    except Exception:
        attempts = 0
    if record.get('state') == SEEDING_TOKEN and attempts < SEED_ATTEMPT_LIMIT:
        # We wrote the record, then died before the tile reached the file --
        # a power cut, a force close, a kill. The user was never shown
        # anything, so there is no deletion here to respect; the checks below
        # would read this as one and take the tile away from someone who never
        # saw it. Fall through and finish what the last run started.
        #
        # COUNTED, because "unfinished" must be a phase and not a home. If the
        # write that settles the state can never land, this state persists with
        # the tile sitting in the file, and every deletion the user makes is
        # read as another unfinished seed and undone -- a tile they cannot get
        # rid of, which is the one thing this feature promised.
        _log('a previous seed did not finish; trying again '
             '(attempt {0})'.format(attempts + 1))
    elif (record.get('counter_lost')
          or (now is not None and isinstance(then, int) and now < then)):
        # Either the counter could not be read, or it has gone BACKWARDS since
        # we seeded -- and it cannot: the wizard only ever counts up. A count
        # below its own snapshot is therefore not a low number, it is a reset
        # or a corrupted read, and comparing against it would say "nobody
        # replaced the file" about a device where the wizard may well have.
        # The anchors are the fallback for exactly this, and they answer it
        # well: a wizard-driven replacement takes the user's own favourites
        # with it, a deletion leaves them in place -- but only well enough to
        # act on now, never well enough to write down.
        verdict = _guess_from_anchors(record, theirs, may_record=False)
        if verdict:
            return verdict
    elif record and now is not None and isinstance(then, int):
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
    # It goes down as SEEDING, not OFFERED, because between here and the write
    # below the process can simply stop existing. The anchors come from the file
    # as it was BEFORE we touch it: their favourites, not ours.
    if not _write_sidecar(SEEDING_TOKEN, theirs[:ANCHOR_COUNT],
                          attempts=attempts + 1, require_all=True):
        # Offering something we cannot remember offering -- in both places -- is
        # how the tile becomes impossible to get rid of. Rather not offer it.
        # A partial write is worse than none, so take back whatever landed.
        _forget_sidecar()
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
        # Put the record back the way we found it. Left behind it would claim a
        # tile that is not there, and while SEEDING is the one state that reads
        # correctly as "unfinished", clearing it is still tidier than relying on
        # that -- and it is what makes a first run after this look like a first
        # run.
        _forget_sidecar()
        _log('could not write favourites.xml: {0}'.format(e), level='WARNING')
        return 'write_failed'

    # The tile is really in the file now, so the record can stop saying it is
    # halfway there. If THIS write fails the state stays SEEDING with the tile
    # present, and the next run heals it above -- no path leaves a tile that
    # the record cannot account for.
    _write_sidecar(OFFERED_TOKEN, theirs[:ANCHOR_COUNT])
    _log('seeded the "last ten updates" tile ({0} anchor(s) recorded)'
         .format(len(theirs[:ANCHOR_COUNT])))
    return 'seeded'

