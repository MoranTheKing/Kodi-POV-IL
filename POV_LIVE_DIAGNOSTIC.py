#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POV LIVE container diagnostic (read only).

We proved: POV returns Art(poster) for search (21/21), the skin renders
Art(poster) on the same path as the working widgets, and the texture cache
is healthy (40/40 posters present). Yet the SEARCH rows show blank posters
while DISCOVER (same render path) shows them. So we must read what the skin
ACTUALLY has loaded in the search containers at runtime.

This asks Kodi (over JSON-RPC, GetInfoLabels) for the live contents of the
search/discover containers -- exactly what the skin sees right now:
  * 501 = Discover grid (shows posters -> our control/baseline)
  * 502 = Movies search results (blank posters -> the problem)
  * 503 = TV search results   (blank posters -> the problem)
  * 601 = the category selector
For each, it reads NumItems and, per item, the Label and every art key the
skin's Image_Poster variable tries: Art(poster), Art(tvshow.poster),
Art(season.poster), Icon, plus Art(thumb). Read only; changes nothing.

>>> IMPORTANT -- do this FIRST, then run the script:
  1. Open Kodi. Enable the web server (Settings > Services > Control >
     "Allow remote control via HTTP", port 8080) if not already.
  2. Go to the SEARCH screen, type:  mario
  3. Click into the "סרטים" (Movies) category so the results SHOW.
  4. LEAVE that screen open (don't go back), then run this script.

  Windows:  py POV_LIVE_DIAGNOSTIC.py
  Mac:      python3 POV_LIVE_DIAGNOSTIC.py

If you set a web password/port, edit the four values below.
Writes POV_LIVE_DIAGNOSTIC.txt next to the script. Send it back.
"""

import json
import os
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


def rpc(method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    if USERNAME:
        tok = base64.b64encode(
            ("%s:%s" % (USERNAME, PASSWORD)).encode("utf-8")).decode()
        req.add_header("Authorization", "Basic " + tok)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def get_labels(labels):
    res = rpc("XBMC.GetInfoLabels", {"labels": labels})
    return res.get("result", {}) if isinstance(res, dict) else {}


def main():
    out = []

    def w(s=""):
        out.append(s)

    w("=" * 70)
    w("POV LIVE CONTAINER DIAGNOSTIC (read only)")
    w("Endpoint: " + URL)
    w("=" * 70)

    try:
        png = rpc("JSONRPC.Ping", {})
        w("Ping: " + json.dumps(png))
    except urllib.error.HTTPError as e:
        w("HTTP ERROR: %s %s" % (e.code, e.reason))
        w(">>> check web server ON, port, and USERNAME/PASSWORD above.")
        save(out)
        return
    except Exception as e:
        w("CANNOT REACH KODI: %s" % e)
        w(">>> is Kodi running with the web server enabled?")
        save(out)
        return

    # context
    ctx = get_labels([
        "System.CurrentWindow",
        "System.CurrentControl",
        "Window(Home).Property(TMDbHelper.WidgetContainer)",
        "Control.GetLabel(3000)",
        "Container(601).ListItem.Property(guid)",
    ])
    w("")
    w("-" * 70)
    w("### context (where you are right now)")
    w("-" * 70)
    for k, v in ctx.items():
        w("  %-55s = %s" % (k, v))

    # First, scan a range of container IDs and report which ones hold items,
    # so we don't depend on the exact search-widget id (501=discover,
    # 502/503 = movies/tv search rows, but be robust if numbering differs).
    art_keys = ["Art(poster)", "Art(tvshow.poster)", "Art(season.poster)",
                "Icon", "Art(thumb)", "Art(fanart)"]
    w("")
    w("-" * 70)
    w("### container scan (NumItems for 501-512, 601, 602)")
    w("-" * 70)
    scan_ids = list(range(501, 513)) + [601, 602]
    populated = []
    for cid in scan_ids:
        d = get_labels(["Container(%d).NumItems" % cid])
        num = d.get("Container(%d).NumItems" % cid, "")
        try:
            n = int(num)
        except Exception:
            n = 0
        if num not in ("", "0"):
            w("  Container(%d).NumItems = %s" % (cid, num))
        if n > 0:
            populated.append(cid)
    if not populated:
        w("  (no populated containers found -- did you search 'mario' and")
        w("   open the Movies category, leaving that screen on top?)")

    # Always dump these known roles, plus any other populated container.
    labelled = {501: "DISCOVER (baseline -- shows posters)",
                502: "MOVIES search (suspect)",
                503: "TV search (suspect)",
                601: "selector"}
    dump_ids = sorted(set([501, 502, 503, 601] + populated))
    for cid in dump_ids:
        title = "%d  %s" % (cid, labelled.get(cid, "(populated)"))
        w("")
        w("-" * 70)
        w("### container %s" % title)
        w("-" * 70)
        head = get_labels(["Container(%d).NumItems" % cid,
                            "Container(%d).IsUpdating" % cid,
                            "Container(%d).ListItem.Label" % cid])
        num = head.get("Container(%d).NumItems" % cid, "")
        upd = head.get("Container(%d).IsUpdating" % cid, "")
        w("  NumItems=%s  IsUpdating=%s" % (num, upd))
        try:
            n = int(num)
        except Exception:
            n = 0
        if n == 0:
            w("  (empty -- if this is 502/503, make sure you searched and")
            w("   selected that category so the row is loaded)")
            continue
        show = min(n, 6)
        for i in range(1, show + 1):
            labels = ["Container(%d).ListItem(%d).Label" % (cid, i)]
            for ak in art_keys:
                labels.append("Container(%d).ListItem(%d).%s" % (cid, i, ak))
            d = get_labels(labels)
            lab = d.get("Container(%d).ListItem(%d).Label" % (cid, i), "")
            w("  [%d] %s" % (i, lab))
            for ak in art_keys:
                v = d.get("Container(%d).ListItem(%d).%s" % (cid, i, ak), "")
                if v:
                    sv = v if len(v) <= 95 else v[:95] + "..."
                    w("        %-20s = %s" % (ak, sv))
            # flag if NOTHING resolved
            anyart = any(d.get("Container(%d).ListItem(%d).%s" % (cid, i, ak))
                         for ak in art_keys)
            if not anyart:
                w("        (no art of any kind on this item!)")

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
        print("\n".join(out))


if __name__ == "__main__":
    main()
