"""Ratings from several sites for the title the skin shows (Onyx).

The owner (Nov 2026): the hero shows one number -- TMDb's, from POV's list -- so why not
the full set, for every film, show and episode, everywhere in the build.

WHERE THEY COME FROM. Trakt's ratings call answers, in one request and with no
account -- only the application key POV already carries in its settings:
  /movies/<imdb>/ratings?extended=all                           IMDb (+votes), Rotten
  /shows/<imdb>/ratings?extended=all                            Tomatoes (critics and
  /shows/<imdb>/seasons/<s>/episodes/<e>/ratings?extended=all   audience), Metacritic,
                                                                Trakt, TMDb, Letterboxd
An episode has its own IMDb, TMDb and Trakt ratings; a season is shown its show's.
POV's own "extras" window reads the same call (trakt_ratings_info).

HOW THE SKIN ASKS. No polling and no script per title: the skin names the title it
shows in Window(home).Property(<slot>ask) once the screen has rested on it, and
announces it (NotifyAll(povil.ratings,<slot name>)). One thread of the Wizard's
start-up service hears that, answers from memory, from the Wizard's addon_data
(ratings/, one small file per title) or from Trakt, writes the fields and LAST the
title they belong to (<slot>for) -- the skin shows a field only while that still
names the title on screen, so a slow answer never lands on another title. Nothing is
written when the skin has moved on meanwhile: its newer question answers for itself.

A title is asked again after three days (a new release's numbers move), a title
with no answer or a failed request after an hour, and after Trakt says "too many
requests" nothing is asked for five minutes (an hour when the key itself is refused).
"""
import json
import os
import threading
import time

SENDER = 'povil.ratings'
# slot name (the announcement's data) -> the property prefix it reads and writes
SLOTS = {'home': 'povil.rt.', 'player': 'povil.rtp.'}
FIELDS = ('tmdb', 'imdb', 'imdb_votes', 'tomato', 'tomato_state', 'popcorn', 'popcorn_state',
          'meta', 'meta_tone', 'trakt', 'letterboxd')
STORE = 'special://profile/addon_data/plugin.program.kodipovilwizard/ratings/'
API = 'https://api.trakt.tv'
KEEP = 3 * 24 * 3600
RETRY = 3600
PRUNE = 30 * 24 * 3600
BACK_OFF = 300
REFUSED = 3600           # the key was refused (401/403): not a request for every new title
MEMORY = 300
TIMEOUT = 5


def parse(key):
    """'tt1375666|movie||' -> (cache name, API path), or None for anything else."""
    parts = (key or '').split('|') + ['', '', '']
    imdb, kind, season, episode = (p.strip() for p in parts[:4])
    if not (imdb.startswith('tt') and imdb[2:].isdigit() and len(imdb) <= 12):
        return None
    if kind == 'movie':
        return 'movie-' + imdb, '/movies/%s/ratings' % imdb
    if kind in ('tvshow', 'season'):
        return 'show-' + imdb, '/shows/%s/ratings' % imdb
    if kind == 'episode' and season.isdigit() and episode.isdigit() and len(season) <= 4 and len(episode) <= 5:
        return ('episode-%s-%s-%s' % (imdb, int(season), int(episode)),
                '/shows/%s/seasons/%d/episodes/%d/ratings' % (imdb, int(season), int(episode)))
    return None


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def votes(count):
    """2764656 -> '2.8M', 75773 -> '76K', 812 -> '812'."""
    count = _number(count)
    if count is None:
        return ''
    if count >= 1e6:
        return ('%.1f' % (count / 1e6)).rstrip('0').rstrip('.') + 'M'
    if count >= 1e3:
        return '%dK' % round(count / 1e3)
    return '%d' % count


def shape(data):
    """Trakt's answer as the strings the skin shows; a site with no rating is left out."""
    out = {}
    if not isinstance(data, dict):
        return out

    def site(name):
        value = data.get(name)
        return value if isinstance(value, dict) else {}
    tmdb = _number(site('tmdb').get('rating'))
    if tmdb is not None:
        out['tmdb'] = '%.1f' % tmdb
    imdb = _number(site('imdb').get('rating'))
    if imdb is not None:
        out['imdb'] = '%.1f' % imdb
        out['imdb_votes'] = votes(site('imdb').get('votes'))
    trakt = _number(site('trakt').get('rating'))
    if trakt is not None and _number(site('trakt').get('votes')) is not None:
        out['trakt'] = '%d%%' % round(trakt * 10)
    tomato = _number(site('rotten_tomatoes').get('rating'))
    if tomato is not None:
        state = str(site('rotten_tomatoes').get('state') or '').lower()
        out['tomato'] = '%d%%' % round(tomato)
        out['tomato_state'] = 'certified' if 'cert' in state else (
            'rotten' if 'rotten' in state or (not state and tomato < 60) else 'fresh')
    popcorn = _number(site('rotten_tomatoes').get('user_rating'))
    if popcorn is not None:
        state = str(site('rotten_tomatoes').get('user_state') or '').lower()
        out['popcorn'] = '%d%%' % round(popcorn)
        out['popcorn_state'] = 'spilled' if 'spill' in state or (not state and popcorn < 60) else 'upright'
    meta = _number(site('metascore').get('rating'))
    if meta is not None:
        out['meta'] = '%d' % round(meta)
        out['meta_tone'] = 'good' if meta >= 61 else ('mixed' if meta >= 40 else 'bad')
    letterboxd = _number(site('letterboxd').get('rating'))
    if letterboxd is not None:
        out['letterboxd'] = '%.1f' % letterboxd
    return out


class Store(object):
    """What was fetched, in memory and in one small file per title."""

    def __init__(self, folder, fetch, clock=time.time):
        self.folder, self.fetch, self.clock = folder, fetch, clock
        self.memory = {}
        self.blocked_until = 0
        self.pruned = 0

    def _file(self, name):
        return os.path.join(self.folder, name + '.json')

    def _read(self, name):
        try:
            with open(self._file(name), 'r', encoding='utf-8') as source:
                kept = json.load(source)
            if isinstance(kept, dict) and isinstance(kept.get('ratings'), dict) and isinstance(kept.get('at'), (int, float)):
                return kept
        except (OSError, ValueError):
            pass
        return None

    def _write(self, name, kept):
        try:
            os.makedirs(self.folder, exist_ok=True)
            temp = self._file(name) + '.new'
            with open(temp, 'w', encoding='utf-8') as target:
                json.dump(kept, target)
            os.replace(temp, self._file(name))
        except OSError:
            pass

    def _fresh(self, kept):
        age = self.clock() - kept['at']
        return 0 <= age < (KEEP if kept.get('ok') else RETRY)

    def _remember(self, name, kept):
        if len(self.memory) >= MEMORY:
            for old in sorted(self.memory, key=lambda k: self.memory[k]['at'])[:MEMORY // 4]:
                del self.memory[old]
        self.memory[name] = kept

    def lookup(self, key):
        """The ratings of one title: {} when it has none, cannot be named or cannot be asked now."""
        target = parse(key)
        if target is None:
            return {}
        name, path = target
        kept = self.memory.get(name)
        if kept is None:
            kept = self._read(name)
            if kept is not None:
                self._remember(name, kept)
        if kept is not None and self._fresh(kept):
            return kept['ratings']
        if self.clock() < self.blocked_until:
            return kept['ratings'] if kept else {}
        status, data = self.fetch(path)
        if status in (429, 401, 403):
            self.blocked_until = self.clock() + (BACK_OFF if status == 429 else REFUSED)
            return kept['ratings'] if kept else {}
        if status == 200:
            fresh = {'at': self.clock(), 'ok': True, 'ratings': shape(data)}
        elif kept is not None and kept.get('ok'):
            # a failed request does not wipe what was known: shown as it was, asked again in an hour
            fresh = {'at': self.clock() - KEEP + RETRY, 'ok': True, 'ratings': kept['ratings']}
        else:
            fresh = {'at': self.clock(), 'ok': False, 'ratings': {}}
        self._remember(name, fresh)
        self._write(name, fresh)
        self.prune()
        return fresh['ratings']

    def prune(self):
        """Once a day: files not written for a month go."""
        now = self.clock()
        if now - self.pruned < 24 * 3600:
            return
        self.pruned = now
        try:
            for entry in os.listdir(self.folder):
                path = os.path.join(self.folder, entry)
                if entry.endswith(('.json', '.new')) and now - os.path.getmtime(path) > PRUNE:
                    os.remove(path)
        except OSError:
            pass


def trakt_fetch(path):
    """(HTTP status, parsed answer) for one ratings call; (0, None) when it could not be made."""
    import urllib.error
    import urllib.request
    import xbmcaddon
    try:
        key = xbmcaddon.Addon('plugin.video.pov').getSetting('trakt.client_id')
    except Exception:
        key = ''
    if not key:
        return 0, None
    request = urllib.request.Request(API + path + '?extended=all', headers={
        'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': key, 'User-Agent': 'Kodi'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
            return 200, json.loads(reply.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:
        return 0, None


def answer(home, store, slot):
    """Answer the title the skin named in <slot>ask; True when its fields were written."""
    prefix = SLOTS[slot]
    key = home.getProperty(prefix + 'ask')
    if not key or home.getProperty(prefix + 'for') == key:
        return False
    ratings = store.lookup(key)
    if home.getProperty(prefix + 'ask') != key:
        return False           # the skin moved on: its newer question answers for itself
    for field in FIELDS:
        home.setProperty(prefix + field, ratings.get(field, ''))
    home.setProperty(prefix + 'for', key)
    return True


def watch():
    """The Wizard's start-up service runs this as one of its threads, for as long as Kodi runs."""
    import xbmc
    import xbmcgui
    import xbmcvfs
    home = xbmcgui.Window(10000)
    store = Store(xbmcvfs.translatePath(STORE), trakt_fetch)
    asked = set()
    wake = threading.Event()
    closing = []

    class Listener(xbmc.Monitor):
        def onNotification(self, sender, method, data):
            # NotifyAll(povil.ratings,home) arrives as sender 'povil.ratings', method 'Other.home'
            slot = method.rpartition('.')[2] if sender == SENDER else None
            if slot in SLOTS:
                asked.add(slot)
                wake.set()

    def work():
        while not closing:
            wake.wait()
            wake.clear()
            while asked and not closing:
                slot = asked.pop()
                try:
                    answer(home, store, slot)
                except Exception as exc:
                    xbmc.log('[POV IL ratings] %s: %r' % (slot, exc), xbmc.LOGWARNING)

    worker = threading.Thread(target=work, name='POVILRatingsWork')
    worker.start()
    listener = Listener()
    try:
        # callbacks are delivered while this thread waits here
        while not listener.waitForAbort(600):
            pass
    finally:
        closing.append(True)
        wake.set()
        worker.join(TIMEOUT + 2)
