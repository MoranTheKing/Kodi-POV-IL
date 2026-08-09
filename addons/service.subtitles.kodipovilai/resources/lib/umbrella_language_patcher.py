# Self-healing patch: give Umbrella the MODERN addon-language layout so its
# settings labels render on a Hebrew-interface Kodi.
#
# Symptom (field report, first day of the Umbrella pilot): Umbrella's
# settings dialog shows blank category names and blank setting labels --
# only the toggles/values render.
#
# Root cause: Umbrella ships its strings ONLY in the legacy folder layout
# (resources/language/English/strings.po, German/, Polish/ ...). Kodi 21
# resolves addon strings by locale folder: it looks for
# resource.language.he_il, then falls back to resource.language.en_gb --
# and Umbrella has NEITHER, so every label lookup returns an empty string.
# English-interface users are saved by the legacy folder name happening to
# match their language, which is why upstream never notices. POV and
# CocoScrapers both ship the modern layout, which is why they render fine
# on the same devices.
#
# The fix is purely ADDITIVE: copy English/strings.po into a new
# resource.language.en_gb/ folder inside the installed addon. No upstream
# byte is modified, so Umbrella's own repo updates keep applying cleanly --
# and because an update REPLACES the addon folder (removing our copy), this
# runs every Kodi startup and re-heals, refreshing the copy whenever
# upstream's English strings change. No-op in the common case and for the
# vast majority of users who never installed the pilot.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
LEGACY_REL = 'resources/language/English/strings.po'
MODERN_REL = 'resources/language/resource.language.en_gb/strings.po'

# --- second half: the empty-lists-in-Hebrew fix -----------------------------
# Field report: setting Umbrella's API language to Hebrew empties the lists.
# The cause is two Umbrella settings that are CONTENT FILTERS, not display
# language, and read the same api.language value:
#   useLanguageforOriginal (default TRUE!) -> TMDb discover gets
#       &with_original_language=he, i.e. "only films originally made in
#       Hebrew" -- next to nothing exists, so genre/year lists come back empty.
#   trakt.useLanguage (default false)      -> Trakt lists get &languages=he,
#       the same filter on the Trakt side.
# Nothing is wrong with api.language itself: TMDb still returns Hebrew titles
# and overviews where they exist (Umbrella already falls back to the English
# plot when a translation is missing). So the fix is to leave the language
# alone and switch OFF the two FILTERS -- exactly what the user meant to ask
# for. Settings-level, so we never touch Umbrella's code for this.
#
# Applied once per language value (the marker records which language it was
# resolved for): a user who deliberately turns a filter back on keeps it, and
# switching languages later re-evaluates.
FILTER_SETTINGS = ('useLanguageforOriginal', 'trakt.useLanguage')
FILTER_DONE_SETTING = '_umbrella_lang_filters_v1'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_language_patcher: ' + msg, level=level)
    except Exception:
        pass


def _addon_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
    except Exception:
        return ''
    return base if os.path.isdir(base) else ''


def _umbrella_addon():
    try:
        import xbmcaddon
        return xbmcaddon.Addon(UMBRELLA_ADDON_ID)
    except Exception:
        return None


def _resolved_is_english(addon):
    """True when Umbrella's api.language resolves to English -- i.e. the two
    content filters are harmless and must be left exactly as the user set
    them. Mirrors Umbrella's own resolution: an all-caps value (its 'AUTO')
    means 'follow Kodi's interface language'."""
    try:
        name = (addon.getSetting('api.language') or '').strip()
    except Exception:
        return True          # cannot read it -> assume English, change nothing
    if not name or name.upper() == 'AUTO' or name[-1:].isupper():
        try:
            import xbmc
            name = (xbmc.getLanguage(xbmc.ENGLISH_NAME) or '').split(' ')[0]
        except Exception:
            return True
    return name.strip().lower() in ('', 'english')


def ensure_content_filters_sane():
    """Turn OFF Umbrella's language CONTENT FILTERS while its API language is
    not English, so the lists stop coming back empty. Returns a short status.
    Never raises; does nothing at all when Umbrella is not installed."""
    addon = _umbrella_addon()
    if addon is None:
        return 'not_installed'
    if _resolved_is_english(addon):
        return 'english'
    try:
        lang = (addon.getSetting('api.language') or 'AUTO').strip()
    except Exception:
        return 'read_failed'
    try:
        from resources.lib import kodi_utils as _ku
        done_for = _ku.get_setting(FILTER_DONE_SETTING, '') or ''
    except Exception:
        done_for = ''
    if done_for == lang:
        # already handled for THIS language -- a filter the user has since
        # switched back on is their call, not ours to keep overriding
        return 'unchanged'
    wanted = []
    for key in FILTER_SETTINGS:
        try:
            if (addon.getSetting(key) or '').strip().lower() == 'true':
                wanted.append((key, 'false'))
        except Exception as e:
            _log('could not read {0}: {1}'.format(key, e), 'WARNING')
    turned_off = []
    if wanted:
        # Never a bare setSetting on somebody else's add-on: Kodi rewrites the
        # whole of Umbrella's settings.xml around every one of them. See
        # addon_settings_safe.py.
        try:
            from resources.lib import addon_settings_safe
            from resources.lib.umbrella_setup_patcher import (
                UMBRELLA_GUARD_PROPERTY)
            turned_off, _ = addon_settings_safe.apply(
                UMBRELLA_ADDON_ID, tuple(wanted),
                guard_property=UMBRELLA_GUARD_PROPERTY)
        except Exception as e:
            _log('could not clear content filters: {0}'.format(e), 'WARNING')
    try:
        from resources.lib import kodi_utils as _ku
        _ku.set_setting(FILTER_DONE_SETTING, lang)
    except Exception:
        pass
    if turned_off:
        _log('api.language is {0}; turned OFF the content filter(s) {1} so '
             'the lists are not restricted to Hebrew-only titles'.format(
                 lang, ', '.join(turned_off)))
        return 'patched'
    return 'unchanged'


def ensure_patched():
    """Mirror Umbrella's legacy English strings into the modern en_gb
    resource folder Kodi actually looks for. Idempotent, additive-only,
    never raises. Returns a short status string."""
    base = _addon_path()
    if not base:
        return 'not_installed'
    src = os.path.join(base, *LEGACY_REL.split('/'))
    dst = os.path.join(base, *MODERN_REL.split('/'))
    if not os.path.isfile(src):
        # upstream moved to the modern layout themselves, or a broken
        # install -- either way there is nothing safe to copy
        _log('legacy English strings.po not found -- skipping', 'WARNING')
        return 'no_source'
    try:
        with open(src, 'rb') as f:
            payload = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), 'WARNING')
        return 'read_failed'
    if not payload:
        return 'no_source'
    try:
        if os.path.isfile(dst):
            with open(dst, 'rb') as f:
                if f.read() == payload:
                    return 'unchanged'
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + '.aitmp'
        with open(tmp, 'wb') as f:
            f.write(payload)
        os.replace(tmp, dst)
        _log('installed modern en_gb strings for Umbrella '
             '({0} bytes) -- settings labels will render'.format(len(payload)))
        return 'patched'
    except OSError as e:
        try:
            os.remove(dst + '.aitmp')
        except OSError:
            pass
        _log('write failed: {0}'.format(e), 'WARNING')
        return 'write_failed'
