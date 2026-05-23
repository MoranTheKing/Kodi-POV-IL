# Integration with the bundled DarkSubs (service.subtitles.All_Subs)
# addon.
#
# DarkSubs ships with its own machine-translate engine (Google
# Translate / Bing / Yandex) enabled by default. That's fine on its
# own, but means a user who's set up our AI subtitles addon gets
# competing Hebrew entries in the subtitle search dialog -- the
# Google-translated rows often outrank ours, so they end up with
# Google's translation instead of the (much higher quality) Gemini
# one they wanted.
#
# Solution: once, when the user signals they've adopted our addon
# (i.e. set a Gemini API key), turn DarkSubs's auto_translate off
# so the only Hebrew translations on offer come from us. The user
# can flip it back on any time from DarkSubs's settings.

try:
    import xbmcaddon
except ImportError:
    xbmcaddon = None

from . import kodi_utils

DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
DARKSUBS_AUTO_TRANSLATE_SETTING = 'auto_translate'

# Setting that records whether we've already done the one-shot
# DarkSubs takeover for this profile. Stored under our own
# settings so the user can reset it if they ever want DarkSubs
# back as the default translator.
TAKEOVER_DONE_SETTING = '_darksubs_takeover_done'


def darksubs_installed():
    if not xbmcaddon:
        return False
    try:
        xbmcaddon.Addon(DARKSUBS_ADDON_ID)
        return True
    except Exception:
        return False


def maybe_disable_darksubs_translate():
    """If the user has a Gemini key set, DarkSubs is installed,
    and we haven't already done the takeover, flip DarkSubs's
    auto_translate setting off. Idempotent -- the
    TAKEOVER_DONE_SETTING gate makes sure we don't keep stomping
    on a user who deliberately re-enabled DarkSubs translation.

    Returns one of:
      'done'      -- we just disabled DarkSubs's auto_translate
      'skipped'   -- already done or preconditions not met
      'failed'    -- exception during the attempt (logged)
    """
    # Don't bother unless the user has actually adopted us.
    if not (kodi_utils.get_setting('api_key', '') or '').strip():
        return 'skipped'
    if not darksubs_installed():
        return 'skipped'
    if kodi_utils.get_setting(TAKEOVER_DONE_SETTING, '') == '1':
        return 'skipped'

    try:
        dark = xbmcaddon.Addon(DARKSUBS_ADDON_ID)
        # Only act if it's currently true -- if the user already
        # turned it off, leave the takeover-marker so we don't
        # re-check on every search call.
        current = (dark.getSetting(DARKSUBS_AUTO_TRANSLATE_SETTING) or '').lower()
        if current == 'true':
            dark.setSetting(DARKSUBS_AUTO_TRANSLATE_SETTING, 'false')
            kodi_utils.log(
                'DarkSubs takeover: auto_translate -> false',
                level='INFO')
        kodi_utils.set_setting(TAKEOVER_DONE_SETTING, '1')
        return 'done'
    except Exception as e:
        kodi_utils.log(
            'DarkSubs takeover failed: {0}'.format(e), level='WARNING')
        return 'failed'
