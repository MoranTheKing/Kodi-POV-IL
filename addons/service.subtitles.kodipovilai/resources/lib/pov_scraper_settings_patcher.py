# One-time tune of plugin.video.pov's scraper settings so the build's shipped
# defaults match how a clean POV behaves.
#
# Background: the build ships a POV userdata settings.xml that turns ON a few
# options a clean POV keeps OFF. Two of them flood the source list with junk
# that a clean POV hides, which is exactly the "our build shows a pile of SD
# while clean POV looks filtered" report:
#   * include_prerelease_results = true  -> CAM/SCR/TELE (pre-release) sources
#   * include_3d_results         = true  -> 3D sources
# and one that REDUCES sources vs a clean install:
#   * provider.piratebay         = false -> a default-ON provider left off
#
# The source quality label itself is NOT the problem: POV derives 4K/1080p/720p
# from a regex on the release name (source_utils.get_release_quality) -- the
# exact same code on a clean POV and on ours, so a genuine 4K release is still
# labelled 4K here. The extra "SD" rows are extra (lower-quality/unlabelled)
# sources these settings surface. Turning the two junk options off and piratebay
# back on brings the list in line with a clean POV.
#
# We deliberately DO NOT touch filter.foreign.single.audio (the build keeps it
# off on purpose so Hebrew / foreign-audio releases are not dropped).
#
# Applied ONCE, gated by a marker in our own settings, and only where the value
# still differs -- so a user who later changes any of these keeps their choice.
# If POV is not installed yet we skip WITHOUT marking done, so it retries.

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
TUNE_VERSION = 'v1'

# id -> desired value ('true'/'false' as POV stores bools).
DESIRED = (
    ('include_prerelease_results', 'false'),
    ('include_3d_results', 'false'),
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
