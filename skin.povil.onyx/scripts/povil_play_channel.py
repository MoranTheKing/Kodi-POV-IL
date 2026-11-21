# -*- coding: utf-8 -*-
"""A channel picked in the player's channels panel (Onyx 1.0.35) while a film or an episode plays: the film is stopped
first, its add-on sees the stop (POV looks once a second), and the channel plays after. Written by
tools/skin_onyx/gen_osd.py -- never edited here.

    RunScript(special://skin/scripts/povil_play_channel.py,<the channel's address>)
"""
import sys
import time

import xbmc
import xbmcgui

STOPPED_S, AFTER_S, POV_S = 15, 2.0, 8
# POV clears it once its playback monitor has seen the stop and kept the film's point (player.py, its last line)
POV_PLAYING = 'script.trakt.ids'
ACTION = 'povil.pov.action'


def main(address):
    if not address:
        return
    monitor, player, home = xbmc.Monitor(), xbmc.Player(), xbmcgui.Window(10000)
    if player.isPlaying():
        # (the screen under the film -- the home, a list -- starts no trailer meanwhile: the trailer desk rests this long
        # after an action of POV's, trailers.py ACTION_REST_S -- the reviewer)
        home.setProperty(ACTION, str(time.time()))
        xbmc.executebuiltin('PlayerControl(Stop)')
        began = time.time()
        while player.isPlaying() and time.time() - began < STOPPED_S:
            if monitor.waitForAbort(0.2):
                return
        if player.isPlaying() or monitor.waitForAbort(AFTER_S):
            return
        began = time.time()
        while home.getProperty(POV_PLAYING) and time.time() - began < POV_S:
            if monitor.waitForAbort(0.2):
                return
    xbmc.executebuiltin('PlayMedia("%s")' % address.replace('\\', '\\\\').replace('"', '\\"'))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '')
