# File: plugin.program.kodipovilwizard/resources/lib/patches/kodi_widget_refresh.py

import xbmc

def ping():
    """
    Fires the standard 'foo' library update ping. 
    Third-party skins and TMDbHelper listen for this specific dummy library scan 
    to know when to flush and reload their home screen widgets.
    """
    try:
        xbmc.executebuiltin('UpdateLibrary(video,special://skin/foo)')
        xbmc.log("POV WIZARD PATCH: Fired background skin widget refresh ping.", xbmc.LOGDEBUG)
    except Exception as e:
        xbmc.log(f"POV WIZARD PATCH ERROR (widget_refresh_ping): {e}", xbmc.LOGERROR)