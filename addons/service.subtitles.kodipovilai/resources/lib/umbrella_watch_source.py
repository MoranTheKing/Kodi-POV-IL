# Which service Umbrella takes watched state and resume points from.
#
# Two settings, and each is a single CHOICE rather than a switch:
#
#   indicators.alt   Watch History & Indicators   0 local 1 Trakt 2 Simkl 3 MDBList
#   scrobble.source  Scrobble & Resume Points     0 local 1 Trakt 2 Simkl 3 MDBList
#
# Umbrella ships both at 0, so watched state stays on the device and never
# lines up with POV. That is the whole of "everything is connected and there
# are still no ticks": connecting a service does not make Umbrella READ from
# it, and nothing in the build was choosing.
#
# The order of preference is MDBList, then Trakt -- MDBList wins when both
# are connected. That is a decision about this build, not a technical one,
# and it has to hold whichever service was connected FIRST. Connecting Trakt
# on its own rightly puts Trakt here; MDBList arriving later must be able to
# take over, so the marker records what we wrote rather than only that we
# wrote something, and MDBList may replace a Trakt value of our own making.
# Ordering the two calls is not enough on its own: the instant trigger on
# POV's Connect Services screen fires the MDBList mirror alone, from its own
# process, while the timer keeps calling both.
#
# Claimed ONCE per setting, behind a marker, and only while the setting still
# reads the shipped 0:
#
#   * once, so that a user who later puts one back to Local keeps it there
#     and is not overruled again fifteen minutes later by the keeper;
#   * only from 0, so a source somebody has already chosen -- by hand, or by
#     answering Umbrella's own Trakt dialog -- is never taken away from them.
#     Reversing that answer is exactly what made an earlier attempt at this
#     a blocker, and the rule is worth stating twice rather than losing once;
#   * per setting, so somebody who moved one and not the other keeps the one
#     they moved.
#
# Deliberately NOT gated on "this is the first connect". That was the first
# shape of this and it only ever helped a device connecting for the first
# time -- everybody already connected, which is everybody who reported the
# missing ticks, would have kept Local forever.

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


INDICATORS = 'indicators.alt'
SCROBBLE = 'scrobble.source'
KEYS = (INDICATORS, SCROBBLE)

SHIPPED_LOCAL = '0'
TRAKT = '1'
MDBLIST = '3'

# Recorded against a key we looked at but deliberately did not write. Never
# replaced -- whatever is in that setting was not put there by us.
NOTHING = '-'

# v2, deliberately: changing the id spends one more claim on every device.
#
# WHY, HONESTLY. A user reported lists in Umbrella but no watched state after
# revoking MDBList in POV, in Umbrella and in Account Manager and reconnecting.
# The mechanism first written here -- that AM's revoke resets these two
# settings -- is WRONG, and checking it against AM 1.1.5a is what showed that:
# its Umbrella MDBList revoke clears `mdblist.api` and nothing else
# (acct_vwr.py data_mdb), and Umbrella's own mdblistRevoke clears only the two
# tokens. Neither goes near indicators.alt. The likeliest explanation is far
# duller: the claim shipped in 0.2.482, minutes before the report, and their
# device did not have it yet.
#
# The bump stays anyway, as a judgement call rather than a diagnosis. Anybody
# actually sitting with a spent marker and Local comes right silently instead
# of through a support conversation, and the cost is bounded: the claim is
# still only ever taken FROM Local, still only once, so the only person who
# loses anything is one who deliberately chose Local while connected, and they
# can choose it again. Recorded as a guess so nobody later mistakes it for
# evidence.
MARKER_SETTING = '_umb_watch_source_v2'


def _done():
    """{key: the value we wrote there, or NOTHING if we wrote none}."""
    raw = ''
    try:
        raw = (kodi_utils.get_setting(MARKER_SETTING, '') or '').strip()
    except Exception:
        raw = ''
    out = {}
    for part in raw.split(','):
        key, _sep, value = part.strip().partition('=')
        key = key.strip()
        if key:
            # A bare key with no value is the older shape of this marker:
            # settled, value unknown. Read as "wrote nothing", which is the
            # conservative reading -- NOTHING is never replaced.
            out[key] = value.strip() or NOTHING
    return out


def settle(done, skip=()):
    """Record what we did about each key.

    MERGED into what the marker already says, not written over it. Two of
    these run in different processes -- the timer, and the instant trigger on
    POV's Connect Services screen -- each holding the marker as it was when
    they started, so a plain overwrite lets the later one drop what the
    earlier one just recorded.

    `skip` is the keys whose write did NOT stick. They keep whatever the
    marker had before, because recording a write that did not happen is worse
    than recording nothing: next pass would find our own value standing there
    unclaimed, read it as the user's, and refuse the takeover that was owed.
    This build's own set_setting notes that some Kodi/Android builds swallow
    a write and report success, so it is not a theoretical branch.

    Writes only on a change: this runs on a timer."""
    try:
        merged = _done()
        for key, value in done.items():
            if key in skip:
                continue
            if value == NOTHING and merged.get(key) not in (None, NOTHING):
                # Never demote a recorded claim to "not ours". The merge alone
                # does not settle same-key contention: the other process may
                # have read Umbrella AFTER we claimed the setting but BEFORE
                # we recorded it, in which case it saw a value it had no
                # record of and concluded it was the user's. Letting that
                # conclusion land would lose the claim for good -- NOTHING is
                # never replaced -- and the setting could then never be
                # re-claimed from Local. A concrete value is only ever written
                # here by the process that wrote it to Umbrella, so preferring
                # it over NOTHING is always the right way round.
                continue
            merged[key] = value
        value = ','.join('%s=%s' % (k, v) for k, v in sorted(merged.items()))
        if (kodi_utils.get_setting(MARKER_SETTING, '') or '').strip() == value:
            return
        kodi_utils.set_setting(MARKER_SETTING, value)
    except Exception:
        pass


def pairs(read_umbrella, source, may_replace=()):
    """(key, value) pairs to write so Umbrella reads watched state from
    `source`, plus the marker state to settle afterwards.

    `read_umbrella(key)` returns Umbrella's current value, or None when it
    cannot be read -- and None settles nothing, because a key we could not
    read is a key we have not had our say about yet.

    `may_replace` is the set of values this source outranks, and it is what
    makes "MDBList wins" true whatever order the two services were connected
    in. Connecting Trakt alone legitimately puts Trakt in these settings; if
    MDBList is connected afterwards it has to be able to take over, and
    without this it could not -- the key would already be settled and the
    preference would come down to which service the user happened to connect
    first. The replacement is allowed ONLY when the value standing there is
    still exactly the one WE wrote: anything else is the user's, including
    the user having chosen Trakt by hand.

    THERE IS NO "the user just reconnected, so take it again" CASE, and three
    rounds of review went into learning why. The repair it chased -- our claim
    recorded, the setting somehow back at Local -- is real but was never
    demonstrated in the field, while every signal tried for "a human just
    connected" turned out to fire without one: an empty Umbrella token (its
    own Revoke, and Trakt's re_auth clearing itself on a failed refresh), then
    "POV is connected right now" (the connect row fires whatever the outcome,
    so a declined confirmation counted), then "POV's token changed" (POV
    rotates it on its own timer). Each attempt silently reverted a source the
    user had chosen. What actually delivers the repair is a one-shot: bump
    MARKER_SETTING and every device gets one more claim, from Local only.
    """
    done = _done()
    out, touched = [], dict(done)
    for key in KEYS:
        try:
            current = read_umbrella(key)
        except Exception:
            current = None
        if current is None:
            continue
        prev = done.get(key)
        if prev is None:
            # Our one look at this key.
            if current == SHIPPED_LOCAL:
                out.append((key, source))
                touched[key] = source
            else:
                touched[key] = NOTHING
        elif prev != source and prev in may_replace and current == prev:
            out.append((key, source))
            touched[key] = source
    return out, touched
