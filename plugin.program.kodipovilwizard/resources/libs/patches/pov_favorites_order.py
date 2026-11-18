# -*- coding: utf-8 -*-
"""The order of POV's own favourites: newest first, or by name.

A viewer (Nov 2026): "the ascending / descending order does nothing -- I sort them by hand; it needs an
A-to-Z setting". Kodi's own sort switch has nothing to work with: POV hands its lists to Kodi with no
sort order, so the switch reverses nothing. POV reads its favourites from its own table in the order
they were added; the Wizard's hook in that query (pov_local_favorites_recent) already made it newest
first. The order is now the viewer's choice of the two, kept in one small file in POV's own folder:

    addon_data/plugin.video.pov/povil_favorites_order      'az' = by name; anything else, or no file = newest first

A file, not a setting: POV's query reads it without loading an add-on object, and the Wizard's saved
lists count it among the files a list depends on (pov_list_snapshot.HASHED_FILES), so a list saved in
one order is never shown in the other.

Names are compared as POV stored them when the title was saved (the name it had on screen); Latin
names come before Hebrew ones.
"""
import os

FILE = 'povil_favorites_order'
NEWEST, BY_NAME = 'new', 'az'
CLAUSES = {NEWEST: 'rowid DESC', BY_NAME: 'title COLLATE NOCASE ASC, rowid DESC'}
SAID = {NEWEST: 'החדשים קודם', BY_NAME: 'לפי א-ב'}


def _path():
    import xbmcvfs
    return os.path.join(xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/'), FILE)


def current(path=None):
    try:
        with open(path or _path(), 'r', encoding='utf-8') as source:
            return BY_NAME if source.read(8).strip() == BY_NAME else NEWEST
    except (OSError, ValueError):
        return NEWEST


def clause(path=None):
    """What follows ORDER BY in POV's favourites query."""
    return CLAUSES[current(path)]


def switch(path=None):
    """The other order, written; returns it."""
    path = path or _path()
    order = NEWEST if current(path) == BY_NAME else BY_NAME
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.new', 'w', encoding='utf-8') as target:
        target.write(order)
    os.replace(path + '.new', path)
    return order


def toggle():
    """The Wizard's route (mode=pov_favorites_order): switch, show it on the screen now, and say which."""
    import time
    import xbmc
    import xbmcgui
    order = switch()
    # the home's rows of saved titles carry this property in their address: a new value asks them again
    xbmcgui.Window(10000).setProperty('povil.lists.t', str(time.time()))
    if 'pov' in xbmc.getInfoLabel('Container.PluginName'):
        xbmc.executebuiltin('Container.Refresh')
    xbmcgui.Dialog().notification('המועדפים של POV', 'מסודרים עכשיו ' + SAID[order], xbmcgui.NOTIFICATION_INFO, 3000)
    return order
