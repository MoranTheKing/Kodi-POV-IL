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
shows in Window(home).Property(<slot>ask) the moment it shows it, and announces it
(NotifyAll(povil.ratings,<slot name>)). The Wizard's start-up service hears that and
answers at once from memory or from the Wizard's addon_data (ratings/, one small
file per title); a title not known is asked from Trakt by one of a few workers, and
the titles beside the focused one are asked ahead (see Desk). The fields are written
and LAST the title they belong to (<slot>for) -- the skin shows a field only while
that still names the title on screen, so a slow answer never lands on another title.
Nothing is written when the skin has moved on meanwhile: its newer question answers
for itself.

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
HOST = 'api.trakt.tv'
KEEP = 3 * 24 * 3600
RETRY = 3600
PRUNE = 30 * 24 * 3600
BACK_OFF = 300
REFUSED = 3600           # the key was refused (401/403): not a request for every new title
MEMORY = 300
TIMEOUT = 5
WORKERS = 3              # titles asked from Trakt at the same time
NEAR_AHEAD, NEAR_BEHIND = 10, 6     # titles beside the focused one that are asked ahead
ROW_HEAD = 8             # ... and this many of each other row on the screen
ROWS_EVERY = 20          # seconds between two looks at the other rows while the focus stays in one row
HOME_ROWS = (5011, 5199) # Onyx's home rows: 5<tab><row>; the rows of one tab share the tens
QUEUE = 90               # jobs waiting, at most


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
        self.guard = threading.Lock()
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
        with self.guard:
            if len(self.memory) >= MEMORY:
                for old in sorted(self.memory, key=lambda k: self.memory[k]['at'])[:MEMORY // 4]:
                    del self.memory[old]
            self.memory[name] = kept

    def known(self, key):
        """(ratings, fresh) from memory or the title's file, never the network. ratings is None when
        nothing is kept; a key that names no title is ({}, True): there is nothing to ask."""
        target = parse(key)
        if target is None:
            return {}, True
        name = target[0]
        kept = self.memory.get(name)
        if kept is None:
            kept = self._read(name)
            if kept is not None:
                self._remember(name, kept)
        if kept is None:
            # (while Trakt may not be asked, nothing is all there is to say)
            return ({}, True) if self.clock() < self.blocked_until else (None, False)
        return kept['ratings'], self._fresh(kept) or self.clock() < self.blocked_until

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


_LINES = threading.local()


_KEY = []


def _trakt_key():
    # read once: an add-on object for every request is slow, and the key does not change while Kodi runs
    if not _KEY:
        import xbmcaddon
        try:
            key = xbmcaddon.Addon('plugin.video.pov').getSetting('trakt.client_id')
        except Exception:
            key = ''
        if not key:
            return ''
        _KEY.append(key)
    return _KEY[0]


def trakt_fetch(path):
    """(HTTP status, parsed answer) for one ratings call; (0, None) when it could not be made.
    Each worker keeps its line to Trakt open: a new secure connection costs several times the
    request itself, and a row of titles is asked one after another."""
    import http.client
    key = _trakt_key()
    if not key:
        return 0, None
    headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': key,
               'User-Agent': 'Kodi', 'Connection': 'keep-alive'}
    for attempt in (0, 1):
        line = getattr(_LINES, 'line', None)
        try:
            if line is None:
                line = _LINES.line = http.client.HTTPSConnection(HOST, timeout=TIMEOUT)
            line.request('GET', path + '?extended=all', headers=headers)
            reply = line.getresponse()
            body = reply.read()
            if reply.status != 200:
                return reply.status, None
            return 200, json.loads(body.decode('utf-8'))
        except Exception:
            # a line kept open may have been closed at the far end: once more on a new one
            try:
                line.close()
            except Exception:
                pass
            _LINES.line = None
    return 0, None


_WRITING = threading.Lock()


def publish(home, prefix, key, ratings):
    """Write one title's fields and LAST the title they belong to -- only while the skin still asks
    for that title. One writer at a time: two answers never mix their fields."""
    with _WRITING:
        if home.getProperty(prefix + 'ask') != key:
            return False           # the skin moved on: its newer question answers for itself
        for field in FIELDS:
            home.setProperty(prefix + field, ratings.get(field, ''))
        home.setProperty(prefix + 'for', key)
        return True


def answer(home, store, slot):
    """Answer the title the skin named in <slot>ask, asking Trakt if need be; True when its fields
    were written."""
    prefix = SLOTS[slot]
    key = home.getProperty(prefix + 'ask')
    if not key or home.getProperty(prefix + 'for') == key:
        return False
    return publish(home, prefix, key, store.lookup(key))


def neighbours(read, behind=NEAR_BEHIND, ahead=NEAR_AHEAD, rows=False):
    """The keys of the titles a viewer may reach next, the likeliest first -- written exactly as the skin
    writes the focused title's key (ratings_row.key). `read` is Kodi's info-label reader.

    First the titles beside the focused one in its list, nearest first. With `rows`, on Onyx's home, also
    the first titles of every other row of the tab on the screen (the owner, Nov 2026: "on a phone one
    can go to a title that is not a neighbour" -- a tap lands on any picture in sight)."""
    control = (read('System.CurrentControlID') or '').strip()
    if not control.isdigit():
        return []
    keys = []

    def take(item):
        imdb = (read(item + 'UniqueID(imdb)') or '').strip()
        if not imdb.startswith('tt'):
            return
        key = '%s|%s|%s|%s' % (imdb, read(item + 'DBType') or '', read(item + 'Season') or '', read(item + 'Episode') or '')
        if key not in keys:
            keys.append(key)
    for step in range(1, max(ahead, behind) + 1):
        if step <= ahead:
            take('Container(%s).ListItemNoWrap(%d).' % (control, step))
        if step <= behind:
            take('Container(%s).ListItemNoWrap(%d).' % (control, -step))
    if rows and HOME_ROWS[0] <= int(control) <= HOME_ROWS[1]:
        tab = int(control) // 10 * 10
        for row in range(tab + 1, tab + 10):
            if row == int(control) or (read('Container(%d).NumItems' % row) or '0').strip() in ('', '0'):
                continue
            # from where the row stands (its own selected title), which is what is in sight
            for offset in range(ROW_HEAD):
                take('Container(%d).ListItemNoWrap(%d).' % (row, offset))
    return keys


class Desk(object):
    """Takes the skin's questions and answers them as fast as each can be answered.

    The owner (Nov 2026): TMDb's number was there at once and the others two seconds later --
    "all of them at once, instantly". Three things made the wait: the skin rested a second on a
    title before asking, every title was asked from Trakt on a new connection, and one title
    was asked at a time. Now:
      * a question is answered where it arrives from what is already known (memory, then the
        title's file) -- no network, a few milliseconds; what is known but old is shown and
        asked again behind it;
      * a title not known is asked at once by one of a few workers, the newest question first,
        each on a line to Trakt it keeps open;
      * the titles beside the focused one, and the first titles of the other rows on the screen,
        are asked ahead, so the next press -- or a tap anywhere, on a phone -- finds them known.
    """
    URGENT, AHEAD = 0, 1

    def __init__(self, home, store, read=None):
        self.home, self.store, self.read = home, store, read
        self.jobs = []                  # (rank, order, key, slot) -- taken smallest first
        self.count = 0
        self.busy = set()
        self.lock = threading.Condition()
        self.closing = False
        self.rows_seen = ('', 0.0)      # the list the other rows were last looked at from, and when

    def _put(self, rank, key, slot):
        with self.lock:
            self.count += 1
            if key is None:
                # one look at the screen is enough: an older one still waiting would read the same screen
                # again (each label read takes Kodi's GUI lock -- a fast scroll must not pile them up)
                self.jobs = [job for job in self.jobs if job[2] is not None]
            # the newest first, among questions and among titles asked ahead alike
            self.jobs.append((rank, -self.count, key, slot))
            self.jobs.sort()
            del self.jobs[QUEUE:]       # a long fast scroll: the oldest asked-ahead titles fall off
            self.lock.notify_all()      # (all: a worker that takes only the title on screen may not want this job)

    def asked(self, slot):
        """The skin announced a question in `slot`. Returns True when it was answered here."""
        prefix = SLOTS[slot]
        key = self.home.getProperty(prefix + 'ask')
        if not key:
            return False
        answered = False
        if self.home.getProperty(prefix + 'for') == key:
            answered = True
        else:
            ratings, fresh = self.store.known(key)
            if ratings is not None:
                answered = publish(self.home, prefix, key, ratings)
            if ratings is None or not fresh:
                self._put(self.URGENT, key, slot)
        if slot == 'home' and self.read is not None:
            self._put(self.URGENT, None, slot)          # look at the titles beside it, off this thread
        return answered

    def step(self, wait=None, urgent_only=False):
        """One job of one worker. Returns False when there was none (or the desk is closing).
        A worker with urgent_only takes only what the viewer is looking at now: titles asked ahead go
        through one worker, one request at a time -- a tab seen for the first time is some ninety titles,
        and Trakt answers "too many requests" to a burst (then even the focused title waits five minutes)."""
        with self.lock:
            mine = [job for job in self.jobs if not urgent_only or job[0] == self.URGENT]
            if not mine and not self.closing and wait:
                self.lock.wait(wait)
                mine = [job for job in self.jobs if not urgent_only or job[0] == self.URGENT]
            if self.closing or not mine:
                return False
            self.jobs.remove(mine[0])
            rank, _order, key, slot = mine[0]
            if key is not None:
                if key in self.busy:
                    return True         # another worker is asking this very title: it answers when it is done
                self.busy.add(key)
        if key is None:
            # The other rows are looked at when the focus came to another row, and now and then while
            # it stays (a row loads late, a tab changes): reading a screenful of labels is not free.
            focused, now = (self.read('System.CurrentControlID') or '').strip(), self.store.clock()
            rows = focused != self.rows_seen[0] or now - self.rows_seen[1] >= ROWS_EVERY
            if rows:
                self.rows_seen = (focused, now)
            # (put farthest first: the newest job is taken first, so the nearest title is asked first)
            for near in reversed(neighbours(self.read, rows=rows)):
                ratings, fresh = self.store.known(near)
                if ratings is None or not fresh:
                    self._put(self.AHEAD, near, None)
            return True
        try:
            ratings = self.store.lookup(key)
        finally:
            with self.lock:
                self.busy.discard(key)
        for name, prefix in SLOTS.items():
            # whichever slot asks for this title now gets it (a title asked ahead that the focus reached)
            if self.home.getProperty(prefix + 'ask') == key and self.home.getProperty(prefix + 'for') != key:
                publish(self.home, prefix, key, ratings)
        return True

    def close(self):
        with self.lock:
            self.closing = True
            self.lock.notify_all()


def watch():
    """The Wizard's start-up service runs this as one of its threads, for as long as Kodi runs."""
    import xbmc
    import xbmcgui
    import xbmcvfs
    desk = Desk(xbmcgui.Window(10000), Store(xbmcvfs.translatePath(STORE), trakt_fetch), xbmc.getInfoLabel)

    class Listener(xbmc.Monitor):
        def onNotification(self, sender, method, data):
            # NotifyAll(povil.ratings,home) arrives as sender 'povil.ratings', method 'Other.home'
            slot = method.rpartition('.')[2] if sender == SENDER else None
            if slot in SLOTS:
                try:
                    desk.asked(slot)
                except Exception as exc:
                    xbmc.log('[POV IL ratings] %s: %r' % (slot, exc), xbmc.LOGWARNING)

    def work(urgent_only):
        while not desk.closing:
            try:
                desk.step(wait=60, urgent_only=urgent_only)
            except Exception as exc:
                xbmc.log('[POV IL ratings] %r' % (exc,), xbmc.LOGWARNING)

    # the first worker takes anything; the others only the title on screen
    workers = [threading.Thread(target=work, args=(n > 0,), name='POVILRatingsWork%d' % n) for n in range(WORKERS)]
    for worker in workers:
        worker.start()
    listener = Listener()
    try:
        # callbacks are delivered while this thread waits here
        while not listener.waitForAbort(600):
            pass
    finally:
        desk.close()
        for worker in workers:
            worker.join(TIMEOUT + 2)
