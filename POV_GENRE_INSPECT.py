#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POV genre-icon inspector (READ ONLY -- changes nothing).

Symptom: genre tiles show the POV DEFAULT icon (on BOTH skins), even though
the menu items point at .../media/genres/genre_<x>.png and 28 PNGs exist.
When the path is right + file exists but the default still shows, the usual
cause is a NAME MISMATCH: POV's menu asks for a filename that isn't exactly
what's on disk -> fallback. This reads POV's OWN source to prove it.

It reports:
  1. The exact genres()/anime_genres() icon line in POV navigator.py
     (patched to use the per-genre icon? or still 'genres.png'?).
  2. The build_shortcut_folder_list icon line (path-doubling hardened?).
  3. POV's genre->icon-filename mapping from modules/meta_lists.py.
  4. For every icon filename POV references: does that exact file exist in
     POV's media/genres/, and does it match the icon WE ship (by size+md5)?
     -> flags MISSING names and WRONG/!=ours/stock files.

Read only. Run with Kodi open or closed.
  Windows:  py POV_GENRE_INSPECT.py
  Mac:      python3 POV_GENRE_INSPECT.py
If Kodi isn't auto-found:  py POV_GENRE_INSPECT.py "C:\\...\\Kodi"
Writes POV_GENRE_INSPECT.txt next to the script. Send it back.
"""

import os
import re
import sys
import hashlib

POV = "plugin.video.pov"

# Fingerprints (size, md5) of the 28 genre PNGs THIS build ships.
OUR_ICONS = {
    "genre_action.png": (2827, "1009f372611f06c6b301f50f950c5ca1"),
    "genre_action_adventure.png": (5535, "b6378cadd903aee36b2c29665958cb14"),
    "genre_adventure.png": (5674, "8702264a4bba676b96e00ef9f5df6a00"),
    "genre_animation.png": (3654, "e2cc126f75c10de1bf9b6cbc30cf9c3b"),
    "genre_comedy.png": (5832, "38597d4a98c4b9b2e9158b7934eecaea"),
    "genre_crime.png": (2940, "2518f2c01f945000a81ac7b19f308a08"),
    "genre_documentary.png": (5778, "e2585f2bb4ab63cb9970edc28ab38355"),
    "genre_drama.png": (3091, "4e43895c9777dd4cecda8ab18c050a86"),
    "genre_family.png": (4579, "653f8c040ecfa211748fa562846447d9"),
    "genre_fantasy.png": (3175, "97c82a63ee0e96256d14337a14b89996"),
    "genre_history.png": (1926, "bd1b5ae5cdcdf3f0ba8b831fcd26bdca"),
    "genre_horror.png": (3512, "06abc27c16ac880f7df7523e1c0be121"),
    "genre_kids.png": (4271, "c9ea39f1d83dd8f6be91cb8b7faccdc8"),
    "genre_music.png": (3567, "3d53934e4353b2743f077993fdbb5834"),
    "genre_mystery.png": (2424, "78af886063c5a28680c41d87b3109909"),
    "genre_news.png": (2240, "5f3b1e8a373169d2db321e1a19806723"),
    "genre_reality.png": (3170, "5f73f887ca5ddda6e6a1e28812cc7438"),
    "genre_romance.png": (3182, "d811cdfdb5d933a1285b702369d5d0b3"),
    "genre_scifi.png": (3466, "dad805b36ea1bcb3483c576326f118be"),
    "genre_scifi_fantasy.png": (3480, "3ac01dfe9a71dc808aefeab1a912463a"),
    "genre_soap.png": (3268, "0a95feb97d61f9a24d344ace61e64cef"),
    "genre_talk.png": (1887, "880d61e2da2c4b2699ce90c4025b4005"),
    "genre_thriller.png": (2423, "e1c982bba68eb53a2fa863b64ee7cfe5"),
    "genre_tv.png": (3048, "01eb8d0aad5d6ff9a388e7d2bdf3019f"),
    "genre_tvmovie.png": (3048, "01eb8d0aad5d6ff9a388e7d2bdf3019f"),
    "genre_war.png": (1817, "25c077748316cf17392e31727714da76"),
    "genre_war_politics.png": (2665, "531fd3ae06434430c3c50e7482ecc2ea"),
    "genre_western.png": (2478, "2d8257c1fd3743c8d899c0552c62f523"),
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
        if c and os.path.isdir(os.path.join(c, "addons", POV)):
            return c
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "addons")):
            return c
    return None


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def md5size(path):
    try:
        b = open(path, "rb").read()
        return len(b), hashlib.md5(b).hexdigest()
    except Exception:
        return (-1, "")


def main():
    out = []

    def w(s=""):
        out.append(s)

    kodi = find_kodi_home(sys.argv)
    w("=" * 70)
    w("POV GENRE-ICON INSPECTOR (read only)")
    w("Kodi home: " + str(kodi))
    w("=" * 70)
    if not kodi:
        w("Kodi not found -- re-run with the path:")
        w('  py POV_GENRE_INSPECT.py "C:\\Users\\<you>\\AppData\\Roaming\\Kodi"')
        save(out)
        return

    povdir = os.path.join(kodi, "addons", POV)
    w("POV installed: " + str(os.path.isdir(povdir)))
    if not os.path.isdir(povdir):
        save(out)
        return

    # 1) navigator.py icon lines
    nav = os.path.join(povdir, "resources", "lib", "menus", "navigator.py")
    w("")
    w("-" * 70)
    w("### navigator.py genre icon code")
    w("-" * 70)
    nt = read(nav)
    if nt is None:
        w("  (navigator.py not found)")
    else:
        w("  AI genre-icons marker present: " +
          str("AI_SUBS_POV_GENRE_ICONS" in nt))
        for i, ln in enumerate(nt.split("\n"), 1):
            if "_add_item(" in ln and ("genres.png" in ln or
                                       "genres/%s" in ln or
                                       "value[1]" in ln):
                w("  L%-5d %s" % (i, ln.strip()[:160]))
            if "icon_path, item_get('iconImage')" in ln or \
               "startswith(('special://'" in ln:
                w("  L%-5d %s" % (i, ln.strip()[:160]))

    # 2) meta_lists.py genre -> icon filename mapping
    w("")
    w("-" * 70)
    w("### POV genre->icon mapping (modules/meta_lists.py)")
    w("-" * 70)
    referenced = set()
    ml = os.path.join(povdir, "resources", "lib", "modules", "meta_lists.py")
    mt = read(ml)
    if mt is None:
        # try a couple of alternative locations
        for alt in ("resources/lib/modules/meta_lists.py",
                    "resources/lib/meta_lists.py"):
            mt = read(os.path.join(povdir, *alt.split("/")))
            if mt:
                ml = os.path.join(povdir, *alt.split("/"))
                break
    if mt is None:
        w("  (meta_lists.py not found -- searching all POV .py for "
          "genre_*.png references)")
        for dp, _dn, fn in os.walk(povdir):
            for name in fn:
                if name.endswith(".py"):
                    t = read(os.path.join(dp, name)) or ""
                    for m in re.findall(r"genre_[a-z_]+\.png", t):
                        referenced.add(m)
                    for m in re.findall(r"'genres\.png'", t):
                        referenced.add("genres.png")
    else:
        w("  source: " + ml)
        # capture every 'something.png' that appears near a genre list
        for m in re.findall(r"['\"]([a-z_]+\.png)['\"]", mt):
            referenced.add(m)
        # show the first ~30 lines that contain a .png so we see structure
        shown = 0
        for ln in mt.split("\n"):
            if ".png" in ln and "genre" in ln.lower() and shown < 24:
                w("  | " + ln.strip()[:150])
                shown += 1

    # Keep only genre-ish icon names
    genre_names = sorted(n for n in referenced
                         if n.startswith("genre") or n == "genres.png")
    w("")
    w("  icon filenames POV references (genre-related): %d" %
      len(genre_names))
    w("  " + ", ".join(genre_names) if genre_names else "  (none found)")

    # 3) compare against what's on disk + what we ship
    gdir = os.path.join(povdir, "resources", "skins", "Default", "media",
                        "genres")
    w("")
    w("-" * 70)
    w("### on-disk vs referenced vs our shipped icons")
    w("-" * 70)
    w("  genre media dir: " + gdir)
    w("  dir exists: " + str(os.path.isdir(gdir)))
    on_disk = {}
    if os.path.isdir(gdir):
        for fn in os.listdir(gdir):
            if fn.lower().endswith(".png"):
                on_disk[fn] = md5size(os.path.join(gdir, fn))
        w("  PNGs on disk: %d" % len(on_disk))

    # Which referenced names are MISSING on disk?  (this = POV default!)
    if genre_names:
        missing = [n for n in genre_names if n not in on_disk]
        w("")
        w("  >>> referenced-but-MISSING on disk (these show POV default): %d"
          % len(missing))
        for n in missing:
            w("        %s" % n)

    # Do the on-disk files match OURS, or are they stock/other?
    w("")
    w("  on-disk icon identity (vs the icons THIS build ships):")
    match_ours = 0
    not_ours = 0
    for fn in sorted(on_disk):
        sz, m = on_disk[fn]
        ours = OUR_ICONS.get(fn)
        if ours and ours[0] == sz and ours[1] == m:
            match_ours += 1
            tag = "ours"
        else:
            not_ours += 1
            tag = "NOT-ours (size=%d md5=%s)" % (sz, m[:8])
        if tag != "ours":
            w("        %-26s %s" % (fn, tag))
    w("")
    w("  SUMMARY: on-disk matches-ours=%d, not-ours=%d, "
      "referenced-missing=%d" %
      (match_ours, not_ours,
       len([n for n in genre_names if n not in on_disk]) if genre_names
       else 0))

    w("")
    w("=" * 70)
    w("DONE. Nothing changed. Send POV_GENRE_INSPECT.txt back.")
    w("=" * 70)
    save(out)


def save(out):
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "POV_GENRE_INSPECT.txt")
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        print("Report written to: " + p)
    except Exception as e:
        print("Could not write report: %s" % e)


if __name__ == "__main__":
    main()
