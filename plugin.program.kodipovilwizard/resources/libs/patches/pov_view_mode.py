"""Restore a saved directory view without repeatedly blocking navigation."""
import sys
import time
from urllib.parse import parse_qsl, urlsplit

import xbmc
import xbmcgui
import xbmcvfs


def _folder_key(url):
    parts = urlsplit(url)
    return (parts.scheme, parts.netloc, parts.path,
            tuple(sorted(parse_qsl(parts.query, keep_blank_values=True))))


def force_view(view_id, content):
    if not view_id:
        return False
    try:
        view = str(int(view_id))
        if int(view) <= 0:
            return False
        monitor = xbmc.Monitor()
        skin = xbmc.getSkinDir()
        profile = xbmcvfs.translatePath('special://profile/')
        # The content type alone cannot distinguish outgoing/incoming pages.
        expected = None
        if sys.argv and sys.argv[0].startswith('plugin://'):
            query = sys.argv[2] if len(sys.argv) > 2 else ''
            expected = _folder_key(sys.argv[0] + query)
        deadline = time.monotonic() + 1.5
        applied = 0
        while time.monotonic() < deadline:
            if (monitor.abortRequested() or xbmcgui.getCurrentWindowId() != 10025 or
                    xbmc.getSkinDir() != skin or
                    xbmcvfs.translatePath('special://profile/') != profile):
                return False
            folder = _folder_key(xbmc.getInfoLabel('Container.FolderPath'))
            if expected is not None and folder != expected:
                if applied:
                    return False  # Back/another directory wins immediately.
            elif (xbmc.getInfoLabel('Container.Content') == content and
                    not xbmc.getCondVisibility('Container.IsUpdating')):
                if xbmc.getCondVisibility('Control.IsVisible(%s)' % view):
                    return True
                if applied >= 2:
                    return False  # This skin does not expose the saved view.
                xbmc.executebuiltin('Container.SetViewMode(%s)' % view)
                applied += 1
            if monitor.waitForAbort(0.05):
                return False
        return False
    except Exception as exc:
        xbmc.log('POV WIZARD PATCH ERROR (force_view): ' + type(exc).__name__, xbmc.LOGWARNING)
        return False
