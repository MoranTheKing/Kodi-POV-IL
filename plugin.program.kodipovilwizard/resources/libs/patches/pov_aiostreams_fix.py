# WIZARD_POV_AIOSTREAMS_FIX_v2
import xbmcaddon
import xbmcgui

def enforce_credentials(current_settings):
    """
    Validates if AIOStreams took over the scraper list but lacks credentials.
    Returns safe fallback settings if misconfigured.
    """
    if current_settings != ['provider.aiostreams']:
        return current_settings

    try:
        addon = xbmcaddon.Addon('plugin.video.pov')
        user = (addon.getSetting('aio.username') or '').strip()
        passwd = (addon.getSetting('aio.password') or '').strip()

        if not user or not passwd:
            # Credentials missing: Disarm the setting in the database
            addon.setSetting('provider.aiostreams', 'false')

            # Flush POV's internal settings cache property to force a live refresh
            try:
                xbmcgui.Window(10000).clearProperty('pov_settings')
            except Exception:
                pass

            # Shadow the upstream variable by returning the safe fallback list
            return ['provider.external', 'provider.easynews']

    except Exception:
        pass

    return current_settings