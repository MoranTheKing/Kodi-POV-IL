"""The viewer's own rows on the Onyx home (Wizard 0.5.26 / Onyx 1.0.25): the settings tile "שורות משלי".

A viewer, via the owner, Nov 2026: "let me add a category -- say the films on my hard drive; leave the menus open to
configure, for those who tinker with Kodi". Every tab in TABS has SLOTS rows of the viewer's own at its end
(tools/skin_onyx/gen_home.py CUSTOM_TABS): a row is the skin strings POVILRow_<tab>_<n>_path and _name, and it shows
only while it has a path and the path has items.
"""
TABS = (('movies', 'סרטים'), ('tv', 'סדרות'), ('kids', 'ילדים'), ('favourites', 'מועדפים'))
SLOTS = 3
HEADING = 'שורות משלי'
LIBRARY = (('videodb://movies/titles/', 'הספרייה של קודי: סרטים'), ('videodb://tvshows/titles/', 'הספרייה של קודי: סדרות'),
           ('videodb://recentlyaddedmovies/', 'הספרייה של קודי: סרטים שנוספו לאחרונה'))


def setting(tab, n, part):
    return 'POVILRow_%s_%d_%s' % (tab, n, part)


def quoted(path):
    """The path as a Skin.SetString parameter. Kodi drops a trailing backslash inside quotes (QA Kodi 21, Windows:
    "C:\\Films\\" came back as C:\\Films), so a path goes bare unless a comma would split it."""
    path = path.replace('"', '')
    return '"%s"' % path if ',' in path else path


def clean_name(name):
    """A row's name as a Skin.SetString parameter: a comma, a bracket or a quote would cut it short in Kodi's builtin
    parser ("סרטים (HD" -- the reviewer, 0.5.26), so each becomes a space."""
    for ch in ',()"':
        name = name.replace(ch, ' ')
    return ' '.join(name.split()) or 'השורה שלי'


def library_path(path, rpc=None):
    """A folder whose films (or series) are in Kodi's library: the library's own list of just those (posters, details),
    newest first -- else None. A viewer, Nov 2026, his films' folder added to Kodi as films and scanned: the row showed
    the folder (file names) and not the films."""
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
            xsp = {'rules': {'and': [{'field': 'path', 'operator': 'startswith', 'value': [path]}]}, 'type': kind,
                   'order': {'direction': 'descending', 'method': 'dateadded'}}
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


def pick_source(dialog):
    """A folder the row shows: a library node, a folder (a hard drive, the network, an add-on) or a favourite."""
    choices = [name for _p, name in LIBRARY] + ['תיקייה (הארד-דיסק, רשת או תוסף)', 'מועדף של קודי']
    picked = dialog.select('מקור השורה', choices)
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


def choose():
    import xbmc
    import xbmcgui
    dialog = xbmcgui.Dialog()
    t = dialog.select(HEADING + ': באיזו לשונית?', [name for _t, name in TABS])
    if t < 0:
        return
    tab, tab_name = TABS[t]
    while True:
        names = []
        for n in range(1, SLOTS + 1):
            name = xbmc.getInfoLabel('Skin.String(%s)' % setting(tab, n, 'name'))
            names.append('שורה %d: %s' % (n, name or '(ריקה)'))
        n = dialog.select('%s - %s' % (HEADING, tab_name), names)
        if n < 0:
            return
        n += 1
        has = bool(xbmc.getInfoLabel('Skin.String(%s)' % setting(tab, n, 'path')))
        actions = ['בחירת מקור', 'שינוי שם', 'מחיקת השורה'] if has else ['בחירת מקור']
        a = dialog.select('שורה %d' % n, actions)
        if a == 0:
            path = pick_source(dialog)
            if path:
                current = xbmc.getInfoLabel('Skin.String(%s)' % setting(tab, n, 'name'))
                name = dialog.input('שם השורה', current or 'השורה שלי')
                xbmc.executebuiltin('Skin.SetString(%s,%s)' % (setting(tab, n, 'name'), clean_name(name or 'השורה שלי')))
                xbmc.executebuiltin('Skin.SetString(%s,%s)' % (setting(tab, n, 'path'), quoted(path)))
        elif a == 1:
            current = xbmc.getInfoLabel('Skin.String(%s)' % setting(tab, n, 'name'))
            name = dialog.input('שם השורה', current)
            if name:
                xbmc.executebuiltin('Skin.SetString(%s,%s)' % (setting(tab, n, 'name'), clean_name(name)))
        elif a == 2:
            xbmc.executebuiltin('Skin.Reset(%s)' % setting(tab, n, 'path'))
            xbmc.executebuiltin('Skin.Reset(%s)' % setting(tab, n, 'name'))
        xbmc.sleep(300)
