"""The viewer's own rows and chips on the Onyx home (Wizard 0.5.26 / Onyx 1.0.25; chips and a library row's order:
Wizard 0.5.28 / Onyx 1.0.27): the settings tile "שורות וכפתורים משלי".

A viewer, via the owner, Nov 2026: "let me add a category -- say the films on my hard drive; leave the menus open to
configure, for those who tinker with Kodi". Every tab in TABS has SLOTS rows of the viewer's own at its end
(tools/skin_onyx/gen_home.py CUSTOM_TABS): a row is the skin strings POVILRow_<tab>_<n>_path and _name, and it shows
only while it has a path and the path has items.

The same viewer, Nov 2026: "how can I add a button that takes me into my films library, like the buttons on top --
Netflix, Disney?" and "I have no way to order the films -- by year, by name...". So:
  * CHIPS chips of the viewer's own on each of those screens (POVILChip_<tab>_<n>_path / _name; gen_home.py
    CUSTOM_CHIPS): a chip opens its folder in the Videos window -- Kodi's library there has its own sort menu.
  * A row from Kodi's library (a videodb:// address) has an order (POVILRow_<tab>_<n>_sort / _order; gen_home.py
    LIBRARY_SORTS, the same five): the skin sorts it and starts it on the right. Kodi 21 applies the filter of an
    address's smart playlist but not its order (QA Kodi: every order came out by name), so the order is the skin's.
"""
TABS = (('movies', 'סרטים'), ('tv', 'סדרות'), ('kids', 'ילדים'), ('favourites', 'מועדפים'))
SLOTS = 3
# (six since Wizard 0.5.29 / Onyx 1.0.28, each standing where the viewer puts it and opening a folder or doing what a
# favourite, an add-on or the live TV does: menu_editor.py)
CHIPS = 6
HEADING = 'שורות וכפתורים משלי'
LIBRARY = (('videodb://movies/titles/', 'הספרייה של קודי: סרטים'), ('videodb://tvshows/titles/', 'הספרייה של קודי: סדרות'),
           ('videodb://recentlyaddedmovies/', 'הספרייה של קודי: סרטים שנוספו לאחרונה'))
# (Kodi's sort method, the order, what the viewer reads) -- gen_home.py LIBRARY_SORTS
SORTS = (('dateadded', 'descending', 'החדשים שנוספו קודם'), ('year', 'descending', 'לפי שנה, החדשים קודם'),
         ('title', 'ascending', 'לפי שם, א-ת'), ('rating', 'descending', 'לפי דירוג, הגבוה קודם'),
         ('random', 'descending', 'בסדר אקראי'))


def setting(tab, n, part, kind='Row'):
    return 'POVIL%s_%s_%d_%s' % (kind, tab, n, part)


def quoted(path):
    """The path as a Skin.SetString parameter. Kodi drops a trailing backslash inside quotes (QA Kodi 21, Windows:
    "C:\\Films\\" came back as C:\\Films), so a path goes bare unless a comma would split it."""
    path = path.replace('"', '')
    return '"%s"' % path if ',' in path else path


def clean_name(name, default='השורה שלי'):
    """A row's name as a Skin.SetString parameter: a comma, a bracket or a quote would cut it short in Kodi's builtin
    parser ("סרטים (HD" -- the reviewer, 0.5.26), so each becomes a space."""
    for ch in ',()"':
        name = name.replace(ch, ' ')
    return ' '.join(name.split()) or default


def is_library(path):
    """A row that reads Kodi's library: the skin sorts it (gen_home.py slot_sorts)."""
    return (path or '').startswith('videodb://')


def has_order(path):
    """A library row whose order is the viewer's to choose (its recently added are in their own order)."""
    return is_library(path) and not path.startswith('videodb://recentlyadded')


def library_path(path, rpc=None):
    """A folder whose films (or series) are in Kodi's library: the library's own list of just those (posters, details)
    -- else None. A viewer, Nov 2026, his films' folder added to Kodi as films and scanned: the row showed the folder
    (file names) and not the films. (The order is the skin's: an address's order Kodi 21 does not apply.)"""
    import json
    from urllib.parse import quote
    if rpc is None:
        import xbmc
        rpc = xbmc.executeJSONRPC
    for method, kind, node in (('VideoLibrary.GetMovies', 'movies', 'videodb://movies/titles/'),
                               ('VideoLibrary.GetTVShows', 'tvshows', 'videodb://tvshows/titles/')):
        try:
            reply = json.loads(rpc(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': {
                'filter': {'field': 'path', 'operator': 'startswith', 'value': path}, 'limits': {'start': 0, 'end': 1}}})))
            total = ((reply.get('result') or {}).get('limits') or {}).get('total') or 0
        except Exception:
            total = 0
        if total:
            # (Kodi's own smart-playlist filter; encoded, so no comma or quote reaches Skin.SetString)
            xsp = {'rules': {'and': [{'field': 'path', 'operator': 'startswith', 'value': [path]}]}, 'type': kind}
            return node + '?xsp=' + quote(json.dumps(xsp, separators=(',', ':')), safe='')
    return None


def favourite_paths():
    """(path, name) of Kodi favourites that open a folder."""
    import json
    import re
    import xbmc
    reply = json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Favourites.GetFavourites',
                                                        'params': {'properties': ['window', 'windowparameter', 'path']}})))
    out = []
    for fav in (reply.get('result') or {}).get('favourites') or []:
        path = fav.get('windowparameter') or ''
        if not path:
            m = re.search(r'ActivateWindow\(\s*\w+\s*,\s*"?([^",)]+)', fav.get('path') or '')
            path = m.group(1) if m else ''
        if path:
            out.append((path, fav.get('title') or path))
    return out


def pick_source(dialog, what='השורה', favourites=True):
    """A folder the row (or chip) shows: a library node, a folder (a hard drive, the network, an add-on) or a favourite
    that opens a folder (favourites=False: not offered -- the menu editor offers every favourite by its command)."""
    choices = [name for _p, name in LIBRARY] + ['תיקייה (הארד-דיסק, רשת או תוסף)'] + (['מועדף של קודי'] if favourites else [])
    picked = dialog.select('מקור ' + what, choices)
    if picked < 0:
        return None
    if picked < len(LIBRARY):
        return LIBRARY[picked][0]
    if picked == len(LIBRARY):
        path = dialog.browse(0, 'בחירת תיקייה', 'videos', '', False, False, '')
        if not path:
            return None
        return library_path(path) or path
    favs = favourite_paths()
    if not favs:
        dialog.ok(HEADING, 'אין מועדפים של תיקיות.')
        return None
    f = dialog.select('מועדף', [name for _p, name in favs])
    return favs[f][0] if f >= 0 else None


def pick_order(dialog, current=''):
    """The order of a library row's items: (method, direction), or None."""
    labels = [('* ' if method == current else '') + label for method, _d, label in SORTS]
    o = dialog.select('סדר הפריטים בשורה', labels)
    return SORTS[o][:2] if o >= 0 else None


def set_order(tab, n, order, run):
    run('Skin.SetString(%s,%s)' % (setting(tab, n, 'sort'), order[0]))
    run('Skin.SetString(%s,%s)' % (setting(tab, n, 'order'), order[1]))
    # (the row starts on the right again: Kodi keeps a re-sorted row's selected film wherever the order puts it --
    # gen_home.py RESORT)
    run('SetProperty(povil.rtl.reset,1,home)')


def drop_order(tab, n, run):
    run('Skin.Reset(%s)' % setting(tab, n, 'sort'))
    run('Skin.Reset(%s)' % setting(tab, n, 'order'))


def choose(kinds=('Row', 'Chip')):
    """The tile "שורות וכפתורים משלי" (kinds: the menu editor asks for the rows alone)."""
    import xbmc
    import xbmcgui
    dialog = xbmcgui.Dialog()
    read, run = xbmc.getInfoLabel, xbmc.executebuiltin
    t = dialog.select(HEADING + ': באיזו לשונית?', [name for _t, name in TABS])
    if t < 0:
        return
    tab, tab_name = TABS[t]
    while True:
        slots, names = [], []
        for n in range(1, SLOTS + 1 if 'Row' in kinds else 1):
            slots.append(('Row', n))
            names.append('שורה %d: %s' % (n, read('Skin.String(%s)' % setting(tab, n, 'name')) or '(ריקה)'))
        for n in range(1, CHIPS + 1 if 'Chip' in kinds else 1):
            slots.append(('Chip', n))
            name = read('Skin.String(%s)' % setting(tab, n, 'name', 'Chip'))
            has = read('Skin.String(%s)' % setting(tab, n, 'path', 'Chip')) or read('Skin.String(%s)' % setting(tab, n, 'cmd', 'Chip'))
            names.append('כפתור %d: %s' % (n, name if has else '(ריק)'))
        s = dialog.select('%s - %s' % (HEADING, tab_name), names)
        if s < 0:
            return
        kind, n = slots[s]
        if kind == 'Chip':
            chip(dialog, tab, n, read, run)
        else:
            row(dialog, tab, n, read, run)
        xbmc.sleep(300)


def row(dialog, tab, n, read, run):
    path = read('Skin.String(%s)' % setting(tab, n, 'path'))
    actions = (['בחירת מקור'] + (['סדר הפריטים'] if has_order(path) else []) + ['שינוי שם', 'מחיקת השורה']) if path else ['בחירת מקור']
    a = dialog.select('שורה %d' % n, actions)
    if a < 0:
        return
    action = actions[a]
    if action == 'בחירת מקור':
        path = pick_source(dialog)
        if not path:
            return
        order = None
        if has_order(path):
            order = pick_order(dialog, read('Skin.String(%s)' % setting(tab, n, 'sort')) or SORTS[0][0])
            if order is None:
                return
        current = read('Skin.String(%s)' % setting(tab, n, 'name'))
        name = dialog.input('שם השורה', current or 'השורה שלי')
        run('Skin.SetString(%s,%s)' % (setting(tab, n, 'name'), clean_name(name or 'השורה שלי')))
        run('Skin.SetString(%s,%s)' % (setting(tab, n, 'path'), quoted(path)))
        if order:
            set_order(tab, n, order, run)
        else:
            drop_order(tab, n, run)
        # a screen whose order the viewer set: the new row joins it at its end (home_rows.py)
        try:
            from resources.libs import home_rows
            import xbmc
            home_rows.place_custom(tab, '%s_%d' % (tab, n), read, xbmc.getCondVisibility, run)
        except Exception:
            pass
    elif action == 'סדר הפריטים':
        order = pick_order(dialog, read('Skin.String(%s)' % setting(tab, n, 'sort')) or SORTS[0][0])
        if order:
            set_order(tab, n, order, run)
    elif action == 'שינוי שם':
        name = dialog.input('שם השורה', read('Skin.String(%s)' % setting(tab, n, 'name')))
        if name:
            run('Skin.SetString(%s,%s)' % (setting(tab, n, 'name'), clean_name(name)))
    else:
        run('Skin.Reset(%s)' % setting(tab, n, 'path'))
        run('Skin.Reset(%s)' % setting(tab, n, 'name'))
        drop_order(tab, n, run)
        try:
            from resources.libs import home_rows
            import xbmc
            home_rows.drop_custom(tab, '%s_%d' % (tab, n), xbmc.getCondVisibility, read, run)
        except Exception:
            pass


def chip(dialog, tab, n, read, run):
    """A chip of the viewer's: what it opens (a folder, a favourite, an add-on, the live TV...), its name, where it
    stands, or deleted -- the menu editor's own dialogs (menu_editor.py)."""
    import xbmc
    from resources.libs import menu_editor
    key = 'POVILChip_%s_%d' % (tab, n)
    info = (menu_editor.menu().get('chips') or {}).get(tab) or {}
    if read('Skin.String(%s_path)' % key) or read('Skin.String(%s_cmd)' % key):
        menu_editor.own_chip(dialog, tab, n, info, read, run, xbmc.executeJSONRPC)
        return
    if dialog.select('כפתור %d' % n, ['בחירת מקור']) != 0:
        return
    target = menu_editor.pick_target(dialog, xbmc.executeJSONRPC, 'מה הכפתור יפתח?')
    if not target:
        return
    name = dialog.input('שם הכפתור', target.get('name') or 'הכפתור שלי')
    menu_editor.write_target(key, target, run)
    run('Skin.SetString(%s_name,%s)' % (key, clean_name(name or 'הכפתור שלי', 'הכפתור שלי')))
