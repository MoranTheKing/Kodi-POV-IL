# One-time tune of plugin.video.pov's scraper settings for the build.
#
# The build owner WANTS pre-release (CAM/SCR/TELE) and 3D results included by
# default, so this restores both to ON. It also turns the default-ON
# "piratebay" provider back on (the build's userdata left it off, which reduced
# source counts). v1 of this patcher briefly turned pre-release/3D off; v2
# restores them, and because the marker version changed it re-applies on any
# device that got v1.
#
# NOTE: this does NOT affect the "1080p-named source shown as SD" report. POV
# derives 4K/1080p/720p by regex on the release name
# (source_utils.get_release_quality) -- the same code on a clean POV and here --
# so these settings do not change how a source is labelled, only which sources
# appear. That display report is tracked separately.
#
# We deliberately DO NOT touch filter.foreign.single.audio (the build keeps it
# off on purpose so Hebrew / foreign-audio releases are not dropped).
#
# Applied once per marker version, only where the value still differs -- so a
# user who later changes any of these keeps their choice. If POV is not
# installed yet we skip WITHOUT marking done, so it retries.

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
TUNE_FLAG = '_pov_scraper_tune'
TUNE_VERSION = 'v2'

# id -> desired value ('true'/'false' as POV stores bools).
DESIRED = (
    ('include_prerelease_results', 'true'),
    ('include_3d_results', 'true'),
    ('provider.piratebay', 'true'),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_scraper_settings_patcher: ' + msg, level=level)
    except Exception:
        pass


def _already_done():
    if kodi_utils is None:
        return False
    try:
        return kodi_utils.get_setting(TUNE_FLAG, '') == TUNE_VERSION
    except Exception:
        return False


def _mark_done():
    if kodi_utils is None:
        return
    try:
        kodi_utils.set_setting(TUNE_FLAG, TUNE_VERSION)
    except Exception:
        pass


def _pov_addon():
    if xbmcaddon is None:
        return None
    try:
        return xbmcaddon.Addon(POV_ADDON_ID)
    except Exception:
        return None


def ensure_patched():
    """Returns 'already' | 'no_pov' | 'unchanged' | 'patched'."""
    if _already_done():
        return 'already'
    addon = _pov_addon()
    if addon is None:
        return 'no_pov'  # not installed yet -- retry next startup, do not mark

    changed = []
    for key, want in DESIRED:
        try:
            cur = addon.getSetting(key)
        except Exception:
            cur = None
        if cur is None:
            continue  # key absent in this POV schema -- leave it alone
        if (cur or '').strip().lower() == want:
            continue
        try:
            addon.setSetting(key, want)
            changed.append('{0}={1}'.format(key, want))
        except Exception as e:
            _log('failed to set {0}: {1}'.format(key, e), level='WARNING')

    _mark_done()
    if changed:
        _log('tuned ' + ', '.join(changed), level='INFO')
        return 'patched'
    return 'unchanged'
