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

    # Second: one-time auto-enable of auto_translate for users with
    # a Gemini key but the toggle still off (e.g. they're on the
    # current DarkSubs which ships default=true but their userdata
    # override has it false).
    _maybe_auto_enable_translate()

    # Third: relabel DarkSubs's "Enable machine translation" toggle
    # to hint at the AI integration.
    _maybe_relabel_auto_translate()

    try:
        status = darksubs_patcher.ensure_patched()
    except Exception as e:
        kodi_utils.log(
            'DarkSubs patch attempt crashed: {0}'.format(e),
            level='WARNING')
        return 'failed'
    return status


def _gemini_key_set():
    """True iff the user has configured a Gemini API key in our
    addon. Used to decide whether the auto-enable handshake is
    appropriate (no key -> nothing for the hook to do, so leave
    DarkSubs alone)."""
    return bool((kodi_utils.get_setting('api_key', '') or '').strip())


def _maybe_auto_enable_translate():
    """One-time enable of DarkSubs's auto_translate setting when
    the user has a Gemini key but the toggle is currently off.
    Idempotent via a marker in our addon -- if the marker is
    present we never touch DarkSubs again, even if the user later
    flips the toggle back off (we respect that explicit choice).

    Result on first run with a Gemini key:
      - DarkSubs auto_translate flipped to 'true'
      - Marker '_darksubs_autoenable_done' stored as '1'
      - One-time toast surfaced so the user knows what changed

    No-ops if:
      - No Gemini key set (don't enable Google translate fallback
        on users who haven't opted in to AI)
      - Marker already set (we did this before)
      - auto_translate already 'true' (no need to flip)
      - DarkSubs / xbmcaddon unavailable
    """
    if not xbmcaddon:
        return
    if not _gemini_key_set():
        return
    if kodi_utils.get_setting('_darksubs_autoenable_done', '') == '1':
        return
    try:
        dark = xbmcaddon.Addon(DARKSUBS_ADDON_ID)
        current = (dark.getSetting('auto_translate') or '').lower()
        if current == 'true':
            # Already on -- just mark so we don't recheck every boot.
            kodi_utils.set_setting('_darksubs_autoenable_done', '1')
            return
        dark.setSetting('auto_translate', 'true')
        kodi_utils.set_setting('_darksubs_autoenable_done', '1')
        kodi_utils.log(
            'Auto-enabled DarkSubs auto_translate so the AI '
            'hook can fire on first non-Hebrew subtitle pick',
            level='INFO')
        try:
            kodi_utils.notify(
                'תרגום AI הופעל ב-DarkSubs', time_ms=5000)
        except Exception:
            pass
    except Exception as e:
        kodi_utils.log(
            'Auto-enable of DarkSubs auto_translate failed: '
            '{0}'.format(e), level='WARNING')


_SETTINGS_REL_PATH = 'resources/settings.xml'
_OLD_LABEL = 'label="הפעל תרגום מכונה"'
_NEW_LABEL = 'label="הפעל תרגום מכונה (Gemini AI)"'


def _settings_xml_path():
    """On-disk path to DarkSubs's settings.xml. Empty when Kodi
    APIs aren't available."""
    try:
        import xbmcvfs as _vfs
    except ImportError:
        return ''
    try:
        base = _vfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''
    import os
    p = os.path.join(base, _SETTINGS_REL_PATH)
    return p if os.path.isfile(p) else ''


def _maybe_relabel_auto_translate():
    """Rewrite the label of DarkSubs's auto_translate toggle so the
    settings UI hints that AI is the translator. Surgical: only
    touches the exact baseline label string; user/upstream edits
    don't match and are left alone. Idempotent via a marker
    substring in the new label (Gemini AI)."""
    path = _settings_xml_path()
    if not path:
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        kodi_utils.log(
            'DarkSubs settings.xml read failed: {0}'.format(e),
            level='WARNING')
        return
    if _NEW_LABEL in content:
        return  # already relabelled
    if _OLD_LABEL not in content:
        return  # upstream changed the label; leave alone
    new_content = content.replace(_OLD_LABEL, _NEW_LABEL, 1)
    import os
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        kodi_utils.log(
            'Relabelled DarkSubs auto_translate to indicate '
            'Gemini AI integration', level='INFO')
    except OSError as e:
        try: os.remove(tmp)
        except OSError: pass
        kodi_utils.log(
            'DarkSubs settings.xml relabel failed: {0}'.format(e),
            level='WARNING')
