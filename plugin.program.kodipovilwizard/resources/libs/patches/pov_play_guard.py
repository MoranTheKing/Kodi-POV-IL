"""One episode at a time: taps that piled up while Kodi was busy.

Right after Kodi starts (a dozen add-on services loading), POV can take
several seconds to begin handling a tap on an episode. People tap again --
and once Kodi frees up, every queued tap opens its own source search and
playback, one after another (field video and logs, Oct 2026: four episodes
started back to back).

From POV's router.py, before POV is imported: a play request that arrives
while another one is still finding sources -- started less than a minute ago
and nothing playing yet -- is dropped. Anything while a video plays (POV's
own next-episode playback) and any request after the first one finished or
was cancelled goes through as before. The Wizard's profile service clears
the mark as soon as a video plays (POV's request stays alive for the whole
playback, and a tap right after stopping a bad source is a new choice).
"""
import time

PROPERTY = 'povil.play.started'
PLAY_MODES = ('play_media',)
WINDOW_S = 60.0
# The mark this interpreter set last. With POV's "fast navigation" the
# interpreter is reused and never exits between requests: a new request here
# means the previous one is over.
_LAST = [None]


def _mode(argv):
    query = (argv[2] if len(argv) > 2 else '').lstrip('?')
    for part in query.split('&'):
        name, _, value = part.partition('=')
        if name == 'mode':
            return value
    return ''


def duplicate(argv):
    """True when this request should be dropped (the caller exits)."""
    try:
        if _mode(argv) not in PLAY_MODES:
            return False
        import xbmc
        import xbmcgui
        win = xbmcgui.Window(10000)
        if _LAST[0] is not None:
            _finished(_LAST[0])
            _LAST[0] = None
        now = time.time()
        try:
            started = float(win.getProperty(PROPERTY) or 0)
        except ValueError:
            started = 0.0
        if 0 <= now - started < WINDOW_S and not xbmc.Player().isPlaying():
            xbmc.log('[POV IL] play request dropped: another episode is still starting', xbmc.LOGINFO)
            try:
                xbmcgui.Dialog().notification('POV IL', 'פרק אחר כבר מתחיל להתנגן...', time=2500, sound=False)
            except Exception:
                pass
            return True
        win.setProperty(PROPERTY, repr(now))
        _LAST[0] = now
        import atexit
        atexit.register(_finished, now)
        return False
    except Exception:
        return False


def _finished(started):
    """This request is over (playing, cancelled or failed): the next tap is a
    new choice, not a queued one."""
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        if win.getProperty(PROPERTY) == repr(started):
            win.clearProperty(PROPERTY)
    except Exception:
        pass
