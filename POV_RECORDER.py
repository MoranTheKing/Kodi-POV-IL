#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POV live RECORDER (read only).

Earlier one-shot captures kept firing at the wrong moment. This records a
timeline: it snapshots Kodi every few seconds for ~100s while YOU navigate
naturally, and grabs a FULL dump the instant it sees (a) real search
results, and (b) the genre menu. One run captures both the missing-poster
and the genre-icon situations, with the live artwork each item actually
has. Read only -- changes/deletes nothing.

>>> HOW TO RUN:
  1. Kodi web server on (Settings > Services > Control > HTTP, port 8080).
  2. Start this script:
        Windows:  py POV_RECORDER.py
        Mac:      python3 POV_RECORDER.py
  3. While it runs (it prints a ticking timeline), do this in Kodi:
        - open Search, type  mario , open the "סרטים" category, wait ~3s
        - then open "סרטים לפי ז׳אנר" (a genre menu), wait ~3s
     Order doesn't matter; just visit both within ~100 seconds.
  It stops early once it has captured both. Otherwise it stops at the
  timeout and writes whatever it saw.

If you set a web password/port, edit the four values below.
Writes POV_RECORDER.txt next to the script. Send it back.
"""

import json
import os
import sys
import time
import base64
import urllib.request
import urllib.error

# ---- EDIT IF NEEDED (defaults = standard local Kodi) ----
HOST = "localhost"
PORT = 8080
USERNAME = "kodi"   # set "" if you do NOT require authentication
PASSWORD = ""       # your Kodi web password, if any
# ----------------------------------------------------------

URL = "http://{0}:{1}/jsonrpc".format(HOST, PORT)
RECORD_SECONDS = 100
TICK = 2.5

ART_KEYS = ["Art(poster)", "Art(tvshow.poster)", "Art(season.poster)",
            "Icon", "Art(thumb)", "Art(fanart)"]


def rpc(method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    if USERNAME:
        tok = base64.b64encode(
            ("%s:%s" % (USERNAME, PASSWORD)).encode("utf-8")).decode()
        req.add_header("Authorization", "Basic " + tok)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def labels(ls):
    res = rpc("XBMC.GetInfoLabels", {"labels": ls})
    return res.get("result", {}) if isinstance(res, dict) else {}


def booleans(bs):
    res = rpc("XBMC.GetInfoBooleans", {"booleans": bs})
    return res.get("result", {}) if isinstance(res, dict) else {}


def dump_container(w, cid, label):
    head = labels(["Container(%d).NumItems" % cid,
                   "Container(%d).IsUpdating" % cid])
    num = head.get("Container(%d).NumItems" % cid, "")
    upd = head.get("Container(%d).IsUpdating" % cid, "")
    w("")
    w("  --- container %d  %s  (NumItems=%s IsUpdating=%s) ---"
      % (cid, label, num, upd))
    try:
        n = int(num)
    except Exception:
        n = 0
    if n == 0:
        w("    (empty)")
        return
    for i in range(1, min(n, 6) + 1):
        ls = ["Container(%d).ListItem(%d).Label" % (cid, i)]
        for ak in ART_KEYS:
            ls.append("Container(%d).ListItem(%d).%s" % (cid, i, ak))
        d = labels(ls)
        lab = d.get("Container(%d).ListItem(%d).Label" % (cid, i), "")
        w("    [%d] %s" % (i, lab))
        anyart = False
        for ak in ART_KEYS:
            v = d.get("Container(%d).ListItem(%d).%s" % (cid, i, ak), "")
            if v:
                anyart = True
                sv = v if len(v) <= 95 else v[:95] + "..."
                w("          %-20s = %s" % (ak, sv))
        if not anyart:
            w("          (NO ART OF ANY KIND on this item)")


def full_search_dump(w, when):
    w("")
    w("=" * 70)
    w("FULL SEARCH DUMP  (t=%ss)" % when)
    w("=" * 70)
    ctx = labels(["System.CurrentWindow",
                  "Window(Home).Property(TMDbHelper.WidgetContainer)",
                  "Container(601).ListItem.Property(guid)"])
    for k, v in ctx.items():
        w("  %-50s = %s" % (k, v))
    for cid in (501, 502, 503):
        dump_container(w, cid, {501: "DISCOVER", 502: "row1",
                                503: "row2"}[cid])


def full_genre_dump(w, when, cid):
    w("")
    w("=" * 70)
    w("FULL GENRE DUMP  (t=%ss, container %d)" % (when, cid))
    w("=" * 70)
    ctx = labels(["System.CurrentWindow", "Container.Content",
                  "Container.FolderPath"])
    for k, v in ctx.items():
        sv = v if len(v) <= 110 else v[:110] + "..."
        w("  %-50s = %s" % (k, sv))
    dump_container(w, cid, "GENRES")


def first_item_art(cid):
    """Return (label, poster, icon) for ListItem(1) of a container."""
    d = labels(["Container(%d).ListItem(1).Label" % cid,
                "Container(%d).ListItem(1).Art(poster)" % cid,
                "Container(%d).ListItem(1).Icon" % cid])
    return (d.get("Container(%d).ListItem(1).Label" % cid, ""),
            d.get("Container(%d).ListItem(1).Art(poster)" % cid, ""),
            d.get("Container(%d).ListItem(1).Icon" % cid, ""))


def main():
    out = []

    def w(s=""):
        out.append(s)

    print("POV RECORDER -- connecting to " + URL)
    try:
        rpc("JSONRPC.Ping", {})
    except urllib.error.HTTPError as e:
        msg = "HTTP ERROR %s %s -- check web server/port/user/pass." % (
            e.code, e.reason)
        print(msg)
        w(msg)
        save(out)
        return
    except Exception as e:
        msg = "CANNOT REACH KODI: %s -- is Kodi running w/ web server?" % e
        print(msg)
        w(msg)
        save(out)
        return

    w("=" * 70)
    w("POV LIVE RECORDER  (read only)")
    w("Endpoint: " + URL)
    w("=" * 70)
    w("")
    w("TIMELINE (one line per tick):")
    w("  cols: t | win=<current window> | s1105=<search visible> | "
      "NumItems[501/502/503/512] | focusedItem(poster?,icon)")
    print("Recording ~%ds. NOW in Kodi: search 'mario' -> open 'סרטים', "
          "then open a genre menu." % RECORD_SECONDS)

    start = time.time()
    did_search = False
    did_genre = False
    while time.time() - start < RECORD_SECONDS:
        t = int(time.time() - start)
        try:
            b = booleans(["Window.IsVisible(1105)", "Window.IsActive(1105)"])
            s1105 = bool(b.get("Window.IsVisible(1105)") or
                         b.get("Window.IsActive(1105)"))
            base = labels([
                "System.CurrentWindow",
                "Container.Content",
                "Container(501).NumItems", "Container(502).NumItems",
                "Container(503).NumItems", "Container(512).NumItems",
                "Container.ListItem.Label",
                "Container.ListItem.Art(poster)",
                "Container.ListItem.Icon",
            ])
        except Exception as e:
            w("  t=%-3s (rpc error: %s)" % (t, e))
            time.sleep(TICK)
            continue

        win = base.get("System.CurrentWindow", "")
        content = base.get("Container.Content", "")
        n501 = base.get("Container(501).NumItems", "")
        n502 = base.get("Container(502).NumItems", "")
        n503 = base.get("Container(503).NumItems", "")
        n512 = base.get("Container(512).NumItems", "")
        flab = base.get("Container.ListItem.Label", "")
        fpost = base.get("Container.ListItem.Art(poster)", "")
        ficon = base.get("Container.ListItem.Icon", "")
        has_post = "Y" if fpost else "-"
        ic = ficon if len(ficon) <= 40 else "..." + ficon[-37:]
        w("  t=%-3s win=%-10s s1105=%-5s N[%s/%s/%s/%s] focus='%s' "
          "poster=%s icon=%s" % (t, win[:10], s1105, n501, n502, n503,
                                 n512, flab[:18], has_post, ic))

        def as_int(x):
            try:
                return int(x)
            except Exception:
                return 0

        # full search dump once: search window visible AND a result row
        # actually has items
        if (not did_search and s1105 and
                (as_int(n502) > 0 or as_int(n503) > 0)):
            full_search_dump(w, t)
            did_search = True

        # genre detection: content reports genres, OR the focused item's
        # icon/poster points into a /genres/ folder (unique to POV genres),
        # OR container 512 holds such items.
        genre_cid = None
        if content == "genres":
            genre_cid = None  # use focused dump below
        if ("/genres/" in fpost) or ("/genres/" in ficon) or \
                ("\\genres\\" in fpost) or ("\\genres\\" in ficon):
            genre_cid = "focus"
        if not did_genre and as_int(n512) > 0:
            _, gp, gi = first_item_art(512)
            if "/genres/" in gp or "/genres/" in gi or \
                    "\\genres\\" in gp or "\\genres\\" in gi:
                genre_cid = 512
        if not did_genre and genre_cid is not None:
            if genre_cid == "focus" or genre_cid is None:
                # dump the focused container
                head = labels(["Container.NumItems"])
                n = head.get("Container.NumItems", "0")
                w("")
                w("=" * 70)
                w("FULL GENRE DUMP (t=%ss, FOCUSED container, NumItems=%s)"
                  % (t, n))
                w("=" * 70)
                ctx = labels(["System.CurrentWindow", "Container.Content",
                              "Container.FolderPath"])
                for k, v in ctx.items():
                    sv = v if len(v) <= 110 else v[:110] + "..."
                    w("  %-50s = %s" % (k, sv))
                try:
                    nn = int(n)
                except Exception:
                    nn = 0
                for i in range(1, min(nn, 8) + 1):
                    ls = ["Container.ListItem(%d).Label" % i]
                    for ak in ART_KEYS:
                        ls.append("Container.ListItem(%d).%s" % (i, ak))
                    d = labels(ls)
                    lab = d.get("Container.ListItem(%d).Label" % i, "")
                    w("    [%d] %s" % (i, lab))
                    for ak in ART_KEYS:
                        v = d.get("Container.ListItem(%d).%s" % (i, ak), "")
                        if v:
                            sv = v if len(v) <= 95 else v[:95] + "..."
                            w("          %-20s = %s" % (ak, sv))
            else:
                full_genre_dump(w, t, genre_cid)
            did_genre = True

        if did_search and did_genre:
            w("")
            w(">>> captured both search and genre -- stopping early.")
            break
        time.sleep(TICK)

    if not did_search:
        w("")
        w("!! never saw loaded search results (1105 visible + 502/503>0).")
    if not did_genre:
        w("")
        w("!! never saw a genre menu (focused item icon under /genres/).")

    # always include the on-disk genre check
    disk_genre_check(w)

    w("")
    w("=" * 70)
    w("DONE. Nothing changed. Send POV_RECORDER.txt back.")
    w("=" * 70)
    save(out)


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
        if c and os.path.isdir(os.path.join(c, "addons")):
            return c
    return None


def disk_genre_check(w):
    w("")
    w("=" * 70)
    w("GENRE ICONS -- on-disk check")
    w("=" * 70)
    kodi = find_kodi_home(sys.argv)
    w("Kodi home: " + str(kodi))
    if not kodi:
        w("(not found -- pass the Kodi folder as an argument)")
        return
    pov = "plugin.video.pov"
    nav = os.path.join(kodi, "addons", pov, "resources", "lib", "menus",
                       "navigator.py")
    w("navigator.py exists: " + str(os.path.isfile(nav)))
    if os.path.isfile(nav):
        try:
            with open(nav, "r", encoding="utf-8", errors="replace") as f:
                navtxt = f.read()
            w("  genre-icons patch marker present: " +
              str("AI_SUBS_POV_GENRE_ICONS" in navtxt))
            w("  still hardcodes 'genres.png' in a genre loop: " +
              str("'genres.png', list_name=list_name" in navtxt))
        except Exception as e:
            w("  (read error: %s)" % e)
    gdir = os.path.join(kodi, "addons", pov, "resources", "skins",
                        "Default", "media", "genres")
    w("genre media dir exists: " + str(os.path.isdir(gdir)))
    if os.path.isdir(gdir):
        pngs = [f for f in os.listdir(gdir) if f.lower().endswith(".png")]
        w("  PNG count: %d" % len(pngs))


def save(out):
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "POV_RECORDER.txt")
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        print("Report written to: " + p)
    except Exception as e:
        print("Could not write report: %s" % e)


if __name__ == "__main__":
    main()
