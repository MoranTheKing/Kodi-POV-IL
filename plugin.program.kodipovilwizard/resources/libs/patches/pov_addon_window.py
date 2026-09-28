import xbmc
from xbmcaddon import Addon

def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[POV Addon Window] {msg}", level)

def wait_for_window():
    try:
        Addon()
    except Exception:
        _ai_subs_monitor = xbmc.Monitor()
        for _ in range(30):
            if _ai_subs_monitor.waitForAbort(0.1):
                break
            try:
                Addon()
                break
            except Exception:
                continue

def safe_addon(addon_id='plugin.video.pov'):
    try:
        return Addon(id=addon_id)
    except Exception:
        pass

    _monitor = xbmc.Monitor()
    for _ in range(30):
        if _monitor.waitForAbort(0.1):
            break
        try:
            return Addon(id=addon_id)
        except Exception:
            continue

    # Out of patience, or Kodi is shutting down. Raise normally.
    return Addon(id=addon_id)