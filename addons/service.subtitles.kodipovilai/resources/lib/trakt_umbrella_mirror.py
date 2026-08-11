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
# The watched-indicator switch is set ONLY on the first connect, when
# Umbrella held no Trakt token. Umbrella asks that question itself at the end
# of its own authorisation ("set Trakt as your service for watched and
# unwatched indicators?"), so once Umbrella HAS Trakt, indicators.alt sitting
# at 0 means the user was asked and said no -- and flipping it then would
# reverse a decision they made. When we are the ones connecting, they were
# never asked, so there is no answer to overrule.

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


POV_ADDON_ID = 'plugin.video.pov'
UMBRELLA_ADDON_ID = 'plugin.video.umbrella'

POV_TOKEN = 'trakt.token'
POV_REFRESH = 'trakt.refresh'
POV_EXPIRES = 'trakt.expires'
POV_USER = 'trakt_user'
POV_CLIENT_ID = 'trakt.client_id'
POV_CLIENT_SECRET = 'trakt.client_secret'

UMB_TOKEN = 'trakt.user.token'

UMBRELLA_GUARD_PROPERTY = 'umbrella.updateSettings'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('trakt_umbrella_mirror: ' + msg, level=level)
    except Exception:
        pass


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
    | 'unchanged' | 'mirrored' | 'write_failed'. Never raises."""
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

    if umb_token == token:
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
    if first_connect:
        # Only now -- see the module header on why this is not touched again.
        wanted.append(('indicators.alt', '1'))
        wanted.append(('scrobble.source', '1'))

    changed, _restored, failed = addon_settings_safe.apply(
        UMBRELLA_ADDON_ID, tuple(wanted),
        guard_property=UMBRELLA_GUARD_PROPERTY)
    if failed:
        _log('mirror did not stick ({0}) -- will retry'
             .format(', '.join(failed)), level='WARNING')
        return 'write_failed'
    if not changed:
        return 'unchanged'
    _log('Umbrella now shares POV\'s Trakt authorisation{0}'.format(
        ' (and takes watched state from it)' if first_connect else ''),
        level='INFO')
    return 'mirrored'
