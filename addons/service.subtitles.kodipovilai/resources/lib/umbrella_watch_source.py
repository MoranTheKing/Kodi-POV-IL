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

MARKER_SETTING = '_umb_watch_source_v1'


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


def settle(done):
    """Record what we did about each key.

    Writes only on a change. The callers settle on their fast path too -- the
    one taken on almost every pass -- and this runs on a timer, so an
    unconditional set_setting() would rewrite our settings.xml every tick for
    the life of the box."""
    value = ','.join('%s=%s' % (k, v) for k, v in sorted(done.items()))
    try:
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
    the user having chosen Trakt by hand."""
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
