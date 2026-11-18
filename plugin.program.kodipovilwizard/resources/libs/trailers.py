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
    wait (reachable). A stream that does not answer is never handed to Kodi. That server also
    refuses callers that are not on a home-network address -- its own address on a phone's mobile
    connection is not one (the owner's phone, Nov 2026: no trailer played at all): the manifest
    is then read, and played, through 127.0.0.1 (reachable). Three trailers in a row that do not
    play and the trailers rest ten minutes, so a device they do not work on is not asked of
    YouTube at every title.
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
  * A STOP THAT COMES WHILE THE TRAILER OPENS MAY NOT BE MEANT. On the owner's phone (his second
    log, Nov 2026) the same trailer opened five times in a row and was stopped each time within a
    tenth of a second of its first picture; the fifth stop froze the screen twenty seconds. The
    skin had said "stop" while the trailer was opening -- with Kodi's busy dialog over the home
    what the skin reads of the home is not what it reads a moment later -- the stop was carried
    out at the first picture, the skin asked again, and so on. Now such a stop is looked at
    again half a second after the first picture (Desk._late_stop, wanted_now): if the home is
    on the screen with no dialog and the title is still the one the trailer is of, the trailer
    plays on and the skin's question is put back. A trailer that IS stopped as it begins, twice
    for the same title, leaves that title alone for a while. The log says what the screen looked
    like when the stop came.
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
import os
import re
import threading

SENDER = 'povil.trailer'
ASK, ON = 'povil.tr.ask', 'povil.tr.on'
FILE = 'povil.tr.file'          # the address of the trailer the player was handed: another add-on tells a trailer from a film by it
OPENING = 'povil.tr.opening'    # set from the moment the player is told to play until the first picture (or the viewer moving on)
OFF_SWITCH = 'POVILNoTrailers'  # the skin's setting: set = the viewer switched the trailers off
HERO_LABEL = 9809               # the home's hidden label that holds the trailer address of the title in the hero (gen_home.py)
YOUTUBE = 'plugin.video.youtube'
# None in the first seconds of this thread. It was a minute -- and this thread is started only after the
# Wizard has seen the home's rows settle and has checked for updates, so a viewer waited well over a minute
# from Kodi's start for the first trailer and took the trailers for broken (the owner, Nov 2026: "it has to
# work right when one enters Kodi"). The start is over by the time this thread exists; a few seconds are
# left for what the Wizard still does right after it.
QUIET_START_S = 8
MAX_HEIGHT = 720                # what the trailer asks of YouTube: H.264 up to this, which every box decodes in its chip
HEAVY = ('vp9', 'av01', 'hdr', 'hfr', '3d', 'vr')
WAKE_S = 5                      # how long the YouTube add-on's server may take to wake (its own player waits as long)
ANSWER_S = 4.0                  # how long each of the stream's first bytes may take to arrive, read here before Kodi's player hears of it
OPEN_S = 20                     # no picture this long after the player was told to play: given up
OPEN_LIMIT_S = 120              # ... and after this long the opening is taken to be over whatever Kodi said
STALL_S = 8                     # the clock of a playing trailer standing still this long: given up
GIVEN_UP_S = 30 * 60            # a title whose trailer was given up is not asked again for this long
FAILURE_BOX_S = 4.0             # how long Kodi's "playback failed" box is looked for after a trailer failed to open
LOOPBACK = '127.0.0.1'
FAILS, REST_S = 3, 10 * 60      # this many trailers in a row that did not play: none is tried for this long
SETTLE_S = 0.5                  # a stop that came while the trailer opened is looked at again this long after the first picture
QUICK_S = 1.0                   # a trailer stopped sooner than this after its first picture was stopped "as it began"
#                                 (the loop on the phone stopped it within 0.13 s; a viewer browsing takes longer to move on)
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


def _host(url):
    from urllib.parse import urlsplit
    try:
        return urlsplit(url).hostname or ''
    except Exception:
        return ''


def address_kind(url):
    """What kind of address a stream is read at -- for the log, which never carries the address itself."""
    host = _host(url)
    parts = host.split('.')
    if host in ('localhost', '::1') or parts[0] == '127':
        return 'this device'
    try:
        first, second = int(parts[0]), int(parts[1])
    except Exception:
        return 'other'
    if first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168):
        return 'home network'
    return 'other'


def through_this_device(url):
    """The same address reached through the device's own loopback, or None when it already is (or cannot be)."""
    from urllib.parse import urlsplit, urlunsplit
    try:
        parts = urlsplit(url)
        if parts.scheme != 'http' or not parts.hostname or address_kind(url) == 'this device':
            return None
        netloc = LOOPBACK + (':%d' % parts.port if parts.port else '')
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return None


def _origin(url):
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    return '%s://%s' % (parts.scheme, parts.netloc)


def _why(exc):
    code = getattr(exc, 'code', None)
    return 'HTTP %s' % code if isinstance(code, int) else type(exc).__name__


def reachable(stream, fetch, save=None, log=lambda text: None):
    """The stream to hand to Kodi's player -- read HERE first, with a short wait -- or None.

    fetch(address, headers, seconds, byte range or None) returns what was read. For a DASH
    manifest: the manifest itself, then the first bytes of its first picture stream and of its
    first sound stream. Anything that fails or stays silent is a no, and the log says which step
    and how (never the address).

    THE YOUTUBE ADD-ON'S SERVER MAY REFUSE ITS OWN ADDRESS. It names its streams at the address of
    the device's network interface and answers only callers from a home-network address. On the
    owner's phone (Nov 2026) every trailer ended here with an HTTP error on the manifest: on a
    mobile or a VPN connection that address is not a home-network one. The server listens on
    every interface, so the same manifest is then read through 127.0.0.1, its stream addresses
    are turned the same way, and save(text, address) keeps it where that server serves manifests
    from and returns the address it now has there (Kodi's player does not open a manifest that
    is a file: seen in the QA Kodi, three ways). The stream comes back with that address.
    """
    url, headers = stream.get('url') or '', stream.get('headers') or {}
    if isinstance(headers, str):
        headers = {}
    try:
        if str(stream.get('container') or '').lower() != 'mpd':
            return stream if fetch(url, headers, ANSWER_S, 'bytes=0-1023') else None
    except Exception as exc:
        log('no answer: stream %s' % _why(exc))
        return None
    turned = None
    try:
        manifest = fetch(url, headers, ANSWER_S, None)
    except Exception as first:
        turned = through_this_device(url) if save is not None else None
        if turned is None:
            log('no answer: manifest %s at a "%s" address' % (_why(first), address_kind(url)))
            return None
        try:
            manifest = fetch(turned, headers, ANSWER_S, None)
        except Exception as second:
            log('no answer: manifest %s at a "%s" address, %s through this device' % (_why(first), address_kind(url), _why(second)))
            return None
        log('manifest %s at a "%s" address: read through this device instead' % (_why(first), address_kind(url)))
    if not manifest:
        log('no answer: empty manifest')
        return None
    text = manifest.decode('utf-8', 'replace')
    if turned:
        text = text.replace(_origin(url), _origin(turned))
    try:
        for address in first_addresses(text):
            if not fetch(address, headers, ANSWER_S, 'bytes=0-1023'):
                log('no answer: empty stream')
                return None
    except Exception as exc:
        log('no answer: stream %s' % _why(exc))
        return None
    if not turned:
        return stream
    try:
        kept = save(text, turned)
    except Exception as exc:
        log('no answer: manifest not kept (%s)' % type(exc).__name__)
        return None
    return dict(stream, url=kept) if kept else None


def kept_address(address, prefix='povil_'):
    """(file name, address) for a turned manifest kept beside the one the YouTube add-on wrote: the
    add-on's server serves the file named in the address's `file` field from its own folder."""
    from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode
    parts = urlsplit(address)
    query = parse_qs(parts.query)
    name = (query.get('file') or [''])[0]
    if not name or name != os.path.basename(name) or not name.endswith('.mpd'):
        return None, None
    query['file'] = [prefix + name]
    return prefix + name, urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ''))


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
                 ready=lambda stream: stream, halt=None, wanted_now=lambda key: False, look=lambda key: '', settle=0.0):
        import time
        self.home, self.player, self.resolve, self.make_item = home, player, resolve, make_item
        self.enabled, self.log, self.ready = enabled, log, ready
        # how the player is told to stop: in Kodi a built-in that returns at once, never the player's own stop
        # (see the module's text); without Kodi, the test's own player
        self.halt = halt or player.stop
        # wanted_now(key): is the home on the screen, with no dialog, on the title this trailer is of?
        # look(key): the same in words, for the log. settle: how long after the first picture a stop
        # that came during the opening is looked at again (0: at once, on the caller's thread).
        self.wanted_now, self.look, self.settle = wanted_now, look, settle
        self.shown = None           # when the trailer on the player showed its first picture
        self.quick = {}             # the ask of a trailer stopped as it began -> how many times in a row
        self.said = 0               # how many times the log was told of a stop during an opening
        self.clock = clock or time.time
        self.born = self.clock()
        self.waiting = threading.Event()        # set when Kodi closes: a waiting trailer gives up at once
        self.ours = None            # the address of the trailer this desk handed to the player, until it is over
        self.key = None             # ... and the ask it was started for
        self.opening = None         # when the player was told to play, until its first picture (or its failing)
        self.stop_wanted = False    # the viewer moved on while it was opening: stopped at its first picture
        self.given_up = {}          # the ask of a trailer that did not play -> when it was given up
        self.failed = 0             # trailers in a row that did not play
        self.resting = 0.0          # ... and until when none is tried because of it
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
        self.shown = None
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
        if self.clock() - self.given_up.get(key, -GIVEN_UP_S) < GIVEN_UP_S or self.clock() < self.resting:
            return None             # it did not play a moment ago (or none does on this device now): the still stays
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
            self._did_not_play('the YouTube add-on did not wake its server')
            return False
        except Exception as exc:
            self._did_not_play('%s: %s' % (type(exc).__name__, str(exc)[:160]))
            return False
        if stream is None or not self._wanted(key, ticket):
            return False
        stream = self.ready(stream)
        if not stream:
            # it does not answer: never handed to Kodi's player, and this title rests for a while
            self.given_up[key] = self.clock()
            self._did_not_play('given up (no answer): %s' % video)
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

    def _did_not_play(self, why):
        """One more trailer that did not play; FAILS of them in a row and the trailers rest."""
        self.failed += 1
        self.log(why)
        if self.failed >= FAILS:
            self.failed = 0
            self.resting = self.clock() + REST_S
            self.log('%d trailers in a row did not play: none is tried for %d minutes' % (FAILS, REST_S // 60))

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
                self._did_not_play('given up (%s): %s' % ('stood still' if seen else 'no picture', video_id(key)))
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
                if self.said < 5:
                    self.said += 1
                    self.log('stop while opening (%s)' % self.look(self.key))
                return False
            ours = self.is_ours()
            if ours:
                self._stopped_early(self.key)
            self._forget()
            if ours:
                self.halt()
        return ours

    def _stopped_early(self, key):
        """A trailer is being stopped: was it as it began? Twice in a row for one title and the title is
        left alone for a while -- whatever stops it would stop it again (seen: five times in ten seconds)."""
        if self.shown is not None and self.clock() - self.shown >= QUICK_S:
            self.quick.pop(key, None)
            return
        self.quick[key] = self.quick.get(key, 0) + 1
        if self.quick[key] >= 2:
            self.quick.pop(key, None)
            self.given_up[key] = self.clock()
            self._did_not_play('stopped as it began, twice: %s' % video_id(key))

    def _late_stop(self, url, key):
        """The trailer has shown its first picture and a stop came while it opened: look again."""
        if self.settle:
            self.waiting.wait(self.settle)
        try:
            wanted = bool(self.wanted_now(key))
        except Exception:
            wanted = False
        with self.lock:
            if self.ours != url or not self.stop_wanted:
                return
            self.stop_wanted = False
            if wanted and self.is_ours():
                # not meant: the title is still on the screen. The skin's question is put back, so it
                # neither asks again nor hides the picture
                self.home.setProperty(ASK, key)
                self.home.setProperty(ON, key)
                self.log('a stop that came while the trailer opened was not meant: it plays on')
                return
            ours = self.is_ours()
            if ours:
                self._stopped_early(key)
            self._forget()
            if ours:
                self.halt()

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
            if self.ours and self.is_ours():
                self.failed = 0     # a trailer shows its picture: they work on this device
                self.shown = self.clock()
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
            late = (self.ours, self.key) if self.stop_wanted else None
        if late:
            if self.settle:
                threading.Thread(target=self._late_stop, args=late, name='POVILTrailerLook').start()
            else:
                self._late_stop(*late)


def watch():
    """The Wizard's start-up service runs this as one of its threads, for as long as Kodi runs."""
    import sys
    import xbmc
    import xbmcgui
    import xbmcvfs

    def log(text):
        xbmc.log('[POV IL trailers] %s' % text, xbmc.LOGINFO)

    def enabled():
        # (none on a children's profile: its guard stops every playback it did not approve -- with the
        # blocking stop this module must never meet -- and a trailer is not rated for the child)
        return (not xbmc.getCondVisibility('Skin.HasSetting(%s)' % OFF_SWITCH) and
                home.getProperty('POVIL.ChildProfile') != 'true' and
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

    def save(text, address):
        # beside the manifest the YouTube add-on wrote, in the folder its server serves them from
        from youtube_plugin.kodion.constants import TEMP_PATH
        name, kept = kept_address(address)
        if not name:
            return None
        with open(os.path.join(xbmcvfs.translatePath(TEMP_PATH), name), 'w', encoding='utf-8') as handle:
            handle.write(text)
        return kept

    def ready(stream):
        return reachable(stream, fetch, save, log)

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
            desk._did_not_play('did not open')
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

    BUSY = 'Window.IsActive(busydialog) | Window.IsActive(busydialognocancel)'
    DIALOG = 'System.HasActiveModalDialog + !Window.IsActive(busydialog) + !Window.IsActive(busydialognocancel)'

    def wanted_now(key):
        # (Kodi's busy dialog may still be closing: what is read of the home under it is not the home's)
        for _ in range(10):
            if not xbmc.getCondVisibility(BUSY) or listener.waitForAbort(0.1):
                break
        return (enabled() and xbmc.getCondVisibility('Window.IsActive(home)') and not xbmc.getCondVisibility(DIALOG) and
                xbmc.getInfoLabel('Control.GetLabel(%d)' % HERO_LABEL) == key)

    def look(key):
        label = xbmc.getInfoLabel('Control.GetLabel(%d)' % HERO_LABEL)
        return 'home=%d dialog=%d busy=%d title=%s focus=%s' % (
            xbmc.getCondVisibility('Window.IsActive(home)'), xbmc.getCondVisibility(DIALOG), xbmc.getCondVisibility(BUSY),
            'same' if label == key else ('none' if not label else 'another'), xbmc.getInfoLabel('System.CurrentControlId') or 'none')

    player = Events()
    desk = Desk(home, player, resolve, make_item, enabled, log, ready=ready,
                halt=lambda: xbmc.executebuiltin('PlayerControl(Stop)'),
                wanted_now=wanted_now, look=look, settle=SETTLE_S)

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
