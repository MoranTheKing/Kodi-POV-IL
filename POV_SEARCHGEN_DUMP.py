#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AF3 generated search-include dumper (READ ONLY -- changes nothing).

Search result tiles render blank though the data has Art(poster). The
search rows + selector are GENERATED at runtime by script.skinvariables
into the skin's generated includes file. This dumps the EXACT generated
blocks for:
    skinvariables-searchwidgets-combined   (the movie/tv result rows)
    skinvariables-searchwidgets-standard
    skinvariables-searchwidgets-selector   (the category buttons -> guids)
so we can see the real <param name="visible">, <param name="content">,
and <property name="guid"> values that decide whether each row draws.

Also prints, for context, the searchwidgets node we wrote.

Read only. Kodi can be open or closed.
  Windows:  py POV_SEARCHGEN_DUMP.py
  Mac:      python3 POV_SEARCHGEN_DUMP.py
If Kodi isn't auto-found:  py POV_SEARCHGEN_DUMP.py "C:\\...\\Kodi"
Writes POV_SEARCHGEN_DUMP.txt next to the script. Send it back.
"""

import os
import re
import sys

SKIN = "skin.arctic.fuse.3"


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
        if c and os.path.isdir(os.path.join(c, "addons", SKIN)):
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


def dump_include(w, text, name):
    """Print the <include name="NAME"> ... </include> block (nested-safe)."""
    m = re.search(r'<include name="%s">' % re.escape(name), text)
    if not m:
        w('  (include "%s" NOT FOUND in this file)' % name)
        return
    start = m.start()
    i = m.end()
    depth = 1
    while i < len(text):
        nxt_open = text.find("<include", i)
        nxt_close = text.find("</include>", i)
        if nxt_close == -1:
            break
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            i = nxt_open + len("<include")
        else:
            depth -= 1
            i = nxt_close + len("</include>")
            if depth == 0:
                break
    block = text[start:i]
    base = text[:start].count("\n") + 1
    for j, ln in enumerate(block.split("\n")):
        w("  %5d| %s" % (base + j, ln.rstrip()[:200]))


def main():
    out = []

    def w(s=""):
        out.append(s)

    kodi = find_kodi_home(sys.argv)
    w("=" * 70)
    w("AF3 GENERATED SEARCH-INCLUDE DUMP (read only)")
    w("Kodi home: " + str(kodi))
    w("=" * 70)
    if not kodi:
        w("Kodi not found -- re-run with path:")
        w('  py POV_SEARCHGEN_DUMP.py "C:\\Users\\<you>\\AppData\\Roaming\\Kodi"')
        save(out)
        return

    skindir = os.path.join(kodi, "addons", SKIN, "1080i")
    # find the generated includes file(s)
    gen_files = []
    if os.path.isdir(skindir):
        for fn in os.listdir(skindir):
            if fn.startswith("script-skinvariables") and fn.endswith(".xml"):
                gen_files.append(os.path.join(skindir, fn))
    # also the explicit one we saw
    explicit = os.path.join(skindir, "script-skinvariables-generator-includes-.xml")
    if os.path.isfile(explicit) and explicit not in gen_files:
        gen_files.append(explicit)

    w("")
    w("generated include files found: %d" % len(gen_files))
    for g in gen_files:
        w("  - " + g)

    targets = ["skinvariables-searchwidgets-combined",
               "skinvariables-searchwidgets-standard",
               "skinvariables-searchwidgets-selector"]
    for g in gen_files:
        t = read(g)
        if not t:
            continue
        if not any(("<include name=\"%s\">" % n) in t for n in targets):
            continue
        w("")
        w("#" * 70)
        w("# FILE: " + g)
        w("#" * 70)
        for n in targets:
            w("")
            w("-" * 70)
            w("### " + n)
            w("-" * 70)
            dump_include(w, t, n)

    # the node we wrote
    w("")
    w("=" * 70)
    w("### our searchwidgets node (source of the rows)")
    w("=" * 70)
    node = os.path.join(kodi, "userdata", "addon_data",
                        "script.skinvariables", "nodes", SKIN,
                        "skinvariables-shortcut-searchwidgets.json")
    nt = read(node)
    if nt:
        w("PATH: " + node)
        w(nt[:2000])
    else:
        w("(searchwidgets node not found at %s)" % node)

    # Also: the Includes_Search.xml hardcoded discover block for comparison
    w("")
    w("=" * 70)
    w("### Includes_Search.xml -- group 500 + discover (for comparison)")
    w("=" * 70)
    inc = read(os.path.join(skindir, "Includes_Search.xml"))
    if inc:
        lines = inc.split("\n")
        for i, ln in enumerate(lines, 1):
            if ('id="500"' in ln or 'id="501"' in ln or
                    "Hub_Combined_Widget" in ln or
                    "searchwidgets-combined" in ln or
                    "searchwidgets-standard" in ln or
                    ('name="visible"' in ln and 601 == 601 and "601" in ln) or
                    "Property(guid)" in ln):
                w("  %5d| %s" % (i, ln.strip()[:200]))

    w("")
    w("=" * 70)
    w("DONE. Nothing changed. Send POV_SEARCHGEN_DUMP.txt back.")
    w("=" * 70)
    save(out)


def save(out):
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "POV_SEARCHGEN_DUMP.txt")
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(out))
        print("Report written to: " + p)
    except Exception as e:
        print("Could not write report: %s" % e)


if __name__ == "__main__":
    main()
