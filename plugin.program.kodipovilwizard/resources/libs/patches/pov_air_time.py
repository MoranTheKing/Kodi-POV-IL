"""When an episode of a streaming service counts as aired (Wizard 0.5.38).

A viewer, Nov 2026: "a small bug: episode 6 shows in blue -- meaning no sources -- but there are sources; I pressed it
and there were". POV colours an episode it holds to be not aired yet. It takes TMDb's air date -- a date only, by the US
calendar -- puts the episode at 20:00 US Eastern that day, and adds 5 hours and its "UTC (+/-)" setting (0 in the
build): an episode of 20 Nov counts as aired from 01:00 on 21 Nov. That is a network's evening broadcast. A streaming
service puts its episodes out at midnight Pacific (08:00 UTC, morning in Israel) ON their date -- all that day POV showed
them as not aired, though they were out.

So POV's series data keeps the series' networks (TMDb's own -- POV dropped them; the patch pov_air_networks), and an
episode of a series all of whose networks are streaming services counts EARLY_HOURS sooner -- as POV compares calendar
dates, from its own date (in Israel from midnight, a few hours before it comes out). One that a broadcaster shows too
(HBO and HBO Max, a Japanese channel and Netflix) keeps the evening: white with no sources yet would be worse than blue
(the reviewer). Every other one as before.
A series POV saved before keeps its old data until POV asks again -- a running series: the day after its next episode,
too late for that episode -- so the running series are let go once (purge_once), from POV's database and from the copy
it keeps in the home window's properties, and asked again when next shown.
"""

# TMDb's networks of the streaming services that put their episodes out at midnight US time (TMDb's /network/<id>)
STREAMING = {213: 'Netflix', 1024: 'Prime Video', 2739: 'Disney+', 2552: 'Apple TV', 453: 'Hulu', 3186: 'HBO Max',
             4330: 'Paramount+', 3353: 'Peacock', 1436: 'YouTube Premium', 4353: 'discovery+'}
EARLY_HOURS = 17            # POV's 20:00 US Eastern -> 03:00 Eastern, midnight Pacific
KEY = 'povil_networks'      # in POV's series data, under extra_info
PURGE_FLAG = 'povil_air_networks_v1'
FINISHED = ('Ended', 'Canceled')


def networks(meta):
    try:
        return [int(n) for n in ((meta or {}).get('extra_info') or {}).get(KEY) or []]
    except Exception:
        return []


def streaming(meta):
    """Every one of the series' networks a streaming service (a series a broadcaster shows too keeps the evening)."""
    found = networks(meta)
    return bool(found) and all(n in STREAMING for n in found)


def hours(meta, adjust_hours):
    """POV's hours past 20:00 US Eastern of an episode's date for this series -- sooner for a streaming service's."""
    return adjust_hours - EARLY_HOURS if streaming(meta) else adjust_hours


def _to_let_go(meta_text):
    """The series' meta when it is one to ask again -- running, and saved without its networks -- else None. One that
    cannot be read stays."""
    import json
    try:
        meta = json.loads(meta_text)
        return meta if meta.get('status') not in FINISHED and KEY not in (meta.get('extra_info') or {}) else None
    except Exception:
        return None


def held_in_memory(tmdb, meta):
    """The home window's properties POV keeps a series' data in (caches/meta_cache.py: pov_meta_tvshow_<id type>_<id>,
    read before the database -- filled at POV's start and by every series opened)."""
    ids = [('tmdb_id', tmdb), ('imdb_id', meta.get('imdb_id')), ('tvdb_id', meta.get('tvdb_id'))]
    return ['pov_meta_tvshow_%s_%s' % (kind, value) for kind, value in ids if value not in (None, '')]


def purge_once(folder, connect=None, log=lambda text: None, forget=None, ready=None):
    """Once per device: the running series POV saved without their networks are let go -- each asked again (with them)
    the next time it is shown. forget(property): POV's copy in the home window's properties too. ready(): POV can keep
    networks now (the patch pov_air_networks is in) -- else nothing is done and it is tried at the next start. Returns
    how many, or None when there was nothing to do."""
    import os
    flag = os.path.join(folder, PURGE_FLAG)
    cache = os.path.join(folder, 'metacache.db')
    if os.path.exists(flag) or not os.path.isfile(cache):
        return None
    if ready is not None and not ready():
        return None
    if connect is None:
        import sqlite3
        connect = sqlite3.connect
    con = connect(cache, timeout=10.0)
    try:
        gone = []
        for tmdb, meta_text in con.execute("SELECT tmdb_id, meta FROM metadata WHERE db_type = 'tvshow'").fetchall():
            meta = _to_let_go(meta_text)
            if meta is not None:
                gone.append((tmdb, meta))
        con.executemany("DELETE FROM metadata WHERE db_type = 'tvshow' AND tmdb_id = ?", [(tmdb,) for tmdb, _m in gone])
        con.commit()
    finally:
        con.close()
    if forget is not None:
        for tmdb, meta in gone:
            for name in held_in_memory(tmdb, meta):
                try:
                    forget(name)
                except Exception:
                    pass
    with open(flag, 'w') as handle:
        handle.write('1')
    log('air times: %d running series will be asked again (their networks)' % len(gone))
    return len(gone)
