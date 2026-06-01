#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POV watched / in-progress diagnostic (READ ONLY -- changes nothing).

Two AF3 bugs to pin down (both work in FENtastic):
  BUG 1: "Clear Progress" / "Mark watched" do nothing -- movie stays in
         "Continue Watching".
  BUG 2: "Continue Watching" (in-progress movies) shows only ONE movie;
         a new one REPLACES it instead of adding.

This reads two things, both read-only:
  A) POV's progress DB (watched.db -> table 'progress'): how many
     in-progress MOVIES actually exist on disk, and their ids/titles/
     last_played. This tells us if POV's data is correct (many rows) while
     AF3 shows only 1 (-> skin/widget bug) -- or if the DB itself holds 1.
  B) (optional, if Kodi is running with the web server) the LIVE
     in-progress widget container over JSON-RPC: how many items the home
     widget actually renders, so we see skin-side vs data-side.

It copies the DB to a temp file first (never locks the real one).

  Windows:  py POV_WATCHED_DIAGNOSTIC.py
  Mac:      python3 POV_WATCHED_DIAGNOSTIC.py
If Kodi isn't auto-found:  py POV_WATCHED_DIAGNOSTIC.py "C:\\...\\Kodi"
Writes POV_WATCHED_DIAGNOSTIC.txt next to the script. Send it back.
"""

import os
import sys
import shutil
import sqlite3
import tempfile
import json
import base64
import urllib.request
import urllib.error

POV = "plugin.video.pov"

# Optional live container read (only if Kodi running w/ web server):
HOST, PORT, USERNAME, PASSWORD = "localhost", 8080, "kodi", ""


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


def rpc(url, method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    if USERNAME:
        tok = base64.b64encode(
            ("%s:%s" % (USERNAME, PASSWORD)).encode()).decode()
        req.add_header("Authorization", "Basic " + tok)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main():
    out = []

    def w(s=""):
        out.append(s)

    kodi = find_kodi_home(sys.argv)
    w("=" * 70)
    w("POV WATCHED / IN-PROGRESS DIAGNOSTIC (read only)")
    w("Kodi home: " + str(kodi))
    w("=" * 70)
    if not kodi:
        w("Kodi not found -- re-run with the path.")
        save(out)
        return

    # ---- A) the progress DB ----
    db = os.path.join(kodi, "userdata", "addon_data", POV, "watched.db")
    w("")
    w("-" * 70)
    w("### A) POV progress DB  (watched.db -> table 'progress')")
    w("-" * 70)
    w("path: " + db)
    w("exists: " + str(os.path.isfile(db)))
    if os.path.isfile(db):
        tmp = os.path.join(tempfile.gettempdir(), "_pov_watched_copy.db")
        try:
            shutil.copy2(db, tmp)
            con = sqlite3.connect(tmp)
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            # tables
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r["name"] for r in cur.fetchall()]
            w("tables: " + ", ".join(tables))
            if "progress" in tables:
                cur.execute("PRAGMA table_info(progress)")
                cols = [r["name"] for r in cur.fetchall()]
                w("progress columns: " + ", ".join(cols))
                # count by db_type
                try:
                    cur.execute("SELECT db_type, COUNT(*) AS n FROM progress "
                                "GROUP BY db_type")
                    w("")
                    w("in-progress counts by type:")
                    for r in cur.fetchall():
                        w("   %-10s = %s" % (r["db_type"], r["n"]))
                except Exception as e:
                    w("count failed: %s" % e)
                # list the movie rows
                try:
                    cur.execute("SELECT * FROM progress WHERE db_type='movie' "
                                "ORDER BY last_played DESC")
                    rows = cur.fetchall()
                    w("")
                    w(">>> in-progress MOVIE rows: %d" % len(rows))
                    for i, r in enumerate(rows[:25], 1):
                        d = dict(r)
                        title = d.get("title") or d.get("name") or "?"
                        mid = d.get("media_id") or d.get("tmdb_id") or "?"
                        lp = d.get("last_played", "")
                        w("   [%d] id=%s  '%s'  last_played=%s"
                          % (i, mid, str(title)[:40], lp))
                    w("")
                    if len(rows) > 1:
                        w(">>> DB holds MULTIPLE in-progress movies. If AF3")
                        w("    shows only 1, the bug is skin/widget-side.")
                    elif len(rows) == 1:
                        w(">>> DB holds only 1. So 'replaces instead of adds'")
                        w("    means the WRITE side overwrites -- but POV's")
                        w("    write is keyed per id, so check if multiple")
                        w("    movies were actually started+left in progress.")
                except Exception as e:
                    w("movie rows failed: %s" % e)
            con.close()
            os.remove(tmp)
        except Exception as e:
            w("DB read failed: %s" % e)

    # ---- B) live widget container (optional) ----
    w("")
    w("-" * 70)
    w("### B) LIVE in-progress widget (optional -- needs Kodi web server)")
    w("-" * 70)
    url = "http://%s:%s/jsonrpc" % (HOST, PORT)
    try:
        rpc(url, "JSONRPC.Ping", {})
        # find the home widget container showing the in-progress list.
        # We don't know its id; scan home containers 9000-9020 + common ones.
        res = rpc(url, "XBMC.GetInfoLabels",
                  {"labels": ["System.CurrentWindow"]})
        w("connected. CurrentWindow=%s" %
          res.get("result", {}).get("System.CurrentWindow", ""))
        w("(open the HOME screen with the 'Continue Watching' row visible)")
        found = []
        for cid in list(range(9000, 9031)) + list(range(3000, 3015)):
            r = rpc(url, "XBMC.GetInfoLabels",
                    {"labels": ["Container(%d).NumItems" % cid,
                                "Container(%d).ListItem.Label" % cid]})
            d = r.get("result", {})
            num = d.get("Container(%d).NumItems" % cid, "")
            lab = d.get("Container(%d).ListItem.Label" % cid, "")
            if num not in ("", "0"):
                w("   Container(%d) NumItems=%s firstLabel=%s"
                  % (cid, num, lab))
                found.append(cid)
        if not found:
            w("   (no populated containers found in the scanned range --")
            w("    that's ok; the DB section above is the key evidence)")
    except urllib.error.HTTPError as e:
        w("web server present but auth failed (%s) -- skip (DB is enough)"
          % e.code)
    except Exception:
        w("Kodi web server not reachable -- skipped (the DB section above")
        w("is the key evidence; enable the web server if you want this too)")

    w("")
    w("=" * 70)
    w("DONE. Nothing changed. Send POV_WATCHED_DIAGNOSTIC.txt back.")
    w("=" * 70)
    save(out)


def save(out):
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "POV_WATCHED_DIAGNOSTIC.txt")
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        print("Report written to: " + p)
    except Exception as e:
        print("Could not write report: %s" % e)


if __name__ == "__main__":
    main()
