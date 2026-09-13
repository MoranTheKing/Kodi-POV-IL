"""Selected-provider viewing evidence; read-only, never a declaration of liking."""
import sqlite3
from pathlib import Path
from .engine import identity


def selected_database(settings):
    selected = settings.get('watched_indicators','0') if settings.get('trakt_user') or settings.get('mdblist_user') else '0'
    return {'0':'watched.db','1':'traktcache.db','2':'mdblcache.db'}.get(selected)


def read_watched(path):
    if not path or not Path(path).is_file():
        return dict(status='unknown',keys=[],reason='missing_cache')
    db=None
    try:
        db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)
        db.execute('PRAGMA query_only=ON')
        ordered = any(row[1] == 'last_played' for row in db.execute('PRAGMA table_info(watched_status)'))
        rows=db.execute("SELECT db_type, media_id FROM watched_status WHERE db_type IN ('movie', 'episode')" +
                        (' ORDER BY last_played DESC' if ordered else '') + ' LIMIT 20000').fetchall()
        return _snapshot(rows, path, ordered)
    except (sqlite3.Error,OSError,ValueError):
        return dict(status='unknown',keys=[],reason='unreadable_schema_or_cache')
    finally:
        if db is not None:db.close()


def umbrella_local_selected(settings):
    value=settings.get('indicators.alt','0')
    return value=='0' or value=='4' and settings.get('dev.enable.custom')!='true'


def read_umbrella_local(path):
    if not path or not Path(path).is_file():return dict(status='unknown',keys=[],reason='missing_cache')
    db=None
    try:
        db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)
        db.execute('PRAGMA query_only=ON')
        ordered = any(row[1] == 'last_played' for row in db.execute('PRAGMA table_info(watched)'))
        rows=db.execute("SELECT media_type, tmdb_id FROM watched WHERE media_type IN ('movie', 'episode', 'tvshow') AND overlay=5" +
                        (' ORDER BY last_played DESC' if ordered else '') + ' LIMIT 20000').fetchall()
        return _snapshot(rows, path, ordered)
    except (sqlite3.Error,OSError,ValueError):return dict(status='unknown',keys=[],reason='unreadable_schema_or_cache')
    finally:
        if db is not None:db.close()


def _snapshot(rows, path, ordered=True):
    # One watched episode proves exposure to a show, not that the entire show
    # is complete or enjoyed. Keep show seeds separate from watched exclusions.
    movies, shows, seeds, seen = [], [], [], set()
    for kind, tmdb in rows:
        kind = 'tvshow' if kind in ('episode', 'tvshow') else kind
        try:
            key = identity(kind, tmdb)
        except ValueError:
            continue
        if key in seen:
            continue
        seen.add(key)
        seeds.append(key)  # SQL recency order, never numeric TMDB ID order.
        (movies if kind == 'movie' else shows).append(key)
    return dict(status='cached_history', keys=movies, seed_keys=seeds,
                observed_series=shows, reason='viewing_is_not_liking',
                absence_is_unknown=True, order='recent_first' if ordered else 'unknown', mtime=Path(path).stat().st_mtime)
