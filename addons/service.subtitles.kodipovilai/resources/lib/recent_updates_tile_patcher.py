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
# that replaces the file, so it leaves a mark as it does; this records that
# mark when it seeds, and later:
#
#   the mark changed -> the file was replaced -> put the tile back
#   the mark did not -> nobody replaced it   -> that was the user -> never again
#
# A fact, for the price of one string. The anchors remain only as a fallback
# for the one case the mark cannot settle: every copy of it damaged at once.
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
#   record in OUR folder    -> "Clear data" on the subtitle add-on took it.
#   record beside the mark  -> "Clear data" on the WIZARD took it, together
#                              with the mark -- and both gone reads as a fresh
#                              install, which is the same bug one add-on over.
#
# Two copies, and no single button can reach both. The wizard's mark is
# mirrored the same way and for the same reason -- a mark one click could take
# was just as fatal as a record one click could take, because a folder with no
# mark in it reads as "the file was never replaced" and turns every tile the
# wizard removed into a tile the user removed. Neither fact is losable in one
# act now.
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
# The wizard writes a fresh mark here every time it replaces
# userdata/favourites.xml with a per-skin seed, which is the only thing that
# does. Comparing the mark against the one we saw when we last seeded turns
# "who removed the tile" from a guess into a fact. One copy per add-on folder,
# for the same reason the record is kept twice: one "Clear data" click must not
# be able to take it.
#
# A MARK, NOT A COUNT. This was a counter for three rounds of review, and the
# counter is what the fourth killed. To increment a count you first have to
# read it, and every way of reading it wrong still yields a perfectly ordinary
# number -- just a smaller one. A corrupt copy read as nothing, so the wizard
# rewrote a device's count of 4 as 1; the reader, comparing against the 4 it
# had recorded, watched the number climb back past 4 over the next few skin
# switches and concluded that the user had deleted a tile the wizard itself had
# removed. Gone for good, on a device whose owner had done nothing but switch
# skins. A mark is written without ever being read, so nothing can rewind it,
# and the only question ever asked of it -- "is this still the mark I saw?" --
# has no wrong-but-plausible answers, only right, different, or unreadable.
REPLACED_FILES = (
    'special://profile/addon_data/plugin.program.kodipovilwizard/'
    'favourites_replaced.txt',
    'special://profile/addon_data/service.subtitles.kodipovilai/'
    'favourites_replaced.txt',
)
# There is a file and it cannot be read. Not a mark -- the wizard writes uuid4
# hex, which cannot contain a '!' -- and not None, because both of those mean
# something definite and this means "no idea".
DAMAGED = '!damaged'
SAME, REPLACED, UNKNOWN = 'same', 'replaced', 'unknown'


def _marker_pair():
    """What each copy of the wizard's mark says right now.

    Three values, and conflating any two of them has cost somebody their tile
    at least once already:

        None      -- no file at all. Nothing has ever replaced favourites.xml.
        a mark    -- what the wizard's last replacement wrote.
        DAMAGED   -- there is a file and it cannot be read.
    """
    if xbmcvfs is None:
        return [DAMAGED for _ in REPLACED_FILES]
    out = []
    for ref in REPLACED_FILES:
        try:
            path = xbmcvfs.translatePath(ref)
        except Exception:
            path = ''
        if not path:
            out.append(DAMAGED)
            continue
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                # Empty is half-written, which is damage, not a mark.
                out.append((handle.read() or '').strip() or DAMAGED)
        except FileNotFoundError:
            out.append(None)
        except Exception:
            # There, and unreadable. Corrupt, truncated by a power cut, or
            # half-written -- on the SD cards these boxes run from, not exotic.
            out.append(DAMAGED)
    return out


def _marker_moved(then, now):
    """Has the wizard replaced favourites.xml since `then` was recorded?

    SAME | REPLACED | UNKNOWN, per copy and then over the pair:

        was       is        verdict
        --------------------------------------------------------------------
        anything  the same  SAME      nothing wrote it
        None      a mark    REPLACED  a mark appeared, and only a replacement
                                      writes one
        DAMAGED   a mark    REPLACED  only a write heals damage
        a mark    another   REPLACED  rewritten
        anything  None      UNKNOWN   a mark cannot un-write itself, so this is
                                      damage, not evidence
        anything  DAMAGED   UNKNOWN   it may be a new mark, corrupted

    Over the pair: one copy showing a new mark is proof, so any REPLACED wins.
    Failing that, one copy still holding the mark we recorded is proof that
    nothing wrote it -- a replacement writes both -- so SAME beats UNKNOWN.
    Only when neither copy can say anything is the answer unknown.

    THE PAIR IS COMPARED AS A PAIR, never copy against copy. A copy whose write
    once failed sits there holding an older mark forever, and against a single
    recorded value that stale copy reads as "different" -- which is the reading
    that puts a deleted tile back.
    """
    if not isinstance(then, list) or len(then) != len(now):
        # No snapshot, or one written by a different shape of this code.
        return UNKNOWN
    verdicts = []
    for was, is_ in zip(then, now):
        if was == is_:
            verdicts.append(SAME)
        elif is_ is None or is_ == DAMAGED:
            verdicts.append(UNKNOWN)
        else:
            verdicts.append(REPLACED)
    if REPLACED in verdicts:
        return REPLACED
    if SAME in verdicts:
        return SAME
    return UNKNOWN
_FAV_ACTION_RE = re.compile(r'<favourite\b[^>]*>(.*?)</favourite>', re.S)
TILE_NAME = '[B][COLOR yellow]10 העדכונים האחרונים[/COLOR][/B]'
TILE_THUMB = 'special://home/media/build_icons/Wizard/wizard_pov_il.png'
TILE_ACTION = ('RunPlugin("plugin://plugin.program.kodipovilwizard/'
               '?mode=recentupdates")')
TILE = ('    <favourite name="{0}" thumb="{1}">{2}</favourite>'
        .format(TILE_NAME, TILE_THUMB, TILE_ACTION))


# THE TILE OPENS A WIZARD ROUTE, AND THE WIZARD IS UPDATED SEPARATELY.
# `?mode=recentupdates` was added to the wizard's router in 0.1.46. This
# patcher ships in the ADD-ON, which reaches a device through the quickfix --
# a different channel, arriving first. Between the two, the tile was on the
# home screen and did nothing at all: pressing it ran the plugin, no branch in
# the router matched, and the script exited in about a millisecond. A user
# reported exactly that, and the log showed it precisely -- "[ mode:
# recentupdates ]" followed by "script successfully run", with wizard v0.1.45
# installed.
#
# So the tile is not offered until the thing it opens exists. Checked against
# the wizard actually installed, not against what this build shipped with,
# because those are not the same on a device mid-update. A wizard we cannot
# read at all is treated as too old: the cost is one boot's delay, and the
# alternative is the dead tile again.
WIZARD_ADDON_ID = 'plugin.program.kodipovilwizard'
WIZARD_MIN_VERSION = (0, 1, 46)


def _wizard_can_serve_the_tile():
    """Is the INSTALLED wizard new enough to answer the tile's route?"""
    try:
        import xbmcaddon
        raw = xbmcaddon.Addon(WIZARD_ADDON_ID).getAddonInfo('version')
    except Exception:
        # Not installed, or Kodi still calls it unknown this early. Either way
        # this is not the boot to offer the tile on.
        return False
    try:
        parts = tuple(int(p) for p in str(raw).strip().split('.')[:3])
    except Exception:
        # An unparseable version is not evidence of anything. Do not guess it
        # is new enough; a dead tile is worse than a late one.
        return False
    return parts >= WIZARD_MIN_VERSION


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
    """One copy: the dict it holds, DAMAGED if there is a file we cannot read,
    or None if there is no file there at all.

    THREE ANSWERS, NOT TWO, for the same reason the wizard's mark has three.
    This used to hand back a synthetic {'state': REMOVED_TOKEN} for anything
    unreadable -- a conservative reading, and the right one when it is all we
    have. What made it wrong was that it did not look like a guess by the time
    _sidecar saw it, so a corrupt copy could outvote a perfectly legible one
    that disagreed. Keep the guess, but keep it labelled.
    """
    try:
        import json
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.loads(handle.read())
        return data if isinstance(data, dict) else DAMAGED
    except FileNotFoundError:
        return None
    except Exception:
        # Truncated by a power cut, corrupted, or written by an older format.
        return DAMAGED


def _sidecar():
    """The record, from whichever copies survive. Always a dict, never raises.

    Empty only when EVERY copy is gone, which no single "Clear data" can do.
    """
    copies = [_read_one(path) for path in _seen_paths()]
    legible = [c for c in copies if isinstance(c, dict)]
    if not legible:
        if any(c is DAMAGED for c in copies):
            # Every copy that exists is unreadable. Now the conservative
            # reading IS the only reading: treating it as "never seeded" would
            # throw away a deletion we may well have recorded and put the tile
            # back. The cost of being wrong this way is a tile somebody never
            # sees again; the other way it is a tile they cannot get rid of.
            #
            # LABELLED, because a caller has to be able to tell this apart from
            # a removal somebody actually wrote down. The repair path treats a
            # present tile as proof that the record is wrong and rewrites it --
            # right when the record is this guess, and a silent erasure of the
            # user's decision when it is a real one.
            return {'state': REMOVED_TOKEN, 'inferred': True}
        return {}
    for copy in legible:
        # A recorded deletion outranks everything -- among copies that can
        # actually be read. If a surviving copy says the user removed the tile,
        # that is the answer; the other copy is not a second opinion, it is a
        # copy that got wiped and came back.
        #
        # A COPY WE CANNOT READ DOES NOT GET A VOTE HERE. One corrupted byte in
        # one of the two used to be enough: the unreadable copy was turned into
        # a removal and returned without so much as consulting the healthy copy
        # sitting next to it saying "offered". Nothing else had to happen -- the
        # tile was still on screen, the user had touched nothing -- and from
        # that boot on, the first line of ensure_patched returned on it and the
        # self-heal below could never run again. The next perfectly ordinary
        # skin switch then took the tile away for good.
        if copy.get('state') == REMOVED_TOKEN:
            return copy
    # NO SECOND-GUESSING THE MARK FROM HERE. This used to flag the record when
    # the wizard's copy of it was gone and the count read zero, on the theory
    # that whatever took the record took the count with it -- and that guess is
    # precisely what let a deleted tile come back. A genuine zero, on the very
    # many devices where nobody has ever switched skin, is indistinguishable
    # from a wiped one, so the user's deletion was seen, believed, and then
    # deliberately not written down for fear of the wrong reason -- and the
    # next skin switch put the tile back. _marker_moved answers the question
    # itself now, where "no file" is a value with a meaning rather than a
    # suspicious number.
    if isinstance(copies[0], dict):
        return dict(copies[0])
    return dict(legible[0])


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
    # The mark goes in with the anchors: what matters later is not what it says
    # but whether it has CHANGED since this moment. Read ONCE, so both copies
    # carry the same pair even if the wizard writes a new mark mid-write.
    payload = json.dumps({'state': state, 'anchors': list(anchors or []),
                          'replaced_token': _marker_pair(),
                          'seed_attempts': int(attempts or 0)},
                         ensure_ascii=False)
    written = 0
    for path in _seen_paths():
        try:
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                # exist_ok, because two processes can reach this line at once
                # and the loser used to take a FileExistsError as "this copy
                # could not be written" -- and with require_all that is an
                # offer withdrawn over a directory that does exist.
                os.makedirs(directory, exist_ok=True)
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
    """True when every copy is on disk AND readable. Anything less is healed on
    sight, while the tile is there to prove what the record should say.

    READABLE, not merely present: a corrupted copy passes every other test in
    the heal condition -- it exists, and the legible copy beside it says
    OFFERED with anchors -- so nothing repaired it, and it sat there as a live
    hazard until the day it was the only copy left."""
    paths = _seen_paths()
    return bool(paths) and all(isinstance(_read_one(p), dict) for p in paths)


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


def _guess_from_anchors(record, theirs):
    """The old, inferential answer, for the one case the mark cannot settle:
    no copy of it able to say anything. It is a guess, and every version of
    this guess has been wrong in one direction or the other.

    IT NEVER WRITES A VERDICT DOWN. Recording REMOVED_TOKEN is permanent -- the
    first check on every later start returns on it and never looks at the mark
    again -- which is the right weight for an answer read off the mark and far
    too much for one read off a handful of favourites that the skin seed may
    itself contain: the seeds share tiles, so a "surviving" anchor can be a
    build tile that survives everything. So a start with no readable mark still
    does not restore the tile -- the promise is that a deletion sticks, and
    this start cannot prove it was not one -- but nothing is written down, and
    the next start decides again on facts, because the caller re-baselines the
    snapshot to the mark as it reads now before asking."""
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
        _log("the tile is gone and the wizard's mark cannot be read; leaving "
             'it alone this start, without recording a verdict')
        return 'user_removed'
    return None


def ensure_patched():
    """'no_kodi' | 'no_favourites' | 'already_present' | 'user_removed'
    | 'already_seen' | 'read_failed' | 'unparseable' | 'write_failed'
    | 'seed_abandoned' | 'wizard_too_old' | 'seeded'."""
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

    now = _marker_pair()
    # THE TILE ITSELF OUTRANKS ANYTHING THE RECORD SAYS -- so this is asked
    # first. A tile sitting in favourites.xml cannot be a tile the user
    # removed; whatever the record thinks, the file in front of us settles it.
    # Asking the record first meant an unreadable one returned "removed" with
    # the tile plainly on screen, and the repair below -- the one thing that
    # could have fixed the record while the tile was there to prove what it
    # should say -- was unreachable from that moment on. The fuzzer found this
    # the same hour its own dead invariant was repaired; it had been sitting
    # underneath it the whole time.
    if has_tile:
        if (record.get('state') == REMOVED_TOKEN
                and not record.get('inferred')):
            # A DELETION SOMEBODY ACTUALLY WROTE DOWN, and a tile in the file
            # anyway. Leave both exactly as they are.
            #
            # This is the hole the has_tile reordering opened, and it opened it
            # the same day it was written: the repair below fires on any record
            # that is not OFFERED, so it rewrote a recorded removal to
            # "offered" -- and then the next skin switch to a seed WITHOUT the
            # tile read as an ordinary wizard removal, and put back the tile
            # the user had deleted. The comment above considered only two ways
            # a tile can be present against a REMOVED record, an unreadable
            # record and a manual re-add, and both are fine to re-offer. It
            # missed the third, which the repair list two lines up names out
            # loud: a per-skin seed can carry the tile itself. No seed we ship
            # today does -- I checked every one in the build -- but seeding it
            # is exactly what the open "tile on all four skins" item would do,
            # and the record would be quietly erased on the devices that got it.
            #
            # The cost of this guard: a user who deletes the tile and then
            # re-creates it by hand does not get that re-add remembered as a
            # fresh offer, so a later skin switch will not restore it for them.
            # Against silently forgetting every user's deletion, that is not a
            # close call.
            return 'already_present'
        if (not record.get('anchors')
                or record.get('state') != OFFERED_TOKEN
                or not _sidecar_is_whole()
                or record.get('replaced_token') != now):
            # Four repairs in one write, all of them "the tile is here and the
            # record does not say so properly":
            #   no anchors     -- a fresh install whose seed already carried the
            #                     tile, so this never ran. Without anchors the
            #                     user's first deletion has nothing to be
            #                     measured against and would read as a wipe.
            #   still SEEDING  -- the tile went in but the second record write
            #                     did not. Settle it now.
            #   a copy missing
            #   or unreadable  -- one "Clear data" took it, or a bad sector
            #                     ate it. Put it back while the tile is here to
            #                     prove it belongs.
            #   the mark moved -- somebody wrote a mark and the tile survived
            #                     it, which a real replacement cannot do: it
            #                     overwrites the whole file. So the mark ran
            #                     ahead of a copy that never happened, and if
            #                     that is left standing, the user's next
            #                     deletion reads as that replacement and the
            #                     tile comes back. The tile is here NOW, so
            #                     here is the honest baseline.
            #
            # A REMOVED record still reaches here when it is the INFERRED one
            # -- no copy legible, so the removal is this module's own guess and
            # the tile in front of us is better evidence than the guess. A
            # removal that was really written down returned above.
            _write_sidecar(OFFERED_TOKEN, theirs[:ANCHOR_COUNT])
        return 'already_present'

    if record.get('state') == REMOVED_TOKEN:
        # They told us to go away. Nothing reopens that.
        return 'user_removed'

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
    elif record:
        moved = _marker_moved(record.get('replaced_token'), now)
        if record.get('state') == SEEDING_TOKEN and moved != REPLACED:
            # OUT OF ATTEMPTS ON A SEED THAT NEVER LANDED. Every branch below
            # is written for a tile that was successfully offered and has since
            # gone missing, and asks the mark who took it. THIS attempt never
            # put anything in favourites.xml -- the record says so, and a
            # favourites write that fails takes its own record back down, so
            # SEEDING surviving here means the process died between the two.
            # Falling through asked "did anyone replace the file?", got the
            # perfectly true answer "no", and wrote down a deletion for a tile
            # that this run never wrote -- on a first install, one the user had
            # never once seen. (Not always a first install: a re-seed after a
            # wipe can exhaust its attempts the same way, and there the tile
            # HAS been seen before. Either way the verdict was invented, which
            # is what makes it wrong.)
            #
            # So: stop, and record nothing. Not a rollback of the record --
            # that would read as "never offered" on the next start and seed
            # again, which is the retry loop this limit exists to end, and it
            # would run for as long as the settling write kept failing: a tile
            # the user deletes and deletes and cannot get rid of. Leaving the
            # exhausted record exactly where it is says "we gave up" and stays
            # said. A later mark, though, is real evidence that the wizard has
            # been through the file, and that earns a fresh attempt.
            _log('a previous seed never finished after {0} attempts; leaving '
                 'it alone rather than inventing a verdict'.format(attempts))
            return 'seed_abandoned'
        if moved == SAME:
            # Nobody replaced the file since we seeded, and the tile is gone.
            # That was the user, whichever way they did it.
            _write_sidecar(REMOVED_TOKEN)
            _log('the tile was removed by the user; not offering it again')
            return 'user_removed'
        if moved == UNKNOWN:
            # No copy of the mark can speak: both damaged, or gone from a
            # folder something wiped.
            #
            # RE-BASELINE FIRST, and then guess. Recording the mark as it reads
            # NOW is what keeps damage from becoming permanent: leave the old
            # snapshot in place and the pair stays uncomparable for as long as
            # the damage lasts, so every start goes on guessing off anchors
            # that a skin seed can itself supply -- and the one thing that
            # cannot happen from the guessing path is the tile ever being
            # settled. With the snapshot re-baselined, whatever this start
            # cannot settle the next one can: the mark either still reads the
            # way it does now, which means nothing wrote it, or it does not,
            # which means the wizard did.
            _write_sidecar(record.get('state') or OFFERED_TOKEN,
                           record.get('anchors'), attempts=attempts)
            verdict = _guess_from_anchors(record, theirs)
            if verdict:
                return verdict
        else:
            _log("the wizard's mark changed since we seeded the tile, so it "
                 'replaced favourites.xml; restoring the tile')

    if not _wizard_can_serve_the_tile():
        # Nothing is written down: no record, no attempt counted. The next
        # start asks again, and the tile appears the moment the wizard that
        # can open it is in place.
        _log('the installed wizard is older than {0}, which is where the tile'
             "'s route lives; not offering it yet"
             .format('.'.join(str(n) for n in WIZARD_MIN_VERSION)))
        return 'wizard_too_old'

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

