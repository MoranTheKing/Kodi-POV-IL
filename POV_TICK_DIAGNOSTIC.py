#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POV watched-tick diagnostic (READ ONLY -- changes nothing, sends nothing).

THE REPORT: a watched tick on films the user has never watched -- "in general
it does it on everything, films included" -- seen entering from the home
screen widgets.

WHAT WE ALREADY RULED OUT. Not the skin. skin.fentastic draws its tick from
ListItem.Overlay / ListItem.Playcount, and it ships no OverlayUnwatched.png at
all, so an UNWATCHED item has nothing to draw -- the tick can only appear when
something upstream says playcount 1 / overlay 5. That is data, and this script
reads exactly that data.

WHERE THE DATA COMES FROM. POV keeps three separate watched databases and one
setting chooses between them:

    watched_indicators = 0  ->  watched.db       (POV's own)
                       = 1  ->  traktcache4.db   (Trakt)
                       = 2  ->  mdblcache.db     (MDBList)

Connecting MDBList -- which is now how most people connect, through Account
Manager -- switches that setting to 2, so the ticks stop coming from POV's own
records and start coming from whatever the MDBList sync wrote. If that sync
stored the WATCHLIST (films you mean to watch) rather than the WATCHED list,
every film you ever added shows a tick and the report is exactly what we see.
This script settles it by counting and listing the rows, and by looking up the
handful of films from the screenshot by id.

NO SECRETS ARE PRINTED. Tokens are reported as present/absent only, never
their value, so the output is safe to send back as-is.

  Windows:  py POV_TICK_DIAGNOSTIC.py
  Mac:      python3 POV_TICK_DIAGNOSTIC.py
If Kodi is not found automatically:  py POV_TICK_DIAGNOSTIC.py "C:\\...\\Kodi"
Writes POV_TICK_DIAGNOSTIC.txt next to the script. Send that file back.
"""

import os
import re
import shutil
import sqlite3
import sys
import tempfile

POV = "plugin.video.pov"

DATABASES = {
    "0": ("POV's own", "watched.db"),
    "1": ("Trakt", "traktcache4.db"),
    "2": ("MDBList", "mdblcache.db"),
}

# A few films from the reported screen, so we can ask the database about
# them by name instead of hoping they show up in the first rows.
KNOWN = {
    "557": "Spider-Man (2002)",
    "634492": "Madame Web",
    "1061474": "Superman / Supergirl",
    "912649": "Venom: The Last Dance",
}


def find_kodi_home(argv):
    if len(argv) > 1 and os.path.isdir(argv[1]):
        return argv[1]
    cands = []
    ap = os.environ.get("APPDATA")
    if ap:
        cands.append(os.path.join(ap, "Kodi"))
    home = os.path.expanduser("~")
    cands += [os.path.join(home, ".kodi"),
              os.path.join(home, "Library", "Application Support", "Kodi"),
              os.path.join(home, ".var", "app", "tv.kodi.Kodi", "data",
                           ".kodi"),
              "/storage/.kodi"]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "userdata")):
            return c
    return None


def read_setting(settings_xml, setting_id):
    """POV's settings.xml, read from disk.

    Deliberately the FILE and not Kodi's in-memory copy: Account Manager
    writes this file directly, so the two can disagree, and the file is what
    POV itself reloads."""
    try:
        with open(settings_xml, "r", encoding="utf-8") as handle:
            content = handle.read()
    except Exception:
        return None
    content = re.sub(r"<!--.*?-->", "", content, flags=re.S)
    quoted = re.escape(setting_id)
    m = re.search(r'<setting[^>]*\bid="%s"[^>]*>([^<]*)</setting>' % quoted,
                  content)
    if m:
        return m.group(1).strip()
    for pat in (r'<setting[^>]*\bid="%s"[^>]*\bvalue="([^"]*)"' % quoted,
                r'<setting[^>]*\bvalue="([^"]*)"[^>]*\bid="%s"' % quoted):
        m = re.search(pat, content)
        if m:
            return m.group(1).strip()
    return ""


def open_copy(path):
    """Never touch the live file: sqlite locks, and Kodi may be running."""
    tmp = os.path.join(tempfile.gettempdir(),
                       "_pov_tick_" + os.path.basename(path))
    shutil.copy2(path, tmp)
    con = sqlite3.connect(tmp)
    con.row_factory = sqlite3.Row
    return con


def describe_db(w, data_dir, filename, label, verbose):
    path = os.path.join(data_dir, filename)
    w("")
    w("--- %s  (%s)" % (filename, label))
    if not os.path.isfile(path):
        w("    not on disk")
        return
    w("    size: %d bytes" % os.path.getsize(path))
    try:
        con = open_copy(path)
    except Exception as err:
        w("    could not read: %s" % err)
        return
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r["name"] for r in cur.fetchall()]
        w("    tables: " + (", ".join(tables) or "(none)"))
        if "watched_status" not in tables:
            w("    no watched_status table -- nothing marks a tick from here")
            return
        cur.execute("SELECT db_type, COUNT(*) AS n FROM watched_status "
                    "GROUP BY db_type")
        counts = {r["db_type"]: r["n"] for r in cur.fetchall()}
        w("    rows by type: " + (", ".join(
            "%s=%d" % (k, v) for k, v in sorted(counts.items())) or "(empty)"))
        movies = counts.get("movie", 0)
        if movies:
            w("    -> %d films are marked WATCHED from this database" % movies)
        if verbose:
            cur.execute("SELECT media_id, title, last_played FROM "
                        "watched_status WHERE db_type = 'movie' "
                        "ORDER BY last_played DESC LIMIT 40")
            rows = cur.fetchall()
            if rows:
                w("")
                w("    the 40 most recent films it calls watched:")
                for r in rows:
                    w("      %-10s %-45s %s" % (
                        r["media_id"], (r["title"] or "")[:45],
                        r["last_played"]))
            w("")
            w("    films from the screenshot, looked up by id:")
            for tmdb_id, name in KNOWN.items():
                cur.execute("SELECT title, last_played FROM watched_status "
                            "WHERE db_type = 'movie' AND media_id = ?",
                            (tmdb_id,))
                hit = cur.fetchone()
                w("      %-28s %s" % (
                    name,
                    "MARKED WATCHED (last_played %s)" % hit["last_played"]
                    if hit else "not marked"))
    except Exception as err:
        w("    failed while reading: %s" % err)
    finally:
        try:
            con.close()
        except Exception:
            pass


def main():
    out = []

    def w(s=""):
        out.append(s)

    kodi = find_kodi_home(sys.argv)
    w("=" * 72)
    w("POV WATCHED-TICK DIAGNOSTIC (read only)")
    w("Kodi home: %s" % kodi)
    w("=" * 72)
    if not kodi:
        w("Kodi was not found. Re-run with the path to the Kodi folder, e.g.")
        w('   py POV_TICK_DIAGNOSTIC.py "C:\\Users\\me\\AppData\\Roaming\\Kodi"')
        save(out)
        return

    data_dir = os.path.join(kodi, "userdata", "addon_data", POV)
    settings_xml = os.path.join(data_dir, "settings.xml")
    w("")
    w("### 1) which source POV is asking")
    w("-" * 72)
    w("settings.xml: %s" % settings_xml)
    w("exists: %s" % os.path.isfile(settings_xml))

    indicator = read_setting(settings_xml, "watched_indicators")
    w("")
    w("watched_indicators = %r  ->  %s" % (
        indicator, DATABASES.get(indicator, ("unknown", "?"))[0]))
    for key in ("mdbl_indicators_active", "trakt.indicators_active"):
        w("%-24s = %r" % (key, read_setting(settings_xml, key)))
    for key in ("mdblist.token", "trakt.token"):
        value = read_setting(settings_xml, key)
        w("%-24s : %s" % (
            key,
            "not readable" if value is None
            else ("present" if value else "empty")))

    w("")
    w("### 2) what each database actually holds")
    w("-" * 72)
    w("The one selected above is the one drawing the ticks; the others are")
    w("printed for comparison, so we can see whether the wrong one is chosen.")
    for value, (label, filename) in sorted(DATABASES.items()):
        describe_db(w, data_dir, filename, label, verbose=(value == indicator))

    w("")
    w("### 3) how to read this")
    w("-" * 72)
    w("If the selected database lists hundreds of films the user never")
    w("watched, the sync that filled it is the bug and the skin is innocent.")
    w("If it lists only a handful that really were watched, the tick is")
    w("coming from somewhere else and the next place to look is the widget.")
    save(out)


def save(lines):
    text = "\n".join(lines)
    print(text)
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "POV_TICK_DIAGNOSTIC.txt")
    try:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print("\nwritten to: " + target)
    except Exception as err:
        print("\ncould not write the file: %s" % err)


if __name__ == "__main__":
    main()
