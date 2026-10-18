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

When Kodi is busy (the first seconds after it starts, on a slow box several
seconds), nothing showed between the tap and POV's sources window, so people
tapped again. A notice says the episode is being looked up as soon as the
request arrives (0.4.61 waited 1.5 s first -- still a gap on a Shield, field
video Oct 2026), and it is closed the moment POV's own window is up.
"""
import time

PROPERTY = 'povil.play.started'
PLAY_MODES = ('play_media',)
WINDOW_S = 60.0
NOTICE_S = 8.0          # the notice's longest life; closed earlier by the watcher
NOTICE_STEP_S = 0.1
# POV's own progress (full screen or background bar) or its results list.
POV_WINDOWS = ('Window.IsVisible(progress_media.xml) | Window.IsVisible(sources_results.xml)'
               ' | Window.IsActive(extendedprogressdialog)')
# The mark this interpreter set last. With POV's "fast navigation" the
# interpreter is reused and never exits between requests: a new request here
# means the previous one is over.
_LAST = [None]
# Marks of requests whose POV route returned (router.py, after Router()()):
# atexit runs only after the notice timer, and never with fast navigation.
_OVER = set()


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
        _searching_notice(now)
        return False
    except Exception:
        return False


def _searching_notice(started):
    """Say the tap counted, now; take the notice down once POV shows its own
    window, plays, or the request is over."""
    try:
        import xbmc
        import xbmcgui
        if xbmc.Player().isPlaying():
            return          # POV's next episode during playback: no notice
        xbmcgui.Dialog().notification('POV IL', 'מחפש מקורות...',
                                      time=int(NOTICE_S * 1000), sound=False)
        import threading
        threading.Thread(target=_watch_notice, args=(started,)).start()
    except Exception:
        pass


def _notice_done(started):
    import xbmc
    import xbmcgui
    if started in _OVER or xbmcgui.Window(10000).getProperty(PROPERTY) != repr(started):
        return True
    return xbmc.Player().isPlaying() or xbmc.getCondVisibility(POV_WINDOWS)


def _watch_notice(started):
    try:
        import xbmc
        monitor = xbmc.Monitor()
        waited = 0.0
        while waited < NOTICE_S:
            if _notice_done(started):
                if xbmc.getCondVisibility('Window.IsVisible(notification)'):
                    xbmc.executebuiltin('Dialog.Close(notification,true)')
                return
            if monitor.waitForAbort(NOTICE_STEP_S):
                return
            waited += NOTICE_STEP_S
    except Exception:
        pass


def request_over():
    """POV's route returned (no results, cancelled, or playback over)."""
    if _LAST[0] is not None:
        _OVER.add(_LAST[0])


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
