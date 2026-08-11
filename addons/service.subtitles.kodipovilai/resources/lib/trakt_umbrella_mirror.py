# One Trakt authorisation for POV and Umbrella.
#
# Same shape as the MDBList mirror, and for the same reason: connecting Trakt
# in this build connects POV, and Umbrella is left with nothing -- which is
# also why Umbrella showed every episode unwatched while POV showed the
# ticks. Account Manager exists to solve this, but its Trakt route ends in
# os._exit(1) (Kodi force-closes) and its traktAuth turns Kodi's add-on
# updates off, so this build deliberately routes Trakt to POV instead. That
# left Umbrella out.
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
    from resources.lib import addon_settings_safe
except Exception:
    addon_settings_safe = None

try:
    from resources.lib import umbrella_watch_source
except Exception:
    umbrella_watch_source = None


POV_ADDON_ID = 'plugin.video.pov'
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


def _get(addon_id, key):
    if xbmcaddon is None:
        return None
    try:
        return (xbmcaddon.Addon(addon_id).getSetting(key) or '').strip()
    except Exception:
        return None      # not installed / unreadable -- not the same as ''


def mirror():
    """Give Umbrella POV's Trakt authorisation, pointed at POV's Trakt app.

    Returns 'no_pov' | 'no_umbrella' | 'no_token' | 'incomplete'
    | 'unchanged' | 'mirrored' | 'adopted' | 'write_failed'.
    Never raises."""
    if addon_settings_safe is None:
        return 'write_failed'

    token = _get(POV_ADDON_ID, POV_TOKEN)
    if token is None:
        return 'no_pov'
    refresh = _get(POV_ADDON_ID, POV_REFRESH)
    client_id = _get(POV_ADDON_ID, POV_CLIENT_ID)
    client_secret = _get(POV_ADDON_ID, POV_CLIENT_SECRET)
    expires = _get(POV_ADDON_ID, POV_EXPIRES) or ''
    user = _get(POV_ADDON_ID, POV_USER) or ''

    umb_token = _get(UMBRELLA_ADDON_ID, UMB_TOKEN)
    if umb_token is None:
        return 'no_umbrella'

    if not token:
        # POV is not connected. Umbrella may hold a perfectly good
        # authorisation of its own -- leave it alone.
        return 'no_token'
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
    if (umb_token and umb_token != token
            and _get(UMBRELLA_ADDON_ID, 'trakt.authed.clientid') == client_id
            and _get(UMBRELLA_ADDON_ID, UMB_REFRESH)
            and _newer(_get(UMBRELLA_ADDON_ID, UMB_EXPIRES), expires)):
        back = (
            (POV_TOKEN, umb_token),
            (POV_REFRESH, _get(UMBRELLA_ADDON_ID, UMB_REFRESH)),
            (POV_EXPIRES, _get(UMBRELLA_ADDON_ID, UMB_EXPIRES) or ''),
        )
        _changed, _restored, failed = addon_settings_safe.apply(
            POV_ADDON_ID, back)
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
    src, settle_keys = [], None
    if umbrella_watch_source is not None and not _get(
            UMBRELLA_ADDON_ID, 'mdblist.token'):
        src, settle_keys = umbrella_watch_source.pairs(
            lambda k: _get(UMBRELLA_ADDON_ID, k), umbrella_watch_source.TRAKT)

    if umb_token == token and not src:
        # Nothing to write, but the look at the watch-source settings still
        # counts -- see the same branch in mdblist_umbrella_mirror for why
        # skipping it here would quietly re-claim a setting the user moved
        # back to Local.
        if settle_keys and umbrella_watch_source is not None:
            umbrella_watch_source.settle(settle_keys)
        return 'unchanged'

    first_connect = not umb_token

    wanted = [
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
        _log('mirror did not stick ({0}) -- will retry'
             .format(', '.join(failed)), level='WARNING')
        return 'write_failed'
    if settle_keys and umbrella_watch_source is not None:
        umbrella_watch_source.settle(settle_keys)
    if not changed:
        return 'unchanged'
    _log('Umbrella now shares POV\'s Trakt authorisation{0}'.format(
        ' (and takes watched state from it)' if first_connect else ''),
        level='INFO')
    return 'mirrored'
