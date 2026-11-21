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

THE NUMBER ON A PICTURE'S CORNER (Wizard 0.5.41; patches/pov_rating.py has the sums) is
the average of these sites, each out of ten. It is answered with the fields (<slot>avg).
The pictures get theirs where POV's lists are built, in another process, so every
title's sum is also kept in ONE small file (average.idx), written a moment after the
answers. Kodi works a picture's number out when its row is loaded and not again (seen
on the QA Kodi's screen), so a row built before a title was asked about keeps the
number known then until it is loaded again. The rows are therefore asked again:
  * AT ONCE when the picture of the title the screen is on shows another number than
    the row beside it was just answered with -- the one place where the viewer sees
    both numbers (not more often than every few seconds, never twice for a title).
    On the home that is the rows; in an open list (the Videos window) the list;
  * and once the titles asked ahead are in, for what was learned of the pictures
    beside it -- only while nothing plays: the titles the viewer is not on can wait
    for the trailer to end.
Never while a title is starting, a dialog is open or a film plays, and with no scan
dialog: Kodi's would stop a trailer over the home (the reviewer, Nov 2026).
"""
import json
import os
import sys
import threading
import time

# patches/pov_rating.py: the average's sums and its one file, shared with POV's lists (which import it by
# that folder too -- the Wizard's patches put it on POV's path)
_PATCHES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'patches')
if _PATCHES not in sys.path:
    sys.path.append(_PATCHES)
import pov_rating  # noqa: E402

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
AVERAGE = 'avg'          # <slot>avg: the average, answered with the fields
LIST = 'list'            # <slot>list: the list's own figure for the title asked (TMDb's, from POV), set by the skin
SKIN_SHOWS = 'povil.avg.skin'   # set by a skin that shows the average: an older one gets no refresh for nothing
ITEM_AVERAGE, ITEM_SOURCE = 'Property(povil_avg)', 'Property(povil_avg_src)'    # pov_rating.PROPERTY / SOURCE on an item
INDEX_EVERY = 2          # seconds between two writes of the averages' file while titles are being asked
REFRESH_EVERY = 30       # seconds between two refreshes of the home's rows for the pictures beside the title
REFRESH_SOON = 5         # ... and for the picture of the title on screen
REFRESH_WAIT = 2         # how often a refresh that is owed is looked at again
TRIED = 300              # titles remembered as refreshed for (never twice: a picture that stays wrong is not chased)
# The refresh's moment: the home with nothing over it, no title about to play (a trailer being opened), no library
# scan of the viewer's own (the refresh is a scan of nothing: it would end a real one) ...
_REFRESH_BASE = ('Window.IsActive(home) + !System.HasActiveModalDialog + '
                 'String.IsEmpty(Window(home).Property(povil.tr.opening)) + !Library.IsScanningVideo')
# ... for the pictures beside the title: nothing playing at all; for the picture of the title on screen: nothing
# but a trailer over the home (povil.tr.on -- the trailer desk's mark; a film or an episode is never loaded under)
REFRESH_WHEN = _REFRESH_BASE + ' + !Player.HasMedia'
# (and the viewer at rest for a moment: a row loaded again under keys being pressed may stutter on a weak box -- the
# reviewer)
REFRESH_NOW = (_REFRESH_BASE + ' + [!Player.HasMedia | !String.IsEmpty(Window(home).Property(povil.tr.on))] + '
               'System.IdleTime(1)')
# An open list (the Videos window, Onyx's views): its own refresh, and only while nothing plays -- loading a list
# again there may bring Kodi's busy dialog, which stops a trailer
VIEW_LISTS = (51, 55)
REFRESH_VIEW = ('Window.IsActive(videos) + !System.HasActiveModalDialog + !Player.HasMedia + '
                'String.IsEmpty(Window(home).Property(povil.tr.opening)) + System.IdleTime(1)')
VIEW_BUILTIN = 'Container.Refresh'
STALE_S = 20             # a refresh wanted for the picture on screen that found no moment for this long is dropped
# (the third word: no dialog -- Kodi's scan progress over the home stops a trailer there)
REFRESH_BUILTIN = 'UpdateLibrary(video,special://skin/foo,false)'
ROWS_REFRESHED = 'povil.rows.refreshed'    # pov_list_snapshot.REFRESHED_PROPERTY: one refresh covers every row
PLAY_STARTED = 'povil.play.started'        # pov_play_guard.PROPERTY: a title was picked and looks for its sources
PLAY_WINDOW_S = 60


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
        # every title's sum for the average (pov_rating.py), and its one file
        self.sums = None
        self.sums_dirty = False
        self.sums_written = 0
        self.writing = threading.Lock()  # one writer of the file at a time
        self.learned = 0                # titles whose number changed since the home's rows were last asked again

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

    def _sums(self):
        """Every title's sum; read from the one file, or -- the first time, and whenever that file is gone --
        gathered from the titles' own files. The reading is done outside the lock (a store of thousands of
        files takes a while once, and the answers do not wait for it)."""
        sums = self.sums
        if sums is not None:
            return sums
        path = os.path.join(self.folder, pov_rating.INDEX)
        gathered = pov_rating.read_index(path) if os.path.isfile(path) else None
        dirty = False
        if gathered is None:
            gathered = {}
            try:
                names = [entry[:-5] for entry in os.listdir(self.folder) if entry.endswith('.json')]
            except OSError:
                names = []
            for name in names:
                kept = self._read(name)
                entry = pov_rating.entry_of(kept['ratings']) if kept else None
                if entry:
                    gathered[name] = entry
            dirty = bool(gathered)
        with self.guard:
            if self.sums is None:
                self.sums, self.sums_dirty = gathered, dirty
            return self.sums

    def _note(self, name, ratings):
        """A title was answered: its sum, kept when it changed. It counts as news for the pictures only when
        the number a picture shows changes -- a first answer that averages to the one figure the picture
        already had (TMDb's) changes nothing on the screen."""
        entry = pov_rating.entry_of(ratings)
        sums = self._sums()
        with self.guard:
            old = sums.get(name)
            if entry == old:
                return
            before = pov_rating.average(old) if old else pov_rating.shown((ratings or {}).get('tmdb'))
            sums.pop(name, None)            # (the newest last: the oldest fall off a file that grew too long)
            if entry is not None:
                sums[name] = entry
            self.sums_dirty = True
            if pov_rating.average(entry) != before:
                self.learned += 1

    def flush(self, force=False):
        """Write the averages' file when a sum changed -- a moment after it did, not once per title.
        True when the file holds every sum now."""
        sums = self._sums()
        with self.writing:
            with self.guard:
                if not self.sums_dirty:
                    return True
                if not force and 0 <= self.clock() - self.sums_written < INDEX_EVERY:
                    return False
                titles = dict(sums)
                self.sums_dirty = False
                self.sums_written = self.clock()
            if not pov_rating.write_index(os.path.join(self.folder, pov_rating.INDEX), titles):
                # (POV's process may hold the file open for a moment on Windows: written at the next answer)
                with self.guard:
                    self.sums_dirty = True
                return False
            return True

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
        # (noted before its file is written: the first note gathers the sums from the files that were there)
        self._note(name, fresh['ratings'])
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
                    if entry.endswith('.json'):
                        sums = self._sums()
                        with self.guard:
                            if sums.pop(entry[:-5], None) is not None:
                                self.sums_dirty = True
        except OSError:
            pass


# The lines to Trakt, shared by the workers. Each worker used to keep its own: the one that asks
# titles ahead used its line all the time, while the two that take only the title on screen let
# theirs go cold -- and a title the viewer jumped to (the owner, on a phone: "skipping a few
# posters ahead the ratings are back to one or two seconds") was asked on a line Trakt had
# closed: a failed try, then a new secure connection. Now a title on screen takes the line used
# LAST, and a title asked ahead the one used longest ago -- which keeps every line warm while
# there is anything to ask ahead.
_LINES = threading.local()      # .urgent: is this worker asking for the title on screen now?
_POOL = []                      # [last used, line] of the lines no worker holds
_POOL_LOCK = threading.Lock()
POOL = 3
SLOW_S = 0.7                    # an answer for the title on screen slower than this is said in the log


def _take_line(urgent):
    with _POOL_LOCK:
        if not _POOL:
            return None
        _POOL.sort(key=lambda entry: entry[0])
        return (_POOL.pop() if urgent else _POOL.pop(0))[1]


def _give_line(line):
    with _POOL_LOCK:
        _POOL.append([time.time(), line])
        extra = [] if len(_POOL) <= POOL else [_POOL.pop(0)[1]]
    for old in extra:
        try:
            old.close()
        except Exception:
            pass


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
    _LINES.how = ''
    for attempt in (0, 1):
        line = _take_line(getattr(_LINES, 'urgent', True)) if attempt == 0 else None
        try:
            if line is None:
                _LINES.how = 'new line' if attempt == 0 else 'kept line was closed, new line'
                line = http.client.HTTPSConnection(HOST, timeout=TIMEOUT)
            line.request('GET', path + '?extended=all', headers=headers)
            reply = line.getresponse()
            body = reply.read()
            _give_line(line)
            if reply.status != 200:
                return reply.status, None
            return 200, json.loads(body.decode('utf-8'))
        except Exception:
            # a line kept open may have been closed at the far end: once more on a new one
            try:
                line.close()
            except Exception:
                pass
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
        # the average of what the row shows (TMDb's from the list when Trakt gave none for it: the row shows
        # that one then)
        home.setProperty(prefix + AVERAGE,
                         pov_rating.average(pov_rating.entry_of(ratings), home.getProperty(prefix + LIST)))
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

    def __init__(self, home, store, read=None, log=None, refresh=None):
        self.home, self.store, self.read, self.log = home, store, read, log
        self.refresh = refresh          # refresh(soon) asks the home's rows again; False when this is not the moment
        self.refreshed = 0
        # the picture of the title on screen shows another number than its row: (where -- 'home' or 'view' --, since when)
        self.stale = None
        self.tried = []                 # the titles a refresh was already wanted for
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
            self.look()
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
        _LINES.urgent = rank == self.URGENT
        began = time.time()
        try:
            ratings = self.store.lookup(key)
        finally:
            with self.lock:
                self.busy.discard(key)
                waiting = len(self.jobs)
        took = time.time() - began
        if self.log is not None and rank == self.URGENT and took >= SLOW_S:
            self.log('slow answer for the title on screen: %d ms (%s), %d waiting' % (
                took * 1000, getattr(_LINES, 'how', '') or 'kept line', waiting))
        for name, prefix in SLOTS.items():
            # whichever slot asks for this title now gets it (a title asked ahead that the focus reached)
            if self.home.getProperty(prefix + 'ask') == key and self.home.getProperty(prefix + 'for') != key:
                if publish(self.home, prefix, key, ratings) and name == 'home':
                    self.look()
        flush = getattr(self.store, 'flush', None)
        if flush is not None:
            flush(force=not waiting)
        return True

    def look(self):
        """The title the home's row was just answered for: does its picture, in the row the focus is in, show the
        row's number? A picture keeps the number its row was loaded with (Kodi works a list item's label out once),
        so one built before the title was asked about does not -- and here the viewer sees both. Then the rows are
        owed a refresh soon. Only a picture POV's lists gave a number (ITEM_SOURCE): without the Wizard's patch in
        POV no refresh would ever change it."""
        if self.read is None or self.refresh is None:
            return False
        prefix = SLOTS['home']
        key, number = self.home.getProperty(prefix + 'for'), self.home.getProperty(prefix + AVERAGE)
        if not key or not number or self.home.getProperty(prefix + 'ask') != key or key in self.tried:
            return False
        control = (self.read('System.CurrentControlID') or '').strip()
        if not control.isdigit():
            return False
        if HOME_ROWS[0] <= int(control) <= HOME_ROWS[1]:
            where = 'home'
        elif int(control) in VIEW_LISTS:
            where = 'view'
        else:
            return False
        item = 'Container(%s).ListItem.' % control
        if (self.read(item + 'UniqueID(imdb)') or '').strip() != key.split('|')[0]:
            return False
        if not (self.read(item + ITEM_SOURCE) or '').strip() or (self.read(item + ITEM_AVERAGE) or '').strip() == number:
            return False
        self.tried.append(key)
        del self.tried[:-TRIED]
        self.stale = (where, self.store.clock(), key)
        with self.lock:
            self.lock.notify_all()          # the worker that sees to the rows need not sleep on
        return True

    def owed(self):
        """A refresh of the home's rows is wanted: for the picture of the title on screen, or because an
        average changed since the rows were last asked again. Never on a skin that shows no averages (it says
        so: SKIN_SHOWS) -- there a refresh would change nothing, and the worker need not look every few seconds."""
        if self.refresh is None or not self.home.getProperty(SKIN_SHOWS):
            return False
        return self.stale is not None or bool(getattr(self.store, 'learned', 0))

    def settle(self):
        """The pictures on the home carry the average known when their row was loaded. What was learned since
        reaches them by a refresh of the rows: soon, for the picture of the title on screen; for the pictures
        beside it once nothing more is being asked -- not one refresh per title. self.refresh says whether this
        is the moment (never while a dialog is open or a title is starting). True when the rows were asked again."""
        if not self.owed():
            return False
        now = self.store.clock()
        if self.stale is not None and (not 0 <= now - self.stale[1] < STALE_S
                                       or self.home.getProperty(SLOTS['home'] + 'for') != self.stale[2]):
            # the viewer went elsewhere meanwhile (another title, another window): the next load of the rows puts
            # that picture right
            self.stale = None
            if not self.owed():
                return False
        soon = self.stale[0] if self.stale is not None else None
        with self.lock:
            if self.closing or (not soon and (self.busy or any(job[2] is not None for job in self.jobs))):
                return False
        if 0 <= now - self.refreshed < (REFRESH_SOON if soon else REFRESH_EVERY):
            return False
        if not self.store.flush(force=True):
            return False                # the file could not be written: the rows would read the old one
        learned = self.store.learned
        if not self.refresh(soon):
            return False
        self.refreshed = now
        self.stale = None
        if soon != 'view':              # (an open list loaded again says nothing of the home's rows)
            with self.store.guard:
                self.store.learned -= learned
        if self.log is not None:
            self.log('%s: %s' % ('the open list is loaded again' if soon == 'view' else 'the rows are asked again',
                                 'the picture on screen showed another number than its row' if soon
                                 else 'the averages of %d titles changed' % learned))
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
    home = xbmcgui.Window(10000)

    def refresh_rows(soon):
        if not home.getProperty(SKIN_SHOWS):
            return False
        if soon == 'view':
            if not xbmc.getCondVisibility(REFRESH_VIEW):
                return False
            xbmc.executebuiltin(VIEW_BUILTIN)
            return True
        if not xbmc.getCondVisibility(REFRESH_NOW if soon else REFRESH_WHEN):
            return False
        try:
            if 0 <= time.time() - float(home.getProperty(PLAY_STARTED) or 0) < PLAY_WINDOW_S:
                return False
        except ValueError:
            pass
        # (POV's own widget refresh, as pov_list_snapshot asks it: every row is asked again, each from its saved copy)
        home.setProperty(ROWS_REFRESHED, repr(time.time()))
        xbmc.executebuiltin(REFRESH_BUILTIN)
        return True

    desk = Desk(home, Store(xbmcvfs.translatePath(STORE), trakt_fetch), xbmc.getInfoLabel,
                log=lambda text: xbmc.log('[POV IL ratings] ' + text, xbmc.LOGINFO), refresh=refresh_rows)

    def patched():
        target, mark = pov_rating.PATCHED
        with open(os.path.join(xbmcvfs.translatePath('special://home/addons/plugin.video.pov/'), *target.split('/')),
                  encoding='utf-8') as source:
            return mark in source.read()

    def first_things():
        # The averages' file for POV's lists (gathered from the store's own files the first time), and -- once per
        # device, when POV's lists are first found giving their items the average -- the lists saved before are
        # let go, and the rows on the screen, built before, are owed a refresh.
        desk.store.flush(force=True)
        if pov_rating.lists_once(xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/'), patched):
            with desk.store.guard:
                desk.store.learned += 1
            xbmc.log('[POV IL ratings] POV\'s lists carry the average now: the saved lists are built again', xbmc.LOGINFO)

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
        if not urgent_only:
            try:
                first_things()
            except Exception as exc:
                xbmc.log('[POV IL ratings] first things: %r' % (exc,), xbmc.LOGWARNING)
        while not desk.closing:
            try:
                # Every worker sleeps until there is a job. The one that asks ahead also sees to the rows: only
                # while a refresh is owed does it look again, every few seconds, whether this is the moment.
                owed = not urgent_only and desk.owed()
                desk.step(wait=REFRESH_WAIT if owed else 60, urgent_only=urgent_only)
                if not urgent_only:
                    desk.settle()
            except Exception as exc:
                xbmc.log('[POV IL ratings] %r' % (exc,), xbmc.LOGWARNING)

    # the first worker takes anything; the others only the title on screen
    workers = [threading.Thread(target=work, args=(n > 0,), name='POVILRatingsWork%d' % n) for n in range(WORKERS)]
    for worker in workers:
        worker.start()
    listener = Listener()
    # The skin asks once per title, the moment the home shows it -- and this thread starts only once the
    # home has settled, so the first title of every start had been asked before anyone listened: it showed
    # TMDb's rating alone (the list's own) until the viewer moved away and back (the owner, Nov 2026: "the
    # first screen on every device shows only the TMDb rating ... moving forward and back shows them all").
    # What the skin asked is still in its property: answered now.
    for slot in SLOTS:
        try:
            desk.asked(slot)
        except Exception as exc:
            xbmc.log('[POV IL ratings] first ask %s: %r' % (slot, exc), xbmc.LOGWARNING)
    try:
        # callbacks are delivered while this thread waits here
        while not listener.waitForAbort(600):
            pass
    finally:
        desk.close()
        for worker in workers:
            worker.join(TIMEOUT + 2)
