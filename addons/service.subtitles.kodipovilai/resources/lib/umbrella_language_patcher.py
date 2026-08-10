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

# --- third half: the metadata language itself -------------------------------
# Umbrella ships api.language=English, and we had deliberately never touched
# it -- the filter fix above only fires once the language is ALREADY not
# English, i.e. after a user changed it by hand. On an Israeli build that is
# the wrong default: titles, overviews and artwork should come back in Hebrew.
#
# 'Hebrew' is one of Umbrella's own options (its settings.xml lists it), so
# this is a value their own picker writes, not an arrangement of ours.
#
# ORDER MATTERS, and getting it wrong is the exact bug we already fixed:
# api.language also drives two CONTENT FILTERS, and switching to Hebrew with
# those still on asks TMDb and Trakt for titles ORIGINALLY MADE in Hebrew --
# which empties every list. So this must run BEFORE
# ensure_content_filters_sane(), in the same startup. service.py calls them in
# that order and must keep doing so.
#
# Applied once, and only while the setting still reads exactly what Umbrella
# shipped: somebody who has already chosen a language has said what they want.
API_LANGUAGE_SETTING = 'api.language'
API_LANGUAGE_SHIPPED = 'English'
API_LANGUAGE_WANTED = 'Hebrew'
API_LANGUAGE_DONE_SETTING = '_umbrella_api_language_v1'


def ensure_api_language():
    """Put Umbrella's metadata language on Hebrew, once. Returns a short
    status string; never raises. MUST be called before
    ensure_content_filters_sane()."""
    addon = _umbrella_addon()
    if addon is None:
        return 'not_installed'
    try:
        from resources.lib import kodi_utils as _ku
        if (_ku.get_setting(API_LANGUAGE_DONE_SETTING, '') or '') == 'done':
            return 'unchanged'
    except Exception:
        pass
    try:
        current = (addon.getSetting(API_LANGUAGE_SETTING) or '').strip()
    except Exception:
        return 'read_failed'
    if current != API_LANGUAGE_SHIPPED:
        # Already moved -- theirs to decide. Mark it settled so we never
        # revisit it, not even if they happen to set it back to English.
        try:
            from resources.lib import kodi_utils as _ku
            _ku.set_setting(API_LANGUAGE_DONE_SETTING, 'done')
        except Exception:
            pass
        return 'user_chosen'
    try:
        from resources.lib import addon_settings_safe
        from resources.lib.umbrella_setup_patcher import (
            UMBRELLA_GUARD_PROPERTY)
        changed, _, failed = addon_settings_safe.apply(
            UMBRELLA_ADDON_ID, ((API_LANGUAGE_SETTING, API_LANGUAGE_WANTED),),
            guard_property=UMBRELLA_GUARD_PROPERTY)
    except Exception as e:
        _log('could not set api.language: {0}'.format(e), 'WARNING')
        return 'write_failed'
    if failed:
        # Leaving the marker off is the whole point: a half-applied language
        # with the filters about to be re-evaluated is the empty-lists bug.
        return 'write_failed'
    try:
        from resources.lib import kodi_utils as _ku
        _ku.set_setting(API_LANGUAGE_DONE_SETTING, 'done')
    except Exception:
        pass
    if changed:
        _log('Umbrella metadata language set to Hebrew')
        return 'patched'
    return 'unchanged'


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
    failed = []
    if wanted:
        # Never a bare setSetting on somebody else's add-on: Kodi rewrites the
        # whole of Umbrella's settings.xml around every one of them. See
        # addon_settings_safe.py.
        try:
            from resources.lib import addon_settings_safe
            from resources.lib.umbrella_setup_patcher import (
                UMBRELLA_GUARD_PROPERTY)
            turned_off, _, failed = addon_settings_safe.apply(
                UMBRELLA_ADDON_ID, tuple(wanted),
                guard_property=UMBRELLA_GUARD_PROPERTY)
        except Exception as e:
            failed = [k for k, _v in wanted]
            _log('could not clear content filters: {0}'.format(e), 'WARNING')
    if failed:
        # Marker withheld: the lists are still empty, so the next startup has
        # to try again rather than record the job as done.
        return 'write_failed'
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
    never raises. Returns a short status string.

    The mechanism turned out not to be Umbrella-specific -- Account Manager
    Lite is hit by exactly the same locale-folder fallback -- so the work
    itself lives in legacy_lang_mirror; this stays as Umbrella's entry point
    because the second half of this module (the content filters) is
    Umbrella's alone."""
    try:
        from resources.lib import legacy_lang_mirror
    except Exception:
        return 'not_installed'
    return legacy_lang_mirror.mirror(UMBRELLA_ADDON_ID, LEGACY_REL, MODERN_REL)
