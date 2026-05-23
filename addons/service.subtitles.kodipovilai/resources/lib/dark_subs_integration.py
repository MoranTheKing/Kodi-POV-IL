# Integration with the bundled DarkSubs (service.subtitles.All_Subs)
# addon.
#
# DarkSubs has a built-in machine-translation step that fires when
# the user picks a non-Hebrew subtitle (auto_translate=true by
# default, using Google Translate / Bing / Yandex). That's good UX
# but the AI we ship is dramatically better quality, so when the
# user has set up our addon (Gemini API key present), we want
# DarkSubs's "auto-translate" to actually call OUR translator.
#
# Approach: patch DarkSubs's engine.py on disk to inject a small
# hook at the top of machine_translate_subs. The hook calls into
# our addon via RunScript if a Gemini key is set, and falls through
# to the original Google/Bing/Yandex logic on any failure (no key,
# crash, timeout). See darksubs_patcher.py for the actual injection
# logic; this module is just the orchestration entry point.
#
# Behaviour summary:
#   - No Gemini key set       : identical to upstream DarkSubs
#   - Gemini key set + works  : DarkSubs uses our AI on every
#                               non-Hebrew subtitle pick
#   - Gemini key set + fails  : DarkSubs falls through to its
#                               own Google Translate (no regression)

try:
    import xbmcaddon
except ImportError:
    xbmcaddon = None

from . import kodi_utils
from . import darksubs_patcher

DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'


def darksubs_installed():
    if not xbmcaddon:
        return False
    try:
        xbmcaddon.Addon(DARKSUBS_ADDON_ID)
        return True
    except Exception:
        return False


def _restore_auto_translate_if_we_disabled_it():
    """The v0.1.1 "disable handshake" set DarkSubs's auto_translate
    to 'false' for users with a Gemini key. With the new design that
    is REGRESSION-causing: DarkSubs's download_sub only calls
    machine_translate_subs (where our hook lives) when auto_translate
    is 'true'. So users who got the v0.1.1 takeover end up with
    plain English subs -- neither AI nor Google translates them.

    We use the takeover marker that v0.1.1 left behind ('1' in
    `_darksubs_takeover_done`) as a signal that WE were the ones
    who turned auto_translate off. In that case, flip it back on
    and clear the marker. We don't touch users whose auto_translate
    was off for any other reason (the marker is missing for them).
    """
    if not xbmcaddon:
        return
    if kodi_utils.get_setting('_darksubs_takeover_done', '') != '1':
        return
    try:
        dark = xbmcaddon.Addon(DARKSUBS_ADDON_ID)
        current = (dark.getSetting('auto_translate') or '').lower()
        if current == 'false':
            dark.setSetting('auto_translate', 'true')
            kodi_utils.log(
                'Restored DarkSubs auto_translate to true so the '
                'new AI hook can actually fire',
                level='INFO')
        # Marker no longer needed; clear so we don't keep checking.
        kodi_utils.set_setting('_darksubs_takeover_done', '')
    except Exception as e:
        kodi_utils.log(
            'DarkSubs auto_translate restore failed: {0}'.format(e),
            level='WARNING')


def maybe_patch_darksubs():
    """Ensure DarkSubs's engine.py has our AI translation hook
    injected, if DarkSubs is installed. Safe to call repeatedly --
    the patcher is idempotent and won't touch the file if it's
    already patched or if DarkSubs's function shape has changed
    (in which case the hook is silently skipped and DarkSubs keeps
    working as upstream).

    ALSO undoes the auto_translate=false damage left by the v0.1.1
    disable-handshake code, so the hook can actually fire.

    Returns the same status strings as darksubs_patcher.ensure_patched()
    plus 'not_installed' if DarkSubs is missing.
    """
    if not darksubs_installed():
        return 'not_installed'

    # First: heal the bad state the v0.1.1 takeover left behind.
    _restore_auto_translate_if_we_disabled_it()

    try:
        status = darksubs_patcher.ensure_patched()
    except Exception as e:
        kodi_utils.log(
            'DarkSubs patch attempt crashed: {0}'.format(e),
            level='WARNING')
        return 'failed'
    return status
