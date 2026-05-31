#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POV texture-cache diagnostic (READ ONLY -- deletes nothing).

We proved POV returns Art(poster) for search (21/21) and that the search
rows use the SAME skin render path as the home/Discover rows that DO show
posters. So the suspect is Kodi's texture cache: blank/failed cached
entries for the TMDB poster URLs that keep getting reused.

This script OPENS (read-only) Kodi's texture cache database
(Textures13.db) and reports, for the poster URLs we expect:
  * whether each poster URL is in the cache,
  * the cached file it points to,
  * whether that cached file actually exists on disk and its size,
  * how many times it failed to load.
It also samples the most-recently-cached textures so we can see if fresh
posters are landing as 0-byte / broken.

It does NOT modify or delete anything. Safe to run with Kodi closed
(recommended) or open.

HOW TO RUN:
  Windows:  py POV_CACHE_DIAGNOSTIC.py
  Mac:      python3 POV_CACHE_DIAGNOSTIC.py
  Linux:    python3 POV_CACHE_DIAGNOSTIC.py
If it can't find Kodi, pass the folder:
  py POV_CACHE_DIAGNOSTIC.py "C:\\Users\\<you>\\AppData\\Roaming\\Kodi"

Writes POV_CACHE_DIAGNOSTIC.txt next to the script. Send me that file.
"""

import os
import sys
import shutil
import sqlite3
import tempfile

SKIN = 'skin.arctic.fuse.3'


def find_kodi_home(argv):
    if len(argv) > 1 and os.path.isdir(argv[1]):
        return argv[1]
    cands = []
    ap = os.environ.get('APPDATA')
    if ap:
        cands.append(os.path.join(ap, 'Kodi'))
    home = os.path.expanduser('~')
    cands += [
        os.path.join(home, '.kodi'),
        os.path.join(home, 'Library', 'Application Support', 'Kodi'),
        os.path.join(home, '.var', 'app', 'tv.kodi.Kodi', 'data', '.kodi'),
        '/storage/.kodi',
    ]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, 'userdata')):
            return c
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return None


def find_textures_db(kodi):
    db_dir = os.path.join(kodi, 'userdata', 'Database')
    if not os.path.isdir(db_dir):
        return None
    # pick the highest TexturesNN.db
    best = None
    best_n = -1
    for name in os.listdir(db_dir):
        low = name.lower()
        if low.startswith('textures') and low.endswith('.db'):
            digits = ''.join(ch for ch in name if ch.isdigit())
            n = int(digits) if digits else 0
            if n > best_n:
                best_n = n
                best = os.path.join(db_dir, name)
    return best


def main():
    out = []

    def w(s=''):
        out.append(s)

    kodi = find_kodi_home(sys.argv)
    w('=' * 70)
    w('POV TEXTURE-CACHE DIAGNOSTIC (read only)')
    w('Kodi home: ' + str(kodi))
    w('=' * 70)
    if not kodi:
        w('Could not locate Kodi. Re-run with the path, e.g.:')
        w('  py POV_CACHE_DIAGNOSTIC.py "C:\\Users\\<you>\\AppData\\Roaming\\Kodi"')
        save(out)
        return

    db = find_textures_db(kodi)
    w('Textures DB: ' + str(db))
    thumbs = os.path.join(kodi, 'userdata', 'Thumbnails')
    w('Thumbnails folder exists: ' + str(os.path.isdir(thumbs)))
    if not db or not os.path.isfile(db):
        w('No Textures DB found -- cannot inspect the cache.')
        save(out)
        return

    # Copy the DB to a temp file so we never lock/touch the real one,
    # even if Kodi is running.
    tmpdb = os.path.join(tempfile.gettempdir(), '_pov_textures_copy.db')
    try:
        shutil.copy2(db, tmpdb)
    except Exception as e:
        w('Could not copy DB (is it locked?): %s' % e)
        w('Close Kodi and re-run.')
        save(out)
        return

    try:
        con = sqlite3.connect(tmpdb)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
    except Exception as e:
        w('Could not open DB copy: %s' % e)
        save(out)
        return

    # schema
    w('')
    w('-' * 70)
    w('### texture table columns')
    w('-' * 70)
    cols = []
    try:
        cur.execute('PRAGMA table_info(texture)')
        for r in cur.fetchall():
            cols.append(r['name'])
        w(', '.join(cols))
    except Exception as e:
        w('schema read failed: %s' % e)

    has_usecount = 'usecount' in cols
    has_lasthashcheck = 'lasthashcheck' in cols

    # totals
    w('')
    w('-' * 70)
    w('### cache totals')
    w('-' * 70)
    try:
        cur.execute('SELECT COUNT(*) AS n FROM texture')
        total = cur.fetchone()['n']
        w('total cached textures: %d' % total)
        cur.execute("SELECT COUNT(*) AS n FROM texture WHERE url LIKE '%image.tmdb.org%'")
        w('TMDB-image textures: %d' % cur.fetchone()['n'])
    except Exception as e:
        w('totals failed: %s' % e)

    # How many TMDB poster entries map to a missing/0-byte cached file
    w('')
    w('-' * 70)
    w('### TMDB poster cache health (sample up to 40)')
    w('-' * 70)
    try:
        # Kodi stores the image:// URL URL-encoded, so '/' appears as %2f.
        # Match both encoded and plain forms of the common poster widths.
        cur.execute(
            "SELECT url, cachedurl FROM texture "
            "WHERE url LIKE '%image.tmdb.org%' "
            "AND (url LIKE '%w780%' OR url LIKE '%w500%' "
            "     OR url LIKE '%w342%' OR url LIKE '%poster%') "
            "LIMIT 40")
        rows = cur.fetchall()
        if not rows:
            w('(no TMDB poster-ish textures cached yet)')
        missing = 0
        zero = 0
        ok = 0
        for r in rows:
            cached = r['cachedurl'] or ''
            fp = os.path.join(thumbs, cached.replace('/', os.sep)) if cached else ''
            exists = os.path.isfile(fp) if fp else False
            size = os.path.getsize(fp) if exists else -1
            if not exists:
                missing += 1
            elif size == 0:
                zero += 1
            else:
                ok += 1
        w('sampled %d poster textures: ok(>0 bytes)=%d, MISSING file=%d, '
          'ZERO bytes=%d' % (len(rows), ok, missing, zero))
        # show a few concrete examples
        w('')
        w('examples:')
        for r in rows[:8]:
            cached = r['cachedurl'] or ''
            fp = os.path.join(thumbs, cached.replace('/', os.sep)) if cached else ''
            exists = os.path.isfile(fp) if fp else False
            size = os.path.getsize(fp) if exists else -1
            u = r['url']
            if len(u) > 80:
                u = u[:80] + '...'
            w('  url=%s' % u)
            w('      cached=%s exists=%s size=%s' % (cached, exists, size))
    except Exception as e:
        w('poster health failed: %s' % e)

    # Recently added textures (are fresh ones landing broken?)
    w('')
    w('-' * 70)
    w('### most recently cached textures (last 15)')
    w('-' * 70)
    order_col = 'lasthashcheck' if has_lasthashcheck else 'id'
    try:
        cur.execute(
            "SELECT url, cachedurl FROM texture ORDER BY %s DESC LIMIT 15"
            % order_col)
        for r in cur.fetchall():
            cached = r['cachedurl'] or ''
            fp = os.path.join(thumbs, cached.replace('/', os.sep)) if cached else ''
            exists = os.path.isfile(fp) if fp else False
            size = os.path.getsize(fp) if exists else -1
            u = r['url']
            if len(u) > 78:
                u = u[:78] + '...'
            w('  size=%-8s exists=%-5s %s' % (size, exists, u))
    except Exception as e:
        w('recent list failed: %s' % e)

    try:
        con.close()
    except Exception:
        pass
    try:
        os.remove(tmpdb)
    except Exception:
        pass

    w('')
    w('=' * 70)
    w('DONE. Nothing was modified or deleted. Send POV_CACHE_DIAGNOSTIC.txt.')
    w('=' * 70)
    save(out)


def save(out):
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, 'POV_CACHE_DIAGNOSTIC.txt')
    try:
        with open(p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out))
        print('Report written to: ' + p)
    except Exception as e:
        print('Could not write report: %s' % e)
        print('\n'.join(out))


if __name__ == '__main__':
    main()
