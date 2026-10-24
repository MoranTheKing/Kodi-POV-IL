"""Replace POV cache databases that SQLite itself reports as damaged.

Field report (24 Oct 2026, LG webOS TV, POV 6.10.22): after the disk filled
up, POV's providerscache.db was "database disk image is malformed". Every
search counted thousands of results and then showed "No Results", with nothing
in the log; POV's own Clear Cache could not help, its DELETE runs on the
damaged file. POV purges its caches with journal_mode=OFF and synchronous=OFF,
so a full disk in the middle of a write can leave one of them damaged.

At start-up each cache POV rebuilds by itself is checked with
PRAGMA quick_check. Only those: never watched, favourites, views, navigator or
the Trakt/MDBList data. A damaged one is deleted -- it is a cache, and on a
full device the space matters -- and POV's clean_databases recreates it.
A database that is merely locked or cannot be opened is left alone: only
SQLite's own verdict counts. A file with the same size and time as at its last
clean check is not read again, so a slow device pays for the check only after POV
has written to it.
"""
import json
import os
import sqlite3
import time

import xbmc
import xbmcvfs

from resources.libs.common import logging

POV_DATA = 'special://profile/addon_data/plugin.video.pov/'
STATE = 'special://profile/addon_data/plugin.program.kodipovilwizard/pov_cache_ok.json'
CACHE_DBS = ('providerscache.db', 'debridcache.db', 'maincache.db', 'metacache.db')
_DAMAGED = ('malformed', 'not a database', 'file is encrypted')


def check(path):
    """'ok' or 'damaged' when SQLite gave its verdict; 'unchecked' when it
    could not (locked, I/O error, full disk, unreadable)."""
    con = None
    try:
        # A short wait: POV's own maintenance may be VACUUMing it right now,
        # and start-up should not stand still for that.
        con = sqlite3.connect(path, timeout=1)
        row = con.execute('PRAGMA quick_check').fetchone()
        return 'ok' if row and row[0] == 'ok' else 'damaged'
    except sqlite3.DatabaseError as exc:
        # OperationalError ("database is locked") is a DatabaseError too.
        message = str(exc).lower()
        return 'damaged' if any(word in message for word in _DAMAGED) else 'unchecked'
    except Exception:
        return 'unchecked'
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


def damaged(path):
    return check(path) == 'damaged'


def _remove(path):
    os.remove(path)
    for suffix in ('-journal', '-wal', '-shm'):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


_FRESH_S = 2.0


def _stamp(path):
    try:
        st = os.stat(path)
        return [st.st_size, int(st.st_mtime)]
    except OSError:
        return None


def _settled(path):
    """The stamp, unless the file was written in the last two seconds: a
    whole-second time cannot tell such a write from the check itself."""
    try:
        if time.time() - os.stat(path).st_mtime < _FRESH_S:
            return None
    except OSError:
        return None
    return _stamp(path)


def _load(state_path):
    try:
        with open(state_path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state_path, data):
    try:
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except OSError:
        pass


def repair(folder=None, state_path=None):
    """Delete damaged POV caches; return the names removed."""
    folder = folder or xbmcvfs.translatePath(POV_DATA)
    state_path = state_path or xbmcvfs.translatePath(STATE)
    known = _load(state_path)
    seen = {}
    removed = []
    for name in CACHE_DBS:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        stamp = _stamp(path)
        if stamp is not None and known.get(name) == stamp:
            seen[name] = stamp
            continue
        verdict = check(path)
        if verdict == 'ok':
            # Recorded only after a real 'ok', and only if the file did not
            # change while it was being read.
            after = _settled(path)
            if after is not None and after == stamp:
                seen[name] = after
            continue
        if verdict != 'damaged':
            continue
        try:
            _remove(path)
            removed.append(name)
        except OSError as exc:
            logging.log('[POV caches] {0} is damaged and could not be removed: {1}'
                        .format(name, exc), level=xbmc.LOGWARNING)
    if seen != known:
        _save(state_path, seen)
    return removed


def run_at_startup():
    started = time.time()
    removed = repair()
    if removed:
        logging.log('[POV caches] damaged and removed: {0} -- POV rebuilds them'
                    .format(', '.join(removed)), level=xbmc.LOGWARNING)
        # POV creates missing databases when its own service starts; this one
        # may already have started, so ask it now as well.
        xbmc.executebuiltin('RunPlugin(plugin://plugin.video.pov/?mode=clean_databases)')
    logging.log('[POV caches] checked in {0:.0f} ms'.format((time.time() - started) * 1000),
                level=xbmc.LOGINFO)
    return removed
