# -*- coding: utf-8 -*-
"""The home's trailers inside the skin (Onyx 1.0.32), for a viewer who has Onyx without the Kodi POV IL Wizard: the skin
asks for a title's trailer (NotifyAll(povil.trailer,...)) and the Wizard's trailer desk plays it -- without the Wizard no
trailer played (the owner, Nov 2026: "whoever downloads only the Onyx skin -- the trailers won't work for him?").
povil_menu/resources/libs/ holds the Wizard's own trailers.py, trailer_subs.py, youtube_port.py and
patches/pov_trailer_pick.py, copied by tools/skin_onyx/gen_standalone.py: one source, never edited here.

The home starts it (Home.xml onload) only while the Wizard is not installed. It runs once (Window(home).Property(
povil.tr.desk)), keeps its files in the skin's own folder, and gives way once the Wizard is installed (its own desk then
plays them) or another skin is chosen.
"""
import sys
import threading

import xbmc
import xbmcgui
import xbmcvfs

WIZARD = 'System.HasAddon(plugin.program.kodipovilwizard)'
DESK = 'povil.tr.desk'
DATA = 'special://profile/addon_data/skin.povil.onyx/'


def log(text):
    xbmc.log('[POV IL trailers] %s' % text, xbmc.LOGINFO)


def stay():
    return not xbmc.getCondVisibility(WIZARD) and xbmc.getSkinDir() == 'skin.povil.onyx'


def port():
    # the YouTube add-on's own server on a port this device lets it open (the Wizard's youtube_port.py, 15 s after the
    # start, as the Wizard runs it)
    try:
        if xbmc.Monitor().waitForAbort(15) or not stay():
            return
        from resources.libs import youtube_port
        youtube_port.run(lambda text: xbmc.log('[POV IL YouTube] ' + text, xbmc.LOGINFO))
    except Exception as exc:
        log('port check: %r' % (exc,))


def main():
    home = xbmcgui.Window(10000)
    if not stay() or home.getProperty(DESK):
        return
    home.setProperty(DESK, 'skin')
    try:
        sys.path.insert(0, xbmcvfs.translatePath('special://skin/scripts/povil_menu'))
        xbmcvfs.mkdirs(DATA)
        log('the skin plays the trailers (no Wizard)')
        threading.Thread(target=port, name='POVILYouTubePort').start()
        from resources.libs import trailers
        trailers.watch(data=DATA, stay=stay)
    finally:
        home.clearProperty(DESK)


main()
