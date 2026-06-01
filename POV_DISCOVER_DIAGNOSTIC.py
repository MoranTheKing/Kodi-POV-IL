#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POV Discover/Search diagnostic.

Runs on YOUR computer (plain Python 3), talks to the Kodi running on the
same machine over Kodi's built-in HTTP JSON-RPC, and asks POV exactly what
it returns for the Discover grid and for a movie/TV search -- including the
artwork (poster/thumb/fanart) of each item.

This tells us, with certainty:
  * Does POV return posters for these paths?  (if yes -> the skin isn't
    showing them; if no -> it's a POV/TMDB art problem.)
  * What the static "Discover" grid contains vs. a real search.

------------------------------------------------------------------------
BEFORE RUNNING -- enable Kodi's web server (one time):
  Kodi -> Settings -> Services -> Control
    * "Allow remote control via HTTP"            = ON
    * note the Port (default 8080)
    * if "Require authentication" is ON, note the Username + Password
      (default username is usually "kodi")
Leave Kodi open on any screen, then run this script.
------------------------------------------------------------------------

HOW TO RUN:
  Windows:  py POV_DISCOVER_DIAGNOSTIC.py
  Mac:      python3 POV_DISCOVER_DIAGNOSTIC.py
  Linux:    python3 POV_DISCOVER_DIAGNOSTIC.py

It writes POV_DISCOVER_DIAGNOSTIC.txt next to the script. Send me that file.
"""

import json
import sys
import urllib.request
import urllib.error
import base64
import os

# ----------------------------------------------------------------------
# EDIT THESE IF NEEDED (defaults match a standard local Kodi install):
HOST = "localhost"
PORT = 8080
USERNAME = "kodi"     # set to "" if you DON'T require authentication
PASSWORD = ""         # set your Kodi web password here if you set one
# ----------------------------------------------------------------------

# The exact paths the #207 build wires the AF3 Discover grid + search rows to.
PATHS = [
    ("DISCOVER GRID (static popular movies)",
     "plugin://plugin.video.pov/?mode=build_movie_list"
     "&action=tmdb_movies_popular&name=32461&iconImage=dvd.png"),
    ("MOVIE SEARCH  query=mario",
     "plugin://plugin.video.pov/?mode=build_movie_list"
     "&action=tmdb_movies_search&query=mario"),
    ("TV SEARCH     query=mario",
     "plugin://plugin.video.pov/?mode=build_tvshow_list"
     "&action=tmdb_tv_search&query=mario"),
    ("POPULAR TV (for comparison)",
     "plugin://plugin.video.pov/?mode=build_tvshow_list"
     "&action=tmdb_tv_popular&name=32462&iconImage=dvd.png"),
]

URL = "http://{0}:{1}/jsonrpc".format(HOST, PORT)


def rpc(method, params):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    }).encode("utf-8")
    req = urllib.request.Request(URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    if USERNAME:
        token = base64.b64encode(
            "{0}:{1}".format(USERNAME, PASSWORD).encode("utf-8")).decode()
        req.add_header("Authorization", "Basic " + token)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_directory(path):
    return rpc("Files.GetDirectory", {
        "directory": path,
        "media": "video",
        "properties": ["title", "art", "thumbnail", "season", "episode"],
    })


def main():
    out = []

    def w(line=""):
        out.append(line)
        print(line)

    w("=" * 70)
    w("POV DISCOVER/SEARCH DIAGNOSTIC")
    w("Kodi JSON-RPC endpoint: " + URL)
    w("=" * 70)

    # connectivity check
    try:
        ping = rpc("JSONRPC.Ping", {})
        w("Ping: " + json.dumps(ping))
    except urllib.error.HTTPError as e:
        w("HTTP ERROR talking to Kodi: {0} {1}".format(e.code, e.reason))
        w(">>> Check: web server ON? correct PORT? correct USERNAME/PASSWORD?")
        _save(out)
        return
    except Exception as e:
        w("CANNOT REACH KODI: {0}".format(e))
        w(">>> Is Kodi running on this machine, with the web server enabled?")
        _save(out)
        return

    # POV installed/enabled?
    try:
        addons = rpc("Addons.GetAddons", {"type": "xbmc.python.pluginsource"})
        ids = [a.get("addonid", "") for a in
               addons.get("result", {}).get("addons", [])]
        w("\nplugin.video.pov installed: " +
          str("plugin.video.pov" in ids))
    except Exception as e:
        w("\n(could not list addons: {0})".format(e))

    for title, path in PATHS:
        w("\n" + "-" * 70)
        w("### " + title)
        w("PATH: " + path)
        w("-" * 70)
        try:
            res = get_directory(path)
        except Exception as e:
            w("  REQUEST FAILED: {0}".format(e))
            continue
        if "error" in res:
            w("  JSON-RPC error: " + json.dumps(res["error"], ensure_ascii=False))
            continue
        files = res.get("result", {}).get("files", []) or []
        w("  ITEM COUNT: {0}".format(len(files)))
        if not files:
            w("  (POV returned NO items for this path)")
            continue
        # show first 6 items with their full art
        for i, it in enumerate(files[:6]):
            label = it.get("label") or it.get("title") or "?"
            art = it.get("art", {}) or {}
            thumb = it.get("thumbnail", "")
            w("  [{0}] {1}".format(i, label))
            if art:
                for k in sorted(art.keys()):
                    v = art[k]
                    short = (v[:90] + "...") if len(v) > 93 else v
                    w("        art[{0}] = {1}".format(k, short))
            else:
                w("        art = {} (EMPTY)")
            if thumb:
                short = (thumb[:90] + "...") if len(thumb) > 93 else thumb
                w("        thumbnail = {0}".format(short))
        # summary: how many of ALL items have a poster
        with_poster = sum(1 for it in files
                          if (it.get("art", {}) or {}).get("poster"))
        with_thumb = sum(1 for it in files
                         if (it.get("art", {}) or {}).get("thumb")
                         or it.get("thumbnail"))
        w("  SUMMARY: {0}/{1} items have art.poster ; {2}/{1} have a thumb"
          .format(with_poster, len(files), with_thumb))

    w("\n" + "=" * 70)
    w("DONE. Send the file POV_DISCOVER_DIAGNOSTIC.txt back.")
    w("=" * 70)
    _save(out)


def _save(out):
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "POV_DISCOVER_DIAGNOSTIC.txt")
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        print("\nReport written to: " + p)
    except Exception as e:
        print("Could not write report file: {0}".format(e))


if __name__ == "__main__":
    main()
