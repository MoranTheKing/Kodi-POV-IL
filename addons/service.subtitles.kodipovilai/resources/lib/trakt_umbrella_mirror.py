# One Trakt authorisation for POV and Umbrella.
#
# Same shape as the MDBList mirror, and for the same reason: connecting Trakt
# in this build connects POV, and Umbrella is left with nothing -- which is
# also why Umbrella showed every episode unwatched while POV showed the
# ticks. Account Manager exists to solve this, but its Trakt route ends in
# os._exit(1) -- Kodi force-closes -- which its author confirms is deliberate
# and is not going to change: AM rewrites the Trakt handling inside the
# add-ons it supports, so they must be restarted to rebuild their Trakt
# databases. Reasonable for AM; not something a build's main connect screen
# can do. So this build routes Trakt to POV instead, and that left Umbrella
# out.
#
# Trakt is NOT like MDBList, though. An MDBList access token authenticates
# the user and any client may present it, which is why simply handing POV's
# token to Umbrella works. A Trakt token is bound to the application that
# issued it: every call carries a `trakt-api-key` header holding the client
# id, and Trakt rejects a token that was not issued to that application. So
# POV's token is only usable by something identifying itself as POV's app.
#
# Umbrella supports exactly that, as a documented feature -- the "Use Custom
# Trakt API Keys" switch on its Online Services screen:
#
#     def traktClientID():
#         traktId = '87e3f0...'
#         if getSetting('trakt.clientid') != '' and \
#            getSetting('traktuserkey.customenabled') == 'true':
#             traktId = getSetting('trakt.clientid')
#         return traktId
#
# So we point Umbrella at POV's Trakt application through its own supported
# setting and hand over POV's token. No source patch, nothing private:
# Account Manager achieves the same end by REWRITING the client id inside
# Umbrella's trakt.py, which is both more invasive and undone by the next
# Umbrella update. This is the same arrangement, made through the switch
# Umbrella put there for it.
#
# `trakt.authed.clientid` matters and is easy to miss. Umbrella compares it
# against traktClientID() and treats a mismatch as "these credentials belong
# to a different application", so it has to say POV's client id or Umbrella
# will decide its own token is foreign and drop it.
#
# WHAT IS DELIBERATELY NOT WRITTEN:
#   resume.source -- Account Manager writes it and Umbrella's own traktAuth
#     writes it, but it is not declared in Umbrella's settings.xml, so the
#     write is a no-op for all three of us. Umbrella reads scrobble.source
#     for resume points (player.py), which IS declared, and that is what we
#     set instead. Writing a setting that does not exist is how the MDBList
#     sync came to report success while doing nothing.
#
# The watched-indicator switch is NOT gated on "this is the first connect".
# That was the first shape of this and it only ever helped a device
# connecting for the first time, while everybody already connected -- which
# is everybody who reported the missing ticks -- kept Local forever. The rule
# that replaced it lives in umbrella_watch_source: claim a setting once, and
# only while it still reads the shipped Local. Umbrella asks that question
# itself at the end of its own authorisation ("set Trakt as your service for
# watched and unwatched indicators?"), and anything other than the shipped 0
# is an answer somebody gave, so the "only from 0" rule is what protects it.
# `first_connect` below survives for the log line and nothing else.

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None

try:
    from resources.lib import addon_presence
except Exception:
    addon_presence = None

try:
    from resources.lib import addon_settings_safe
except Exception:
    addon_settings_safe = None

try:
    from resources.lib import umbrella_watch_source
except Exception:
    umbrella_watch_source = None


POV_ADDON_ID = 'plugin.video.pov'

# The build-wide "make no change to plugin.video.pov" switch. Its help text
# promises exactly that, without qualification, and this module holds the one
# write to POV in either mirror -- so it has to answer to the switch or the
# switch is not true. Read here rather than imported from service.py: that
# module is the Kodi service entry point and importing it from a library is
# how you get a second copy of the service running.
POV_PATCHING_OFF_SETTING = '_pov_patching_off'
UMBRELLA_ADDON_ID = 'plugin.video.umbrella'

POV_TOKEN = 'trakt.token'
POV_REFRESH = 'trakt.refresh'
POV_EXPIRES = 'trakt.expires'
POV_USER = 'trakt_user'
POV_CLIENT_ID = 'trakt.client_id'
POV_CLIENT_SECRET = 'trakt.client_secret'

UMB_TOKEN = 'trakt.user.token'
UMB_REFRESH = 'trakt.refreshtoken'
UMB_EXPIRES = 'trakt.token.expires'

UMBRELLA_GUARD_PROPERTY = 'umbrella.updateSettings'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('trakt_umbrella_mirror: ' + msg, level=level)
    except Exception:
        pass


def _pov_writes_off():
    if kodi_utils is None:
        return False
    try:
        return (kodi_utils.get_setting(POV_PATCHING_OFF_SETTING, '')
                or '').strip().lower() == 'true'
    except Exception:
        return False


def _newer(a, b):
    """True when epoch-seconds string `a` is strictly later than `b`.

    POV stores trakt.expires as int(created_at + expires_in) and Umbrella
    stores trakt.token.expires as str(time.time() + expires_in) -- different
    formatting, same clock, so a float compare works on both. Anything that
    does not parse is treated as "not newer": this decides whether to take
    Umbrella's copy over POV's, and a guess in that direction is how you lose
    the live credential."""
    try:
        return float(a) > float(b)
    except (TypeError, ValueError):
        return False


def _reader(addon_id):
    """A read function backed by ONE Addon object, for the life of this call.

    Same reasoning as the MDBList mirror: constructing xbmcaddon.Addon()
    re-parses that add-on's whole settings.xml, this pass reads nine of POV's
    keys, and it now runs every minute. Not cached between passes -- noticing
    a token POV refreshed in the background is the entire point of the timer.

    Returns None for every key when the add-on is not installed.

    Through addon_presence rather than by construction, for the reason spelt
    out in the MDBList mirror: asking Kodi about an add-on it does not have
    leaves an ERROR line in the log every single pass."""
    if xbmcaddon is None:
        return lambda _key: None
    addon = (addon_presence.addon(addon_id)
             if addon_presence is not None else None)
    if addon is None:
        return lambda _key: None

    def _get(key):
        try:
            return (addon.getSetting(key) or '').strip()
        except Exception:
            return None
    return _get


def mirror():
    """Give Umbrella POV's Trakt authorisation, pointed at POV's Trakt app.

    Returns 'no_pov' | 'no_umbrella' | 'no_token' | 'incomplete'
    | 'unchanged' | 'mirrored' | 'adopted' | 'pov_writes_off'
    | 'write_failed'. Never raises."""
    if addon_settings_safe is None:
        return 'write_failed'

    pov = _reader(POV_ADDON_ID)
    token = pov(POV_TOKEN)
    if token is None:
        return 'no_pov'
    if not token:
        # POV is not connected. Umbrella may hold a perfectly good
        # authorisation of its own -- leave it alone. Checked before Umbrella
        # is opened at all: on a box with no Trakt this is every pass, and it
        # is the difference between one settings.xml reparse a minute and
        # nine.
        return 'no_token'

    refresh = pov(POV_REFRESH)
    client_id = pov(POV_CLIENT_ID)
    client_secret = pov(POV_CLIENT_SECRET)
    expires = pov(POV_EXPIRES) or ''
    user = pov(POV_USER) or ''

    umbrella = _reader(UMBRELLA_ADDON_ID)
    umb_token = umbrella(UMB_TOKEN)
    if umb_token is None:
        return 'no_umbrella'

    if not (refresh and client_id and client_secret):
        # Without the application's own id and secret Umbrella cannot present
        # this token as POV, and without the refresh token it cannot survive
        # the first expiry. Half of this is worse than none of it.
        _log('POV Trakt is present but incomplete -- not mirroring',
             level='WARNING')
        return 'incomplete'

    # WHICHEVER SIDE ROTATED LAST OWNS THE PAIR.
    #
    # Trakt refresh tokens are single-use: the refresh that hands back a new
    # access token also hands back a new REFRESH token and retires the old
    # one. Once Umbrella is running as POV's application it can and does
    # refresh on its own -- re_auth() fires on any 401 it meets in the
    # background and writes the rotated pair into its own settings. If we
    # then pushed POV's older copy back over it, Umbrella would be holding a
    # refresh token Trakt has already retired, and its next refresh gets
    # invalid_grant -- at which point Umbrella clears the whole
    # authorisation and tells the user to re-authorise (trakt.py re_auth).
    # POV's copy would be just as dead.
    #
    # So when Umbrella holds a DIFFERENT token that expires LATER than POV's,
    # Umbrella is the one that refreshed and POV is the stale side. Copy it
    # back instead, and both are on the live pair again. Guarded on
    # trakt.authed.clientid, because a token Umbrella got as ITSELF is issued
    # to Umbrella's application and is no use to POV.
    #
    # Read once into locals and write those same values: re-reading them for
    # the write would leave a window where Umbrella refreshes again between
    # the test and the copy, and POV would end up with halves of two pairs.
    umb_refresh = umbrella(UMB_REFRESH) or ''
    umb_expires = umbrella(UMB_EXPIRES) or ''
    adopt = (umb_token and umb_token != token and umb_refresh
             and umbrella('trakt.authed.clientid') == client_id
             and _newer(umb_expires, expires))
    # The switch forbids the write to POV, and it does NOT permit the opposite
    # either: mirroring POV's stale copy over the pair Umbrella has just
    # rotated would retire Umbrella's working refresh token. So the TOKEN work
    # stands down -- and ONLY the token work.
    #
    # Standing the whole function down here was the first shape of this and it
    # was wrong for a reason worth writing out: with the switch on, POV's
    # expiry never advances, so this condition stays true on every tick for as
    # long as the switch is on. Returning early took the watch-source claim
    # down with it, permanently and silently, on a switch documented as
    # touching nothing but POV.
    stale = bool(adopt and _pov_writes_off())
    if adopt and not stale:
        # The username comes across too. It is not needed to authenticate,
        # but POV shows it, and a screen naming one account while holding
        # another account's token is the kind of thing that gets diagnosed
        # as "Trakt is broken".
        back = [(POV_TOKEN, umb_token), (POV_REFRESH, umb_refresh),
                (POV_EXPIRES, umb_expires)]
        umb_user = umbrella('trakt.user.name') or ''
        if umb_user and umb_user != user:
            back.append((POV_USER, umb_user))
        _changed, _restored, failed = addon_settings_safe.apply(
            POV_ADDON_ID, tuple(back))
        if failed:
            _log('could not adopt Umbrella\'s refreshed Trakt token ({0})'
                 .format(', '.join(failed)), level='WARNING')
            return 'write_failed'
        _log('adopted the Trakt token Umbrella refreshed -- POV\'s copy was '
             'the stale one', level='INFO')
        return 'adopted'

    # Which service Umbrella should READ watched state from. Trakt only
    # claims it when MDBList has not -- both settings are a single choice and
    # this build prefers MDBList when the two are connected together.
    # No may_replace: Trakt never takes these off MDBList, in either
    # direction. The mdblist.token gate covers the common case; the marker
    # covers the rest.
    src, settle_keys = [], None
    if umbrella_watch_source is not None and not umbrella('mdblist.token'):
        src, settle_keys = umbrella_watch_source.pairs(
            umbrella, umbrella_watch_source.TRAKT)

    if (stale or umb_token == token) and not src:
        # Nothing to write, but the look at the watch-source settings still
        # counts -- see the same branch in mdblist_umbrella_mirror for why
        # skipping it here would quietly re-claim a setting the user moved
        # back to Local.
        if settle_keys and umbrella_watch_source is not None:
            umbrella_watch_source.settle(settle_keys)
        return 'pov_writes_off' if stale else 'unchanged'

    first_connect = not umb_token

    wanted = [] if stale else [
        # The application first, then the switch that makes Umbrella use it:
        # the token is only meaningful once Umbrella is identifying itself as
        # POV's app.
        ('trakt.clientid', client_id),
        ('trakt.clientsecret', client_secret),
        ('traktuserkey.customenabled', 'true'),
        ('trakt.user.name', user),
        ('trakt.user.token', token),
        ('trakt.refreshtoken', refresh),
        ('trakt.token.expires', expires),
        # Must match traktClientID() or Umbrella treats its own credentials
        # as belonging to someone else.
        ('trakt.authed.clientid', client_id),
        ('trakt.isauthed', 'true'),
    ]
    wanted.extend(src)

    changed, _restored, failed = addon_settings_safe.apply(
        UMBRELLA_ADDON_ID, tuple(wanted),
        guard_property=UMBRELLA_GUARD_PROPERTY)
    if failed:
        # Same as the MDBList mirror: keep whatever the watch-source keys
        # actually achieved, so a failure on the token does not lose the
        # record of a claim that landed.
        if settle_keys and umbrella_watch_source is not None:
            umbrella_watch_source.settle(settle_keys, skip=failed)
        _log('mirror did not stick ({0}) -- will retry'
             .format(', '.join(failed)), level='WARNING')
        return 'write_failed'
    if settle_keys and umbrella_watch_source is not None:
        umbrella_watch_source.settle(settle_keys)
    if not changed:
        return 'pov_writes_off' if stale else 'unchanged'
    if stale:
        return 'pov_writes_off'
    _log('Umbrella now shares POV\'s Trakt authorisation{0}'.format(
        ' (and takes watched state from it)' if first_connect else ''),
        level='INFO')
    return 'mirrored'
