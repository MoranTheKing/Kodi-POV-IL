"""Reconcile POV's interpreter flag without unloading the active profile."""
import os
import re
import tempfile
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs


def check():
    from modules import kodi_utils
    try:
        fast = xbmcaddon.Addon('service.subtitles.kodipovilai').getSetting('pov_fast_navigation') == 'true'
        wanted = 'true' if fast else 'false'
        path = xbmcvfs.translatePath('special://home/addons/plugin.video.pov/addon.xml')
        with open(path, 'rb') as handle:
            original = handle.read()
        pattern = br'(<reuselanguageinvoker\s*>)(\s*)(true|false)(\s*)(</reuselanguageinvoker\s*>)'
        matches = list(re.finditer(pattern, original))
        if len(matches) != 1:
            return False
        # The setting must agree before the upstream checker sees it again.
        if kodi_utils.get_setting('reuse_language_invoker', '') != wanted:
            kodi_utils.set_setting('reuse_language_invoker', wanted)
        changed = re.sub(pattern, lambda m: m[1] + m[2] + wanted.encode('ascii') + m[4] + m[5], original)
        if changed == original:
            return True
        pending = None
        try:
            with tempfile.NamedTemporaryFile(dir=os.path.dirname(path), delete=False) as handle:
                pending = handle.name
                handle.write(changed)
            os.replace(pending, path)
            pending = None
        finally:
            if pending and os.path.isfile(pending):
                os.remove(pending)
        restart_notice()
        xbmc.log('[POV IL] Interpreter setting reconciled; active profile retained until next Kodi start', xbmc.LOGINFO)
        return True
    except Exception as error:
        xbmc.log('[POV IL] Interpreter reconciliation failed: ' + type(error).__name__, xbmc.LOGWARNING)
        return False


def restart_notice():
    window = xbmcgui.Window(10000)
    key = 'POVIL.InvokerRestartNotice'
    if not window.getProperty(key):
        window.setProperty(key, '1')
        xbmcgui.Dialog().notification('POV IL', 'הגדרת היציבות תחול בהפעלה הבאה של קודי.', time=5000)


def manual_toggle_applied(value):
    # Keep the explicit navigation preference consistent with a manual toggle.
    xbmcaddon.Addon('service.subtitles.kodipovilai').setSetting('pov_fast_navigation', value)
    restart_notice()
