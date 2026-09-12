"""POV watched snapshot: read-only selected cache, never provider imports or writes."""
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
        rows=db.execute("SELECT db_type, media_id FROM watched_status WHERE db_type = 'movie' LIMIT 20000").fetchall()
        keys=[]
        for kind,tmdb in rows:
            try:keys.append(identity(kind,tmdb))
            except ValueError:continue
        return dict(status='cached_movies_only',keys=sorted(set(keys)),reason='absence_is_unknown',mtime=Path(path).stat().st_mtime)
    except (sqlite3.Error,OSError,ValueError):
        return dict(status='unknown',keys=[],reason='unreadable_schema_or_cache')
    finally:
        if db is not None:db.close()
