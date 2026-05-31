#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POV LIVE container diagnostic v2 -- AUTO-CAPTURE (read only).

Earlier captures landed on the Home screen, so the "search" containers were
actually home widgets. This version removes the timing problem: you START
the script, it then WAITS and polls Kodi until the SEARCH window (1105) is
the active window, and only THEN snapshots the search containers. It also
snapshots the genre menu when you open it.

It changes/deletes nothing -- pure read over JSON-RPC.

>>> HOW TO RUN (order no longer matters much):
  1. Make sure Kodi's web server is on (Settings > Services > Control >
     "Allow remote control via HTTP", port 8080).
  2. Start this script:
        Windows:  py POV_LIVE_DIAGNOSTIC.py
        Mac:      python3 POV_LIVE_DIAGNOSTIC.py
  3. It will say "waiting...". NOW go to Kodi:
        - open Search, type  mario , and open the "סרטים" category.
     The script auto-captures the search screen within ~1 second.
  4. (optional) It then waits again -- open "סרטים לפי ז׳אנר" (genres) so
     it can also capture the genre icons. Or just let it time out.

If you set a web password/port, edit the four values below.
Writes POV_LIVE_DIAGNOSTIC.txt next to the script. Send it back.
"""

import json
import os
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
WAIT_SECONDS = 120      # how long to wait for the search window
GENRE_WAIT = 45         # extra wait to also capture the genre screen


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


def get_labels(labels):
    res = rpc("XBMC.GetInfoLabels", {"labels": labels})
    return res.get("result", {}) if isinstance(res, dict) else {}


ART_KEYS = ["Art(poster)", "Art(tvshow.poster)", "Art(season.poster)",
            "Icon", "Art(thumb)", "Art(fanart)"]


def dump_container(w, cid, label):
    head = get_labels(["Container(%d).NumItems" % cid,
                       "Container(%d).IsUpdating" % cid])
    num = head.get("Container(%d).NumItems" % cid, "")
    upd = head.get("Container(%d).IsUpdating" % cid, "")
    w("")
    w("-" * 70)
    w("### container %d  %s" % (cid, label))
    w("-" * 70)
    w("  NumItems=%s  IsUpdating=%s" % (num, upd))
    try:
        n = int(num)
    except Exception:
        n = 0
    if n == 0:
        w("  (empty)")
        return
    for i in range(1, min(n, 6) + 1):
        labels = ["Container(%d).ListItem(%d).Label" % (cid, i)]
        for ak in ART_KEYS:
            labels.append("Container(%d).ListItem(%d).%s" % (cid, i, ak))
        d = get_labels(labels)
        lab = d.get("Container(%d).ListItem(%d).Label" % (cid, i), "")
        w("  [%d] %s" % (i, lab))
        anyart = False
        for ak in ART_KEYS:
            v = d.get("Container(%d).ListItem(%d).%s" % (cid, i, ak), "")
            if v:
                anyart = True
                sv = v if len(v) <= 95 else v[:95] + "..."
                w("        %-20s = %s" % (ak, sv))
        if not anyart:
            w("        (no art of any kind on this item!)")


def snapshot_search(w):
    w("")
    w("=" * 70)
    w("SEARCH WINDOW SNAPSHOT")
    w("=" * 70)
    ctx = get_labels([
        "System.CurrentWindow", "System.CurrentControl",
        "Window(Home).Property(TMDbHelper.WidgetContainer)",
        "Control.GetLabel(3000)",
        "Container(601).ListItem.Property(guid)",
    ])
    for k, v in ctx.items():
        w("  %-55s = %s" % (k, v))
    # scan
    w("")
    w("  container scan (NumItems):")
    for cid in list(range(501, 513)) + [601, 602]:
        d = get_labels(["Container(%d).NumItems" % cid])
        num = d.get("Container(%d).NumItems" % cid, "")
        if num not in ("", "0"):
            w("    Container(%d) = %s" % (cid, num))
    dump_container(w, 501, "DISCOVER (baseline)")
    dump_container(w, 502, "search row 1 (movies?)")
    dump_container(w, 503, "search row 2 (tv?)")


def snapshot_genres(w):
    w("")
    w("=" * 70)
    w("GENRE WINDOW SNAPSHOT")
    w("=" * 70)
    ctx = get_labels(["System.CurrentWindow", "Container.NumItems",
                      "Container.Content"])
    for k, v in ctx.items():
        w("  %-55s = %s" % (k, v))
    # the focused container varies; dump the main content container plus a scan
    w("")
    w("  container scan (NumItems):")
    found = []
    for cid in list(range(50, 70)) + list(range(500, 560)):
        d = get_labels(["Container(%d).NumItems" % cid])
        num = d.get("Container(%d).NumItems" % cid, "")
        if num not in ("", "0"):
            w("    Container(%d) = %s" % (cid, num))
            found.append(cid)
    # dump the current/focused container generically
    w("")
    w("  FOCUSED container items (Container.ListItem):")
    head = get_labels(["Container.NumItems"])
    num = head.get("Container.NumItems", "")
    try:
        n = int(num)
    except Exception:
        n = 0
    for i in range(1, min(n, 8) + 1):
        labels = ["Container.ListItem(%d).Label" % i]
        for ak in ART_KEYS:
            labels.append("Container.ListItem(%d).%s" % (i, ak))
        d = get_labels(labels)
        lab = d.get("Container.ListItem(%d).Label" % i, "")
        w("  [%d] %s" % (i, lab))
        for ak in ART_KEYS:
            v = d.get("Container.ListItem(%d).%s" % (i, ak), "")
            if v:
                sv = v if len(v) <= 95 else v[:95] + "..."
                w("        %-20s = %s" % (ak, sv))


def main():
    out = []

    def w(s=""):
        out.append(s)
        print(s)

    w("=" * 70)
    w("POV LIVE AUTO-CAPTURE (read only)")
    w("Endpoint: " + URL)
    w("=" * 70)

    try:
        rpc("JSONRPC.Ping", {})
    except urllib.error.HTTPError as e:
        w("HTTP ERROR: %s %s -- check web server/port/user/pass." %
          (e.code, e.reason))
        save(out)
        return
    except Exception as e:
        w("CANNOT REACH KODI: %s -- is Kodi running with web server on?" % e)
        save(out)
        return

    w("")
    w(">>> Connected. NOW in Kodi: open Search, type 'mario', open the")
    w(">>> 'סרטים' category. Waiting up to %d s for the search window..."
      % WAIT_SECONDS)

    deadline = time.time() + WAIT_SECONDS
    captured_search = False
    while time.time() < deadline:
        try:
            cw = get_labels(["System.CurrentWindow",
                             "Window.Property(xmlfile)"])
        except Exception:
            time.sleep(1)
            continue
        win = (cw.get("System.CurrentWindow", "") or "")
        xml = (cw.get("Window.Property(xmlfile)", "") or "")
        # search window is id 1105 -> xmlfile Custom_1105_Search.xml; the
        # localized name may be Hebrew, so match on the xml or the id label.
        if "1105" in xml or "Search" in xml or "Custom_1105" in xml:
            time.sleep(0.6)  # let items settle
            snapshot_search(w)
            captured_search = True
            break
        time.sleep(1)

    if not captured_search:
        w("")
        w("!! Did not detect the search window in time. Capturing whatever")
        w("   is on screen now as a fallback:")
        snapshot_search(w)

    # optional genre capture
    w("")
    w(">>> (optional) Now open 'סרטים לפי ז׳אנר' (genres). Waiting %d s..."
      % GENRE_WAIT)
    gdeadline = time.time() + GENRE_WAIT
    grabbed = False
    while time.time() < gdeadline:
        try:
            d = get_labels(["Container.Content", "Container.NumItems"])
        except Exception:
            time.sleep(1)
            continue
        content = (d.get("Container.Content", "") or "")
        # genres list usually reports content 'genres'
        if content == "genres":
            time.sleep(0.5)
            snapshot_genres(w)
            grabbed = True
            break
        time.sleep(1)
    if not grabbed:
        w("  (genre window not detected -- skipping; that's fine.)")

    w("")
    w("=" * 70)
    w("DONE. Nothing changed. Send POV_LIVE_DIAGNOSTIC.txt back.")
    w("=" * 70)
    save(out)


def save(out):
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "POV_LIVE_DIAGNOSTIC.txt")
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        print("Report written to: " + p)
    except Exception as e:
        print("Could not write report: %s" % e)


if __name__ == "__main__":
    main()
