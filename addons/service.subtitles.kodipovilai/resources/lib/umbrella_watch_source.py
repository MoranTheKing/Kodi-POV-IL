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
# are connected. That is a decision about this build, not a technical one.
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

MARKER_SETTING = '_umb_watch_source_v1'


def _settled():
    """The keys we have already had our one say about."""
    try:
        raw = kodi_utils.get_setting(MARKER_SETTING, '') or ''
    except Exception:
        return set()
    return set(k for k in (p.strip() for p in raw.split(',')) if k)


def settle(keys):
    try:
        kodi_utils.set_setting(MARKER_SETTING, ','.join(sorted(keys)))
    except Exception:
        pass


def pairs(read_umbrella, source):
    """(key, value) pairs to write so Umbrella reads watched state from
    `source`, plus the set of keys to settle afterwards.

    `read_umbrella(key)` returns Umbrella's current value, or None when it
    cannot be read -- and None settles nothing, because a key we could not
    read is a key we have not had our say about yet."""
    done = _settled()
    out, touched = [], set(done)
    for key in KEYS:
        if key in done:
            continue
        try:
            current = read_umbrella(key)
        except Exception:
            current = None
        if current is None:
            continue
        touched.add(key)          # we looked; that is our one look
        if current == SHIPPED_LOCAL:
            out.append((key, source))
    return out, touched
