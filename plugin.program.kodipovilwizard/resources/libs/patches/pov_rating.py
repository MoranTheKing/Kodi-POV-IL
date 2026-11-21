"""The number on a picture's corner: the average of what the sites say about the title.

The owner (Nov 2026), and a viewer the day before: the corner of a poster showed 6.6 where the row of sites
beside the title said TMDb 6.5, IMDb 6.6 and Trakt 71% -- "the average on the poster is not the average ... I
did not understand where this 6.6 was made up from"; a series showed 8 where no site reached 8; a new film
with no votes on TMDb showed nothing while Trakt had a rating for it. The corner showed POV's own figure for
the title, which is TMDb's, alone.

Now it shows the average of every site the row names, each counted out of ten:

    TMDb, IMDb                  as they are            6.5, 6.6
    Trakt, the tomato, the      a tenth of the         71% -> 7.1
    popcorn, Metacritic         figure
    Letterboxd                  twice the figure       3.4 of 5 -> 6.8

rounded to one place, from the figures as the row shows them -- so anyone can add the row up and get the corner.

WHERE THE FIGURES COME FROM. The Wizard's ratings.py asks Trakt for a title's ratings and keeps one small file
per title. It also keeps ONE file for all of them, average.idx -- per title the sum of its figures in tenths,
how many they are, and whether TMDb's is among them. A list is built in another process (POV's, a new one for
every row), and reads that one file with marshal: no JSON, no file per title (see pov_list_snapshot.py on what
an import costs while Kodi starts).

WHO WRITES THE CORNER. POV builds a title's item (stamp(), called from its lists by the Wizard's patches): the
item gets the average (ListItem.Property(povil_avg)) and what it was worked out from (povil_avg_src: the title's
name in the store and POV's own figure). A list shown from its saved copy (pov_list_snapshot.py) works the
average out again from the copy's povil_avg_src and the file of the moment (replayed()), so a saved list never
shows an old average. ListItem.Rating stays POV's figure: the row's TMDb mark and other skins read it.

A title Trakt has not been asked about yet shows POV's figure alone -- the average of the one site known --
and the row beside it shows that one site until the answer is in.
"""
import marshal
import os
import struct
import time

PROPERTY = 'povil_avg'
SOURCE = 'povil_avg_src'
INDEX = 'average.idx'
FORMAT = 1
STORE = 'special://profile/addon_data/plugin.program.kodipovilwizard/ratings/'
# (site, tenths of a point for one unit of the figure the row shows)
SITES = (('tmdb', 10.0), ('imdb', 10.0), ('trakt', 1.0), ('tomato', 1.0), ('popcorn', 1.0), ('meta', 1.0),
         ('letterboxd', 20.0))
RECHECK_S = 1.0             # the file is looked at again this long after the last look
# Written once per device, in POV's profile folder, when POV's lists first give their items the average
# (lists_once): pov_list_snapshot.py counts it among what a saved list depends on, so every list saved before
# is built again behind its first showing.
LISTS_FLAG = 'povil_rating_v1'
PATCHED = ('resources/lib/menus/movies.py', 'WIZARD_POV_RATING_MOVIE_v1')    # the file and the mark that say POV is patched
MOST = 6000                 # titles kept in the file


def tenths(text, scale=10.0):
    """'6.6' -> 66, '71%' -> 71 (scale 1), '' or nonsense or nothing above zero -> 0."""
    try:
        value = float(str(text).strip().rstrip('%'))
    except (TypeError, ValueError):
        return 0
    if not 0 < value * scale <= 100:
        return 0
    return int(value * scale + 0.5)


def shown(rating):
    """POV's figure as Kodi writes it on the screen: 6.634 -> '6.6'; '' for none. Kodi keeps a rating in four
    bytes, so 6.05 is a hair above itself there and shows as 6.1 (the reviewer): rounded from the same four."""
    try:
        value = struct.unpack('f', struct.pack('f', float(rating)))[0]
    except (TypeError, ValueError, OverflowError, struct.error):
        return ''
    return '%.1f' % value if 0 < value <= 10 else ''


def entry_of(ratings):
    """[sum in tenths, how many, is TMDb's among them] for one title's figures as ratings.shape() gives them;
    None when the title has none."""
    total = count = 0
    has_tmdb = False
    for site, scale in SITES:
        value = tenths((ratings or {}).get(site), scale)
        if value:
            total, count = total + value, count + 1
            has_tmdb = has_tmdb or site == 'tmdb'
    return [total, count, has_tmdb] if count else None


def average(entry, own=''):
    """'6.7' for a title's entry and POV's own figure (TMDb's: counted when Trakt gave none for TMDb -- the
    row shows it then too); '' when there is nothing to average."""
    total, count, has_tmdb = 0, 0, False
    if isinstance(entry, (list, tuple)) and len(entry) == 3:
        try:
            total, count, has_tmdb = int(entry[0]), int(entry[1]), bool(entry[2])
        except (TypeError, ValueError):
            total, count, has_tmdb = 0, 0, False
    if count <= 0 or total <= 0:
        total, count, has_tmdb = 0, 0, False
    mine = tenths(own)
    if mine and not has_tmdb:
        total, count = total + mine, count + 1
    if not count:
        return ''
    return '%d.%d' % divmod((2 * total + count) // (2 * count), 10)


def store_name(imdb, kind, season=None, episode=None):
    """The title's name in the Wizard's store, as ratings.parse() names it; None for anything else."""
    imdb = str(imdb or '').strip()
    if not (imdb.startswith('tt') and imdb[2:].isdigit() and len(imdb) <= 12):
        return None
    if kind == 'movie':
        return 'movie-' + imdb
    if kind in ('tvshow', 'season'):
        return 'show-' + imdb
    if kind == 'episode':
        try:
            return 'episode-%s-%d-%d' % (imdb, int(season), int(episode))
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------- the one file

def read_index(path):
    """{name: [sum, how many, has TMDb]} from the file; {} when it is missing or not ours."""
    try:
        with open(path, 'rb') as source:
            kept = marshal.loads(source.read())
        if isinstance(kept, dict) and kept.get('v') == FORMAT and isinstance(kept.get('titles'), dict):
            return kept['titles']
    except Exception:
        pass
    return {}


def write_index(path, titles):
    """The whole file, swapped in at once: a list being built never reads half of it."""
    if len(titles) > MOST:
        titles = dict(list(titles.items())[-MOST:])
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = path + '.new'
        with open(temp, 'wb') as target:
            target.write(marshal.dumps({'v': FORMAT, 'titles': titles}))
        os.replace(temp, path)
        return True
    except OSError:
        return False


_SEEN = {'path': None, 'mark': None, 'titles': {}, 'at': 0.0}


def _path():
    if _SEEN['path'] is None:
        import xbmcvfs
        _SEEN['path'] = os.path.join(xbmcvfs.translatePath(STORE), INDEX)
    return _SEEN['path']


def index(path=None, clock=time.time):
    """The file's titles, read again only when the file changed (POV's process may serve many lists)."""
    path = path or _path()
    now = clock()
    if _SEEN.get('for') == path and 0 <= now - _SEEN['at'] < RECHECK_S:
        return _SEEN['titles']
    try:
        stat = os.stat(path)
        mark = (stat.st_mtime, stat.st_size)
    except OSError:
        mark = None
    if _SEEN.get('for') != path or mark != _SEEN['mark']:
        _SEEN['titles'] = read_index(path) if mark else {}
        _SEEN['mark'], _SEEN['for'] = mark, path
    _SEEN['at'] = now
    return _SEEN['titles']


def lists_once(folder, ready=None):
    """Once per device. The Wizard patches POV's lists while Kodi starts -- and the home's rows are built at
    the same moment, by the POV of before, and saved (seen in the QA Kodi: the first rows after the update
    carried no average, and their saved copies would have shown that for hours). So the first time POV is
    found patched (ready()), the lists saved until then are let go. True when it was done now."""
    flag = os.path.join(folder, LISTS_FLAG)
    if os.path.exists(flag) or not os.path.isdir(folder):
        return False
    if ready is not None and not ready():
        return False
    with open(flag, 'w') as handle:
        handle.write('1')
    return True


# ---------------------------------------------------------------- the item

def stamp(listitem, imdb, kind, rating, season=None, episode=None, titles=None):
    """POV built a title's item: its corner's number, and what a saved copy needs to work it out again."""
    name = store_name(imdb, kind, season, episode)
    if not name:
        return ''
    own = shown(rating)
    number = average((index() if titles is None else titles).get(name), own)
    listitem.setProperty(SOURCE, '%s|%s' % (name, own))
    listitem.setProperty(PROPERTY, number)
    return number


def replayed(source, titles=None):
    """The corner's number for a saved item, from its povil_avg_src and the file of the moment."""
    name, _, own = str(source or '').partition('|')
    if not name:
        return ''
    return average((index() if titles is None else titles).get(name), own)
