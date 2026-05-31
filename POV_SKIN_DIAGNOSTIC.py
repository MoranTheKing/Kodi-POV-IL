#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AF3 SEARCH/DISCOVER skin diagnostic.

The POV data is healthy (the previous diagnostic proved 21/21 items have
art.poster). So the missing posters in the SEARCH result rows are a skin
rendering issue. This script reads the relevant Arctic Fuse 3 skin files +
the script.skinvariables GENERATED includes/nodes ON YOUR MACHINE and
extracts exactly which artwork infolabel the search-result rows bind to,
so the fix can be made with certainty (no guessing).

It does NOT need Kodi running and does NOT touch anything -- read only.

HOW TO RUN (same folder is fine):
  Windows:  py POV_SKIN_DIAGNOSTIC.py
  Mac:      python3 POV_SKIN_DIAGNOSTIC.py
  Linux:    python3 POV_SKIN_DIAGNOSTIC.py

If it can't find your Kodi folder automatically, pass it explicitly:
  py POV_SKIN_DIAGNOSTIC.py "C:\\Users\\<you>\\AppData\\Roaming\\Kodi"

It writes POV_SKIN_DIAGNOSTIC.txt next to the script. Send me that file.
"""

import os
import sys
import re

SKIN = 'skin.arctic.fuse.3'


def find_kodi_home(argv):
    if len(argv) > 1 and os.path.isdir(argv[1]):
        return argv[1]
    candidates = []
    ap = os.environ.get('APPDATA')
    if ap:
        candidates.append(os.path.join(ap, 'Kodi'))
    home = os.path.expanduser('~')
    candidates += [
        os.path.join(home, '.kodi'),
        os.path.join(home, 'Library', 'Application Support', 'Kodi'),
        os.path.join(home, 'Library', 'Application Support', 'kodi'),
        os.path.join(home, '.var', 'app', 'tv.kodi.Kodi', 'data', '.kodi'),
        '/storage/.kodi',
    ]
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, 'addons', SKIN)):
            return c
        if c and os.path.isdir(c):
            # accept even if skin missing, we'll report it
            pass
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return None


def read(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        return None


def main():
    out = []

    def w(s=''):
        out.append(s)

    kodi = find_kodi_home(sys.argv)
    w('=' * 70)
    w('AF3 SEARCH/DISCOVER SKIN DIAGNOSTIC')
    w('Kodi home: ' + str(kodi))
    w('=' * 70)
    if not kodi:
        w('Could not locate the Kodi data folder. Re-run and pass it, e.g.:')
        w('  py POV_SKIN_DIAGNOSTIC.py "C:\\Users\\<you>\\AppData\\Roaming\\Kodi"')
        save(out)
        return

    skin_dir = os.path.join(kodi, 'addons', SKIN)
    w('Skin installed: ' + str(os.path.isdir(skin_dir)))
    sv_data = os.path.join(kodi, 'userdata', 'addon_data',
                           'script.skinvariables')
    w('skinvariables addon_data: ' + str(os.path.isdir(sv_data)))
    w('')

    # ---- 1) The skin's own search layout file ----
    res1080 = os.path.join(skin_dir, '1080i')
    inc_search = os.path.join(res1080, 'Includes_Search.xml')
    w('-' * 70)
    w('### 1) Includes_Search.xml -- search result containers (501/601/602)')
    w('PATH: ' + inc_search)
    w('-' * 70)
    t = read(inc_search)
    if t is None:
        w('  (not found / unreadable)')
    else:
        lines = t.split('\n')
        for i, l in enumerate(lines, 1):
            if re.search(r'id="(50[01]|60[12])"|Container\((50[01]|60[12])\)'
                         r'|List_\w+_Row|widget_style|Image_Poster|'
                         r'Art\(poster\)|Art\(thumb\)|ListItem\.Icon|'
                         r'itemlayout_include|<param name="include"', l):
                s = l.strip()
                w('%5d| %s' % (i, s[:200]))

    # ---- 2) The generated skinvariables includes (search widgets) ----
    w('')
    w('-' * 70)
    w('### 2) GENERATED skinvariables files mentioning search widgets')
    w('-' * 70)
    roots = [sv_data, res1080, skin_dir]
    seen = set()
    hits = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dp, _dn, fn in os.walk(root):
            for name in fn:
                if not name.lower().endswith(('.xml', '.json')):
                    continue
                fp = os.path.join(dp, name)
                if fp in seen:
                    continue
                seen.add(fp)
                body = read(fp)
                if body and ('searchwidget' in body.lower() or
                             'DefaultSearch-POV' in body):
                    hits.append((fp, body))
    if not hits:
        w('  (no generated file references search widgets -- the node may')
        w('   not be built yet, or lives elsewhere)')
    for fp, body in hits[:12]:
        w('')
        w('FILE: ' + fp)
        for i, l in enumerate(body.split('\n'), 1):
            if re.search(r'searchwidget|DefaultSearch-POV|widget_style|'
                         r'Image_Poster|Art\(poster\)|Art\(thumb\)|'
                         r'ListItem\.Icon|List_\w+_Row|itemlayout|'
                         r'<param name="include"|"path"|"target"|"label"',
                         l, re.I):
                s = l.strip()
                w('  %5d| %s' % (i, s[:200]))

    # ---- 3) The nodes we wrote (searchwidgets.json) ----
    w('')
    w('-' * 70)
    w('### 3) Our searchwidgets node (what styles we requested)')
    w('-' * 70)
    node = os.path.join(sv_data, 'nodes', SKIN,
                        'skinvariables-shortcut-searchwidgets.json')
    nb = read(node)
    if nb is None:
        # search for it anywhere
        found = None
        if os.path.isdir(sv_data):
            for dp, _dn, fn in os.walk(sv_data):
                for name in fn:
                    if 'searchwidget' in name.lower():
                        found = os.path.join(dp, name); break
        if found:
            w('PATH: ' + found)
            nb = read(found)
    else:
        w('PATH: ' + node)
    if nb:
        w(nb[:4000])
    else:
        w('  (searchwidgets node not found)')

    # ---- 4) search_path.xml (our injected rules) ----
    w('')
    w('-' * 70)
    w('### 4) search_path.xml POV rules (rows -> POV)')
    w('-' * 70)
    spx = os.path.join(skin_dir, 'shortcuts', 'generator', 'data', 'setup',
                       'search_path.xml')
    sb = read(spx)
    if sb is None:
        w('  (not found at ' + spx + ')')
    else:
        for i, l in enumerate(sb.split('\n'), 1):
            if re.search(r'DefaultSearch-POV|AI_SUBS', l):
                w('%5d| %s' % (i, l.strip()[:200]))

    w('')
    w('=' * 70)
    w('DONE. Send POV_SKIN_DIAGNOSTIC.txt back.')
    w('=' * 70)
    save(out)


def save(out):
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, 'POV_SKIN_DIAGNOSTIC.txt')
    try:
        with open(p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out))
        print('Report written to: ' + p)
    except Exception as e:
        print('Could not write report: %s' % e)
        print('\n'.join(out))


if __name__ == '__main__':
    main()
