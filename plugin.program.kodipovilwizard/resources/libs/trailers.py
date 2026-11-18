"""A title's trailer behind the home's hero (Onyx), the way a streaming service's own screen plays one.

The owner (Nov 2026), with a video of another app: "the trailer playing on the title itself". What
that takes in Kodi, measured in the QA Kodi:
  * POV gives every title its trailer as the YouTube add-on's address. Handing that address to
    Kodi's player (PlayMedia) puts Kodi's busy dialog over the home for as long as the add-on
    takes to answer -- 1.5 s on a fast PC, and it takes the remote's keys meanwhile -- and the
    first time ever the add-on asks its "Setup Wizard" question. Neither can happen by itself
    on a screen someone is only browsing.
  * The YouTube add-on's own code, asked from a thread of the Wizard's service, answers with the
    stream itself and shows nothing; the stream is then played as a plain address in Kodi's
    preview mode (windowed), which the skin draws behind the hero.

HOW THE SKIN ASKS (as for the ratings, ratings.py): once the screen has rested a few seconds on a
title the skin writes its trailer address to Window(home).Property(povil.tr.ask) and announces it
(NotifyAll(povil.trailer,ask)); when the title changes, a dialog opens or the home is left, it
empties the property and announces "stop". This module writes Window(home).Property(povil.tr.on):
the ask whose trailer it started -- the skin shows the picture only while the two agree.

WHAT IT NEVER DOES: start a trailer while anything else is playing, or stop anything it did not
start. The subtitles add-on leaves alone a playback whose address is the one in povil.tr.file.

ON FOR EVERYONE unless the viewer switches it off (the skin's setting POVILNoTrailers, a tile among
the home's shortcuts) -- the owner, Nov 2026: "on by default for everyone ... every device must be
able to run it ... it has to work in every situation". What that took, each seen in the QA Kodi:

  * THE YOUTUBE ADD-ON'S OWN SERVER. Every stream it names is read through a small server inside
    Kodi that belongs to it, and it SHUTS THAT SERVER DOWN once Kodi has been left alone for half
    a minute -- which is what a viewer resting on the home does. Its own player wakes the server
    before it plays (yt_play.py: ipc_exec(SERVER_WAKEUP)); its door for other add-ons
    (youtube_resolver) does not. A trailer handed to Kodi while that server is down does not
    play, and worse: Kodi's player waits twenty seconds for every one of the stream's parts, and
    Kodi's whole screen waits with it the moment the player is told to stop (twice in one hour,
    several minutes each). So: the server is woken first (light_streams), and before Kodi's
    player hears of the trailer this module reads the stream's first bytes itself, with a short
    wait (answers). A stream that does not answer is never handed to Kodi.
  * THE STOP IS NEVER PYTHON'S OWN Player.stop(). That call waits, holding Python, until Kodi has
    stopped; Kodi, stopping, asks the YouTube add-on's server about the stream (the player's
    open parts, the file's date for Kodi's own records) -- and that server is Python too, so
    it cannot answer until the call returns. Measured: every stop of a trailer froze Kodi's
    screen for 40 s (two waits of 20), and a stop during the opening for minutes. Sent as
    Kodi's built-in (PlayerControl(Stop), which returns at once) the same stop took 0.02 s and
    nothing froze. Desk is handed that built-in as `halt`.
  * A PLAYER THAT IS STILL OPENING IS NOT TOLD TO STOP EITHER: Kodi's screen waits for the player,
    and the player for every part of the stream it has begun to open. The stop is remembered
    and carried out at the trailer's first picture (Desk.stop, Desk.playback_started); the
    picture is not shown meanwhile, and the next title's trailer waits for it.
  * EVERY DEVICE: left to itself the YouTube add-on names the best stream its own settings allow
    -- of ten trailers three came as 1080p AV1 and one as 4K VP9, which a small box decodes in
    software. The trailer asks for H.264 up to 720p instead (light_streams): every box decodes
    that in its chip. Nothing of the YouTube add-on's own settings is touched; the choice lives
    in this interpreter only.
  * A TRAILER THAT STOPS COMING: Desk.guard watches the clock of the trailer it started; one that
    stands still is stopped, the still comes back, and that title is not asked again for a
    while. Nothing is ever said on the screen -- also not by Kodi: for a play that does not open
    Kodi puts its own "playback failed" box on the screen (seen with an address that answers
    nothing), and when the play was this module's trailer the box is closed (close_failure_box).
  * A FILM STARTED OVER A TRAILER: POV's and Umbrella's players watch their own playback from the
    moment they start it, and the trailer's "stopped" arriving in between made them lose the film
    (no resume point, no watched mark). patches/home_trailer_gone.py stops the trailer and waits
    for it to be gone right before they start (the play guard they already call).
  * Kodi asked every row of the home again whenever a playback started or stopped: the skin's rows
    now carry an order Kodi does not re-ask for (gen_home.py, follows_no_playback).
"""
import re
import threading

SENDER = 'povil.trailer'
ASK, ON = 'povil.tr.ask', 'povil.tr.on'
FILE = 'povil.tr.file'          # the address of the trailer the player was handed: another add-on tells a trailer from a film by it
OPENING = 'povil.tr.opening'    # set from the moment the player is told to play until the first picture (or the viewer moving on)
OFF_SWITCH = 'POVILNoTrailers'  # the skin's setting: set = the viewer switched the trailers off
YOUTUBE = 'plugin.video.youtube'
QUIET_START_S = 60              # none while Kodi is still starting (its services, the home's rows)
MAX_HEIGHT = 720                # what the trailer asks of YouTube: H.264 up to this, which every box decodes in its chip
HEAVY = ('vp9', 'av01', 'hdr', 'hfr', '3d', 'vr')
WAKE_S = 5                      # how long the YouTube add-on's server may take to wake (its own player waits as long)
ANSWER_S = 4.0                  # how long each of the stream's first bytes may take to arrive, read here before Kodi's player hears of it
OPEN_S = 20                     # no picture this long after the player was told to play: given up
OPEN_LIMIT_S = 120              # ... and after this long the opening is taken to be over whatever Kodi said
STALL_S = 8                     # the clock of a playing trailer standing still this long: given up
GIVEN_UP_S = 30 * 60            # a title whose trailer was given up is not asked again for this long
FAILURE_BOX_S = 4.0             # how long Kodi's "playback failed" box is looked for after a trailer failed to open
# Kodi's own box for a play that did not open: its heading is Kodi's string 16026 ("Playback failed");
# any other OK box that happens to be up is not this module's to close
FAILURE_BOX = 'Window.IsActive(okdialog) + String.IsEqual(Control.GetLabel(1),$LOCALIZE[16026])'
_VIDEO_ID = re.compile(r'[?&]video_id=([\w-]{11})(?:&|$)')
_SET = re.compile(r'<AdaptationSet\b(.*?)</AdaptationSet>', re.S)
_KIND = re.compile(r'(?:mimeType|contentType)="(video|audio)')
_BASE = re.compile(r'<BaseURL>(.*?)</BaseURL>', re.S)


class Asleep(Exception):
    """The YouTube add-on's server did not wake: no trailer this time (nothing is wrong with the code)."""


def video_id(address):
    """The YouTube id in the trailer address POV gives a title, or None for anything else."""
    address = address or ''
    if not address.startswith('plugin://%s/' % YOUTUBE):
        return None
    found = _VIDEO_ID.search(address)
    return found.group(1) if found else None


def pick(streams):
    """The stream to play of what the resolver answered: the first that has an address and is not live."""
    for stream in streams or []:
        if isinstance(stream, dict) and stream.get('url') and not stream.get('live'):
            return stream
    return None


def light_streams(video, provider_class, context_class, wake):
    """What the YouTube add-on answers for a trailer when asked for H.264 up to MAX_HEIGHT.

    First its server is woken, as its own player does before it plays (raises Asleep if it is
    not). Then its settings object is asked two things on the way to a stream: which heights and
    which kinds of stream. Both are answered here, on the object of THIS interpreter -- nothing
    is written.
    """
    provider, context = provider_class(), context_class()
    if not context.ipc_exec(wake, timeout=WAKE_S):
        raise Asleep()
    settings = context.get_settings()
    heights = [quality for quality in settings.mpd_video_qualities() if quality['nom_height'] <= MAX_HEIGHT]
    if not heights:
        raise ValueError('no adaptive streams in the YouTube add-on')
    kinds = frozenset(kind for kind in settings.stream_features() if kind not in HEAVY) | frozenset(('avc1', 'mp4a'))
    settings.mpd_video_qualities = lambda value=None: heights
    settings.stream_features = lambda value=None, raw_values=False: sorted(kinds) if raw_values else kinds
    streams, _ = provider.get_client(context=context).load_stream_info(video_id=video)
    return sorted(streams or [], key=lambda stream: stream.get('sort', (0, 0)))


def first_addresses(manifest):
    """The address of the first picture stream and of the first sound stream in a DASH manifest."""
    from html import unescape
    found = {}
    for block in _SET.findall(manifest or ''):
        kind, base = _KIND.search(block), _BASE.search(block)
        if kind and base and kind.group(1) not in found:
            found[kind.group(1)] = unescape(base.group(1).strip())
    return [found[kind] for kind in ('video', 'audio') if kind in found]


def answers(stream, fetch, log=lambda text: None):
    """Does the stream answer -- read HERE, with a short wait, before Kodi's player hears of it?

    fetch(address, headers, seconds, byte range or None) returns what was read. For a DASH
    manifest: the manifest itself, then the first bytes of its first picture stream and of its
    first sound stream. Anything that fails or stays silent is a no.
    """
    url, headers = stream.get('url') or '', stream.get('headers') or {}
    if isinstance(headers, str):
        headers = {}
    try:
        if str(stream.get('container') or '').lower() != 'mpd':
            return bool(fetch(url, headers, ANSWER_S, 'bytes=0-1023'))
        manifest = fetch(url, headers, ANSWER_S, None)
        if not manifest:
            return False
        for address in first_addresses(manifest.decode('utf-8', 'replace')):
            if not fetch(address, headers, ANSWER_S, 'bytes=0-1023'):
                return False
        return True
    except Exception as exc:
        log('no answer: %s' % type(exc).__name__)
        return False


def close_failure_box(visible, run, wait, seconds=FAILURE_BOX_S, step=0.1):
    """A trailer failed to open: Kodi's "playback failed" box, if it comes up, is closed.

    visible(condition) and run(built-in) are Kodi's; wait(seconds) returns True when Kodi is
    closing. Returns True when a box was closed.
    """
    waited = 0.0
    while waited < seconds:
        if visible(FAILURE_BOX):
            run('Dialog.Close(okdialog,true)')
            return True
        if wait(step):
            return False
        waited += step
    return False


def headers_text(headers):
    """The request headers of a stream as Kodi's player properties want them (name=value&name=value)."""
    if not headers:
        return ''
    if isinstance(headers, str):
        return headers
    from urllib.parse import quote
    return '&'.join('%s=%s' % (name, quote(str(value))) for name, value in sorted(headers.items()))


class Desk(object):
    """Starts and stops the home's trailer. Kodi's pieces are handed in, so it runs without Kodi."""

    def __init__(self, home, player, resolve, make_item, enabled, log=lambda text: None, clock=None,
                 ready=lambda stream: True, halt=None):
        import time
        self.home, self.player, self.resolve, self.make_item = home, player, resolve, make_item
        self.enabled, self.log, self.ready = enabled, log, ready
        # how the player is told to stop: in Kodi a built-in that returns at once, never the player's own stop
        # (see the module's text); without Kodi, the test's own player
        self.halt = halt or player.stop
        self.clock = clock or time.time
        self.born = self.clock()
        self.waiting = threading.Event()        # set when Kodi closes: a waiting trailer gives up at once
        self.ours = None            # the address of the trailer this desk handed to the player, until it is over
        self.key = None             # ... and the ask it was started for
        self.opening = None         # when the player was told to play, until its first picture (or its failing)
        self.stop_wanted = False    # the viewer moved on while it was opening: stopped at its first picture
        self.given_up = {}          # the ask of a trailer that did not play -> when it was given up
        self.let_go = None          # the address of a trailer this desk forgot before it was seen to end
        self.ticket = 0
        self.lock = threading.Lock()

    def is_ours(self):
        try:
            return bool(self.ours) and self.player.isPlaying() and self.player.getPlayingFile() == self.ours
        except Exception:
            return False

    def _opening(self):
        """Is the player still opening this desk's trailer? (An opening Kodi never said a word about ends by itself.)"""
        if self.opening is not None and self.clock() - self.opening >= OPEN_LIMIT_S:
            self.opening = None
            if not self.is_ours():
                self._forget()
        return self.opening is not None

    def _forget(self):
        # (remembered: should it show a picture after all -- a word of Kodi's about another playback was
        # taken for its failing, or it opened later than anyone waits -- it is stopped then, not left to
        # play unseen with its sound on)
        self.let_go = self.ours or self.let_go
        self.ours = self.key = self.opening = None
        self.stop_wanted = False
        self.home.clearProperty(ON)
        self.home.clearProperty(FILE)
        self.home.clearProperty(OPENING)

    def _busy_with_another(self):
        try:
            return self.player.isPlaying() and not self.is_ours()
        except Exception:
            return True

    def asked(self):
        """The skin asked for the trailer in povil.tr.ask. Returns the job to run off this thread, or None."""
        key = self.home.getProperty(ASK)
        video = video_id(key)
        if not video or not self.enabled() or self._busy_with_another():
            return None
        if self.clock() - self.given_up.get(key, -GIVEN_UP_S) < GIVEN_UP_S:
            return None             # it did not play a moment ago: the still stays
        with self.lock:
            if self.ours and self.key == key and (self.is_ours() or self._opening()):
                # it plays, or is opening: the viewer came back to it before it was stopped
                self.stop_wanted = False
                self.home.setProperty(ON, key)
                return None
        with self.lock:
            self.ticket += 1
            ticket = self.ticket
        # Kodi has just started: the trailer waits until the start is over, and plays then only if
        # this is still the title on screen
        wait = max(0.0, QUIET_START_S - (self.clock() - self.born))
        return lambda: self._start(key, video, ticket, wait)

    def _wanted(self, key, ticket):
        return ticket == self.ticket and self.home.getProperty(ASK) == key

    def _start(self, key, video, ticket, wait=0.0):
        if wait:
            self.waiting.wait(wait)
            if not self._wanted(key, ticket):
                return False
        # the trailer before this one is still opening: a player that is opening is left alone
        while self._opening():
            if self.waiting.wait(0.2) or not self._wanted(key, ticket):
                return False
        try:
            stream = pick(self.resolve(video))
        except Asleep:
            return False
        except Exception as exc:
            self.log('%s: %s' % (type(exc).__name__, str(exc)[:160]))
            return False
        if stream is None or not self._wanted(key, ticket):
            return False
        if not self.ready(stream):
            # it does not answer: never handed to Kodi's player, and this title rests for a while
            self.given_up[key] = self.clock()
            self.log('given up (no answer): %s' % video)
            return False
        with self.lock:
            # the answer took a moment: only if this is still the title on screen, and nothing else began
            if not self._wanted(key, ticket) or self._busy_with_another() or self._opening():
                return False
            url = stream['url']
            self.ours, self.key, self.opening, self.stop_wanted = url, key, self.clock(), False
            # (set before the player starts: the subtitles add-on reads it when the playback begins)
            self.home.setProperty(ON, key)
            self.home.setProperty(FILE, url)
            # (Kodi shows its busy dialog while a playback opens: the skin keeps its spinner off meanwhile)
            self.home.setProperty(OPENING, '1')
            self.player.play(url, self.make_item(url, stream), True)
        return True

    def guard(self, tick=1.0):
        """Watches the trailer this desk has just started, on the thread that started it. One that
        shows no picture within OPEN_S is given up without a word to the player (see stop); one
        whose clock stands still for STALL_S while it plays is stopped. Either way its title is
        not asked again for a while. Returns True when it gave the trailer up."""
        with self.lock:
            url, key, ticket = self.ours, self.key, self.ticket
        if not url:
            return False
        last, moved, seen = None, self.clock(), False
        while not self.waiting.wait(tick):
            with self.lock:
                if ticket != self.ticket or self.ours != url:
                    return False    # stopped, ended, or something else has the player
            try:
                now = self.player.getTime() if self.is_ours() else None
            except Exception:
                now = None
            if now is not None and now > 0 and now != last:
                last, moved, seen = now, self.clock(), True
            elif self.clock() - moved >= (STALL_S if seen else OPEN_S):
                with self.lock:
                    if ticket != self.ticket or self.ours != url:
                        return False
                    self.given_up[key] = self.clock()
                    self.home.clearProperty(ON)
                    self.home.clearProperty(OPENING)
                    if self.opening is not None:
                        self.stop_wanted = True     # still opening: stopped if it ever shows a picture
                    else:
                        ours = self.is_ours()
                        self._forget()
                        if ours:
                            self.halt()
                self.log('given up (%s): %s' % ('stood still' if seen else 'no picture', video_id(key)))
                return True
        return False

    def stop(self):
        """The skin moved on: stop the trailer -- only if it is this desk's that plays.

        A player that is still OPENING is never told to stop: Kodi's screen waits for the player,
        and the player for every part of the stream it has begun to open (seen: minutes). The
        picture is taken off the screen now; the player is stopped at its first picture.
        """
        with self.lock:
            self.ticket += 1        # an answer still on its way is no longer wanted
            self.home.clearProperty(ON)
            self.home.clearProperty(OPENING)
            if self.ours and self._opening():
                self.stop_wanted = True
                return False
            ours = self.is_ours()
            self._forget()
            if ours:
                self.halt()
        return ours

    def playback_over(self):
        """Kodi says a playback ended, stopped or failed. Returns True when it was this desk's
        trailer and it never showed a picture (Kodi then has a box to say so, which nobody wants)."""
        with self.lock:
            if self.ours and not self.is_ours():
                failed = self.opening is not None
                if failed:
                    self.given_up[self.key] = self.clock()
                self._forget()
                return failed
            if not self.ours:
                self.home.clearProperty(OPENING)
        return False

    def playback_started(self):
        """Something began to play: the trailer (then it is no longer opening, and is stopped now if
        the viewer moved on meanwhile), or something else (then the player is someone else's)."""
        with self.lock:
            self.home.clearProperty(OPENING)
            if not self.ours or not self.is_ours():
                try:
                    orphan = bool(self.let_go) and self.player.isPlaying() and self.player.getPlayingFile() == self.let_go
                except Exception:
                    orphan = False
                if self.ours:
                    self._forget()
                self.let_go = None
                if orphan:
                    self.halt()
                return
            self.opening = None
            if self.stop_wanted:
                self._forget()
                self.halt()


def watch():
    """The Wizard's start-up service runs this as one of its threads, for as long as Kodi runs."""
    import sys
    import xbmc
    import xbmcgui
    import xbmcvfs

    def log(text):
        xbmc.log('[POV IL trailers] %s' % text, xbmc.LOGINFO)

    def enabled():
        return (not xbmc.getCondVisibility('Skin.HasSetting(%s)' % OFF_SWITCH) and
                xbmc.getCondVisibility('System.AddonIsEnabled(%s)' % YOUTUBE))

    def resolve(video):
        folder = xbmcvfs.translatePath('special://home/addons/%s/resources/lib/' % YOUTUBE)
        if folder not in sys.path:
            sys.path.append(folder)
        from youtube_plugin.youtube.provider import Provider
        from youtube_plugin.kodion.context import XbmcContext
        from youtube_plugin.kodion.constants import SERVER_WAKEUP
        return light_streams(video, Provider, XbmcContext, SERVER_WAKEUP)

    def fetch(address, headers, seconds, span):
        # (a plain read of this module's own: no proxy for an address inside this device)
        import urllib.request
        request = urllib.request.Request(address, headers=dict(headers or {}))
        if span:
            request.add_header('Range', span)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=seconds) as answer:
            return answer.read(1024 if span else 2 * 1024 * 1024)

    def ready(stream):
        return answers(stream, fetch, log)

    def make_item(url, stream):
        item = xbmcgui.ListItem(path=url, offscreen=True)
        container = str(stream.get('container') or '').lower()
        if stream.get('adaptive') or container in ('mpd', 'hls'):
            item.setProperty('inputstream', 'inputstream.adaptive')
            item.setMimeType('application/dash+xml' if container != 'hls' else 'application/x-mpegURL')
            item.setContentLookup(False)
            headers = headers_text(stream.get('headers'))
            if headers:
                item.setProperty('inputstream.adaptive.manifest_headers', headers)
                item.setProperty('inputstream.adaptive.stream_headers', headers)
        return item

    home = xbmcgui.Window(10000)
    home.clearProperty(ON)
    home.clearProperty(FILE)
    home.clearProperty(OPENING)

    def over():
        if desk.playback_over():
            log('did not open')
            threading.Thread(target=close_failure_box, name='POVILTrailerBox',
                             args=(xbmc.getCondVisibility, xbmc.executebuiltin, listener.waitForAbort)).start()

    class Events(xbmc.Player):
        def onAVStarted(self):
            desk.playback_started()

        def onPlayBackStopped(self):
            over()

        def onPlayBackEnded(self):
            over()

        def onPlayBackError(self):
            over()

    player = Events()
    desk = Desk(home, player, resolve, make_item, enabled, log, ready=ready,
                halt=lambda: xbmc.executebuiltin('PlayerControl(Stop)'))

    def run(job):
        threading.Thread(target=lambda: job() and desk.guard(), name='POVILTrailer').start()

    class Listener(xbmc.Monitor):
        def onNotification(self, sender, method, data):
            # NotifyAll(povil.trailer,ask) arrives as sender 'povil.trailer', method 'Other.ask'
            what = method.rpartition('.')[2] if sender == SENDER else None
            try:
                if what == 'ask':
                    job = desk.asked()
                    if job is not None:
                        run(job)
                elif what == 'stop':
                    desk.stop()
            except Exception as exc:
                log('%s: %r' % (what, exc))

    listener = Listener()
    try:
        # the skin may have asked before this thread was listening (Kodi's start): the skin does not
        # ask twice for the same title
        job = desk.asked()
        if job is not None:
            run(job)
    except Exception as exc:
        log('first ask: %r' % exc)
    try:
        # callbacks are delivered while this thread waits here
        while not listener.waitForAbort(600):
            pass
    finally:
        desk.waiting.set()
        try:
            desk.stop()
        except Exception:
            pass
