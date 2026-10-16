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

# POV 6.10.06 stopped holding one Addon() from import time and now builds it
# inside every settings read (make_settings_dict, get_setting, ...). When Kodi
# updates POV while its service runs, the add-on is unregistered for under a
# second and that read raised "Unknown addon id" -- measured on a device: the
# 6.10.05 -> 6.10.06 update killed the running service at Kodi start, which
# users saw as a POV error. Only POV's own id waits; asking for another add-on
# that is simply not installed must still fail at once.
_OWN_IDS = ('', 'plugin.video.pov')


def patient_addon(real):
    """Wrap xbmcaddon.Addon so POV's own lookups wait out that window."""
    if getattr(real, '_povil_patient', False):
        return real

    def _addon(*args, **kwargs):
        try:
            return real(*args, **kwargs)
        except RuntimeError:
            addon_id = kwargs.get('id', args[0] if args else '')
            if (addon_id or '') not in _OWN_IDS:
                raise
        _monitor = xbmc.Monitor()
        for _ in range(30):
            if _monitor.waitForAbort(0.1):
                break
            try:
                return real(*args, **kwargs)
            except RuntimeError:
                continue
        return real(*args, **kwargs)

    _addon._povil_patient = True
    return _addon
