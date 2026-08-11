# One MDBList authorisation for both add-ons.
#
# Connecting MDBList used to mean doing it twice: once here (an API key,
# paired by QR) and once inside Umbrella (a short code typed on mdblist.com).
# That is not a limitation of MDBList -- it was ours. POV and Umbrella want
# the SAME credential and get it the same way:
#
#   POV      menus/myservices.py MDBList.set()
#              POST oauth/device-authorization/  -> user_code + QR
#              poll oauth/token/                 -> access_token, refresh_token
#              mdblist.token = access_token, mdblist.refresh = refresh_token
#   Umbrella modules/mdblist.py mdblistAuth()
#              POST oauth/device-authorization/  -> user_code
#              poll oauth/token/                 -> access_token, refresh_token
#              mdblist.token = access_token
#
# and both then send `Authorization: Bearer <access_token>` to the same
# api.mdblist.com. So one authorisation produces a token both can use, and the
# second trip round the loop bought nothing.
#
# POV even says so itself, in indexers/mdblist_api.py:
#
#     if not bool(get_setting('mdblist.refresh')): params['apikey'] = ...
#     else: headers = {'Authorization': 'Bearer %s' % ...}
#
# -- an api_key when there is no refresh token, a Bearer when there is. That
# line is also the test this module relies on: a POV `mdblist.token` with NO
# `mdblist.refresh` beside it is an API KEY, not an access token, and copying
# it into Umbrella would produce exactly the failure this replaces (connected,
# and empty), because Umbrella only ever sends Bearer. So we mirror only when
# POV holds a real OAuth pair.
#
# THE REFRESH. The two add-ons have different OAuth client_ids -- POV's is a
# hidden setting, Umbrella's is hardcoded -- and a refresh token belongs to
# the client it was issued to. Sharing one token would leave whichever add-on
# did not issue it unable to refresh. So Umbrella is deliberately given the
# access token and NO refresh token, because its own refresher begins:
#
#     refresh_token = getSetting('mdblist.refresh.token')
#     if not refresh_token: return
#
# With that empty it never tries, never fails, and simply uses what it is
# given. POV owns the refreshing -- with its own client_id, which is the only
# one that can -- and this module re-mirrors whenever POV's token has moved.
# Run at every startup, so a refresh POV did yesterday reaches Umbrella today.
#
# NOT YET PROVEN IN THE FIELD: that MDBList accepts a token issued to POV's
# client for calls Umbrella makes. It should -- an OAuth resource server
# authenticates the user behind the token, not the client presenting it -- but
# it is an assumption until a real account has run it, and it is written down
# here rather than left implied.

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

# POV's pair. `refresh` is what proves the token is OAuth and not an API key.
POV_TOKEN = 'mdblist.token'
POV_REFRESH = 'mdblist.refresh'

# Umbrella's. Its refresh is written EMPTY on purpose -- see the header.
UMB_TOKEN = 'mdblist.token'
UMB_REFRESH = 'mdblist.refresh.token'

UMBRELLA_GUARD_PROPERTY = 'umbrella.updateSettings'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('mdblist_umbrella_mirror: ' + msg, level=level)
    except Exception:
        pass


def _get(addon_id, key):
    if xbmcaddon is None:
        return None
    try:
        return (xbmcaddon.Addon(addon_id).getSetting(key) or '').strip()
    except Exception:
        return None      # not installed, or unreadable -- not the same as ''


def mirror():
    """Give Umbrella whatever MDBList access token POV currently holds.

    Returns 'no_pov' | 'no_umbrella' | 'no_token' | 'api_key_only'
    | 'unchanged' | 'mirrored' | 'write_failed'. Never raises."""
    if addon_settings_safe is None:
        return 'write_failed'

    token = _get(POV_ADDON_ID, POV_TOKEN)
    if token is None:
        return 'no_pov'
    refresh = _get(POV_ADDON_ID, POV_REFRESH)
    if refresh is None:
        return 'no_pov'

    umb_token = _get(UMBRELLA_ADDON_ID, UMB_TOKEN)
    if umb_token is None:
        return 'no_umbrella'

    if not token:
        # POV has nothing. Deliberately NOT clearing Umbrella: it may hold a
        # perfectly good token of its own, authorised inside Umbrella before
        # any of this existed, and taking that away would be a regression
        # dressed up as tidiness.
        return 'no_token'

    if not refresh:
        # An API key, not an access token. Umbrella only sends Bearer, so
        # copying this would reproduce the exact bug this module replaces.
        return 'api_key_only'

    if umb_token == token:
        return 'unchanged'

    changed, _restored, failed = addon_settings_safe.apply(
        UMBRELLA_ADDON_ID,
        ((UMB_TOKEN, token), (UMB_REFRESH, '')),
        guard_property=UMBRELLA_GUARD_PROPERTY)
    if failed:
        _log('mirror did not stick ({0}) -- will retry next startup'
             .format(', '.join(failed)), level='WARNING')
        return 'write_failed'
    if not changed:
        return 'unchanged'
    _log('Umbrella now shares POV\'s MDBList authorisation', level='INFO')
    return 'mirrored'
