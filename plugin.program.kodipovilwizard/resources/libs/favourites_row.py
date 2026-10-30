"""Kodi's favourites as a right-to-left home row (the Onyx skin).

Kodi lists favourites itself (favourites://) with the first one on the left;
the Onyx home starts every row on the right. This route lists the same
favourites -- read from special://profile/favourites.xml, the file Kodi keeps
them in -- last first, each marked povil_rtl=1, so the skin starts the row on
the first favourite, on the right.

Each favourite carries the Onyx soft wash of its picture (povil_rtl.blur_art).

A tap runs the favourite's own command (mode=favourite_run). The row may be
older than the file, so the favourite at that place must still carry the
same name; otherwise the first favourite of that name runs, and with none
left the home is refreshed.

default.py hands both modes here before the Wizard's router: a home row
should not pay for the Wizard's menus. Nothing is listed or run in a kids
profile.
"""
import xml.etree.ElementTree as ET
from urllib.parse import quote

import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs

BASE = 'plugin://plugin.program.kodipovilwizard/'
FILE = 'special://profile/favourites.xml'


def read():
    """[(name, thumb, command)] in Kodi's order; [] when there are none."""
    try:
        root = ET.parse(xbmcvfs.translatePath(FILE)).getroot()
    except (OSError, ET.ParseError):
        return []
    favourites = []
    for node in root.iter('favourite'):
        command = (node.text or '').strip()
        if command:
            favourites.append((node.get('name') or '', node.get('thumb') or '', command))
    return favourites


def _child():
    """A kids profile, or no way to tell: then nothing is listed or run."""
    try:
        from resources.libs.patches import profile_age_guard
        return profile_age_guard.active_policy() is not None
    except Exception:
        return True


def _blur(item):
    """The Onyx soft wash of the favourite's picture (povil_rtl.blur_art)."""
    try:
        from resources.libs.patches import povil_rtl
        povil_rtl.blur_art(item)
    except Exception:
        pass


def row(handle):
    items = []
    if not _child():
        favourites = read()
        for index in reversed(range(len(favourites))):
            name, thumb, _command = favourites[index]
            item = xbmcgui.ListItem(name, offscreen=True)
            if thumb:
                item.setArt({'thumb': thumb, 'icon': thumb})
                _blur(item)
            item.setProperty('povil_rtl', '1')
            item.setProperty('IsPlayable', 'false')
            url = '%s?mode=favourite_run&i=%d&n=%s' % (BASE, index, quote(name))
            items.append((url, item, False))
    if items:
        xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


def run(handle, params):
    if handle >= 0:
        # Kodi may start a non-playable item as media: nothing to play here
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem(offscreen=True))
    if _child():
        return
    favourites = read()
    name = params.get('n', '')
    try:
        index = int(params.get('i', ''))
    except ValueError:
        index = -1
    if not (0 <= index < len(favourites) and favourites[index][0] == name):
        index = next((i for i, fav in enumerate(favourites) if fav[0] == name), -1)
    if index < 0:
        xbmc.executebuiltin('Container.Refresh')
        return
    xbmc.executebuiltin(favourites[index][2])
