"""The menu editor of the Onyx home (Wizard 0.5.29 / Onyx 1.0.28): the settings tile "עריכת התפריט", and in the skin
settings Homepage -> "Home menus customizer" (here) / "Home media shelf customizer" (here, at the rows).

A viewer, via the owner, Nov 2026, showing a mod of Onyx 1.0.26 his own Claude made -- the original Onyx's Homepage
category back, with "the order of the buttons on the top bar, renaming, hiding, buttons of your own, and shortcuts
under each button (adding, moving and hiding the build's)": "I'd be glad if you put it in yours, because I want to
work only with your skin, updates included".

What the skin reads (tools/skin_onyx/gen_home.py; extras/povil_menu.json describes the bar and the chips):
  * the bar: POVILBarOrdered + POVILBar_<place> (a tab id in each place), POVILTabName_<id> (a tab's own name),
    POVILHideTab_<id> (off the bar, as onyx_tabs.py has it), POVILTabOwn_<n>_path / _cmd / _name (a button of the
    viewer's own: a folder in the Videos window, or a command);
  * the chips: POVILChip_<tab>_<n>_path / _cmd / _name / _at (start / mid / end), POVILHideChip_<tab>_<n>.
At most NINE buttons stand on the bar: a button of the viewer's own takes the place of one he took off -- the bar is
as wide as it always was.
"""
import json

MENU_FILE = 'special://home/addons/skin.povil.onyx/extras/povil_menu.json'
HEADING = 'עריכת התפריט'
MAX_ON_BAR = 9
CHAR_W = 21                 # about one letter of the bar's font, in pixels: a tab's name fits its button
POINTS = (('start', 'בהתחלה (מימין)'), ('mid', 'אחרי השירותים'), ('end', 'בסוף (משמאל)'))
CHIP_TABS = (('movies', 'סרטים'), ('tv', 'סדרות'), ('kids', 'ילדים'), ('favourites', 'מועדפים'))
FALLBACK = {
    'bar': ['movies', 'tv', 'continue', 'israeli', 'live', 'kids', 'favourites', 'search', 'settings'],
    'own_tabs': ['own1', 'own2'], 'places': 11,
    'tabs': {'movies': {'label': 'סרטים', 'width': 146, 'always': True}, 'tv': {'label': 'סדרות', 'width': 140},
             'continue': {'label': 'המשך צפייה', 'width': 220}, 'israeli': {'label': 'ישראלי', 'width': 146},
             'live': {'label': 'שידור חי', 'width': 166}, 'kids': {'label': 'ילדים', 'width': 140},
             'favourites': {'label': 'מועדפים', 'width': 170}, 'search': {'label': 'חיפוש', 'width': 146},
             'settings': {'label': 'הגדרות', 'width': 146, 'always': True},
             'own1': {'label': '', 'width': 140}, 'own2': {'label': '', 'width': 140}},
    'chips': {}, 'own_chips': 6}


def menu(read_file=None):
    """The skin's description of its bar and chips (extras/povil_menu.json); FALLBACK when it cannot be read."""
    try:
        if read_file is None:
            import xbmcvfs
            with open(xbmcvfs.translatePath(MENU_FILE), encoding='utf-8') as handle:
                return json.load(handle)
        return json.loads(read_file())
    except Exception:
        return FALLBACK


def skin_quote(value):
    """A value for Skin.SetString that keeps its commas and quotes (QA Kodi: quoted, inner quotes escaped). A
    backslash right before a quote -- the last one of a Windows folder -- is left out: before the escaped quote
    Kodi would read the two as one escaped backslash and cut the command there (the reviewer); a folder opens
    without it."""
    import re
    return '"%s"' % re.sub(r'\\+(?=")', '', value).replace('"', '\\"')


# ---------------------------------------------------------------- the bar
class Bar(object):
    def __init__(self, data, read, visible, run):
        self.data, self.read, self.visible, self.run = data, read, visible, run

    def own_set(self, tab_id):
        n = tab_id[3:]
        return bool(self.read('Skin.String(POVILTabOwn_%s_path)' % n) or self.read('Skin.String(POVILTabOwn_%s_cmd)' % n))

    def order(self):
        """The tabs in their places (own buttons that have nothing to do left out), every build tab once."""
        bar, own = self.data['bar'], self.data['own_tabs']
        valid = set(bar) | set(own)
        if self.visible('Skin.HasSetting(POVILBarOrdered)'):
            got = [self.read('Skin.String(POVILBar_%d)' % p) for p in range(self.data['places'])]
        else:
            got = list(bar)
        out = []
        for tab_id in got:
            if tab_id in valid and tab_id not in out and (tab_id in bar or self.own_set(tab_id)):
                out.append(tab_id)
        out += [tab_id for tab_id in bar if tab_id not in out]
        out += [tab_id for tab_id in own if tab_id not in out and self.own_set(tab_id)]
        return out

    def write(self, order):
        for p in range(self.data['places']):
            if p < len(order):
                self.run('Skin.SetString(POVILBar_%d,%s)' % (p, order[p]))
            else:
                self.run('Skin.Reset(POVILBar_%d)' % p)
        self.run('Skin.SetBool(POVILBarOrdered)')

    def hidden(self, tab_id):
        return self.visible('Skin.HasSetting(POVILHideTab_%s)' % tab_id)

    def name(self, tab_id):
        if tab_id in self.data['own_tabs']:
            return self.read('Skin.String(POVILTabOwn_%s_name)' % tab_id[3:]) or 'כפתור משלי'
        return self.read('Skin.String(POVILTabName_%s)' % tab_id) or self.data['tabs'][tab_id]['label']

    def on_bar(self, order=None):
        return [t for t in (order or self.order()) if not self.hidden(t)]

    def longest(self, tab_id):
        return max(3, (int(self.data['tabs'].get(tab_id, {}).get('width') or 140) - 16) // CHAR_W)

    def reset(self):
        for p in range(self.data['places']):
            self.run('Skin.Reset(POVILBar_%d)' % p)
        self.run('Skin.Reset(POVILBarOrdered)')
        for tab_id in list(self.data['bar']) + list(self.data['own_tabs']):
            self.run('Skin.Reset(POVILTabName_%s)' % tab_id)
            self.run('Skin.Reset(POVILHideTab_%s)' % tab_id)
        for tab_id in self.data['own_tabs']:
            for part in ('path', 'cmd', 'name'):
                self.run('Skin.Reset(POVILTabOwn_%s_%s)' % (tab_id[3:], part))


def button_id(tab_id, read, visible, data=None):
    """The id of a tab's button where it stands now (gen_home.py bar_button: 9600 + place * 16 + its place in
    bar + own_tabs) -- a builtin from Python is carried out without the skin's $VAR (QA Kodi: SetFocus($VAR[..]) from
    the Wizard did nothing). A skin before Onyx 1.0.28 has the films' button at 9010."""
    if visible('Control.IsVisible(9010)'):
        return 9010
    data = data or menu()
    ids = list(data['bar']) + list(data['own_tabs'])
    if tab_id not in ids:
        return None
    if visible('Skin.HasSetting(POVILBarOrdered)'):
        for p in range(int(data['places'])):
            if read('Skin.String(POVILBar_%d)' % p) == tab_id:
                return 9600 + p * 16 + ids.index(tab_id)
        return None
    return 9600 + data['bar'].index(tab_id) * 16 + ids.index(tab_id) if tab_id in data['bar'] else None


def move(order, place, step):
    """The order with the tab at `place` moved `step` places (-1: to the right, earlier); unchanged at an edge."""
    to = place + step
    if not 0 <= place < len(order) or not 0 <= to < len(order):
        return list(order)
    order = list(order)
    order[place], order[to] = order[to], order[place]
    return order


def clean_name(name, default):
    for ch in ',()"[]':
        name = name.replace(ch, ' ')
    return ' '.join(name.split()) or default


# ---------------------------------------------------------------- what a chip or a button does
def pick_target(dialog, rpc, heading='מה הכפתור יפתח?'):
    """{'path': folder} (opened in the Videos window) or {'cmd': builtin} -- or None."""
    kinds =['ספריית הווידאו של קודי או תיקייה', 'מועדף של קודי', 'הפעלת תוסף או תוכנה', 'ספריית המוזיקה או תיקיית מוזיקה',
             'טלוויזיה חיה ורדיו', 'כתובת או פקודה ידנית']
    k = dialog.select(heading, kinds)
    if k < 0:
        return None
    if k == 0:
        from resources.libs import custom_rows
        path = custom_rows.pick_source(dialog, 'הכפתור', favourites=False)
        return {'path': path} if path else None
    if k == 1:
        favs = favourites(rpc)
        if not favs:
            dialog.ok(HEADING, 'אין מועדפים בקודי.')
            return None
        f = dialog.select('מועדף', [title for title, _cmd in favs])
        return {'cmd': favs[f][1], 'name': favs[f][0]} if f >= 0 else None
    if k == 2:
        addons = addons_list(rpc)
        if not addons:
            return None
        a = dialog.select('תוסף', [name for name, _id in addons])
        return {'cmd': 'RunAddon(%s)' % addons[a][1], 'name': addons[a][0]} if a >= 0 else None
    if k == 3:
        m = dialog.select('מוזיקה', ['ספריית המוזיקה של קודי', 'תיקיית מוזיקה (דפדוף)'])
        if m == 0:
            return {'cmd': 'ActivateWindow(Music,musicdb://,return)', 'name': 'מוזיקה'}
        if m == 1:
            path = dialog.browse(0, 'תיקיית מוזיקה', 'music', '', False, False, '')
            return {'cmd': 'ActivateWindow(Music,"%s",return)' % path.rstrip('\\'), 'name': 'מוזיקה'} if path else None
        return None
    if k == 4:
        live = (('ערוצי טלוויזיה', 'ActivateWindow(TVChannels)'), ('מדריך שידורים', 'ActivateWindow(TVGuide)'),
                ('הקלטות', 'ActivateWindow(TVRecordings)'), ('ערוצי רדיו', 'ActivateWindow(RadioChannels)'))
        p = dialog.select('טלוויזיה חיה ורדיו', [name for name, _c in live])
        return {'cmd': live[p][1], 'name': live[p][0]} if p >= 0 else None
    text = (dialog.input('כתובת (plugin://, videodb://, תיקייה) או פקודה של קודי') or '').strip()
    if not text:
        return None
    if '://' not in text.split('(')[0] and text.endswith(')') and '(' in text:
        return {'cmd': text}
    return {'path': text}


def favourites(rpc):
    """(title, command) of every Kodi favourite."""
    reply = json.loads(rpc(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Favourites.GetFavourites',
                                       'params': {'properties': ['window', 'windowparameter', 'path']}})))
    out = []
    for fav in (reply.get('result') or {}).get('favourites') or []:
        kind, title = fav.get('type'), fav.get('title') or ''
        if kind == 'window' and fav.get('windowparameter'):
            cmd = 'ActivateWindow(%s,"%s",return)' % (fav.get('window'), fav['windowparameter'])
        elif kind == 'window':
            cmd = 'ActivateWindow(%s)' % fav.get('window')
        elif kind == 'media' and fav.get('path'):
            cmd = 'PlayMedia("%s")' % fav['path']
        elif kind == 'script' and fav.get('path'):
            cmd = 'RunScript("%s")' % fav['path']
        elif (fav.get('path') or '').endswith(')'):
            cmd = fav['path']
        else:
            continue
        out.append((title, cmd))
    return out


def addons_list(rpc):
    """(name, id) of the enabled video and program add-ons."""
    out = []
    for content in ('video', 'executable'):
        reply = json.loads(rpc(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.GetAddons',
                                           'params': {'content': content, 'enabled': True, 'properties': ['name']}})))
        for a in (reply.get('result') or {}).get('addons') or []:
            if a.get('addonid') and a['addonid'] not in [i for _n, i in out]:
                out.append((a.get('name') or a['addonid'], a['addonid']))
    return sorted(out, key=lambda item: item[0].lower())


def write_target(key, target, run):
    """POVIL..._path or _cmd (the other cleared)."""
    if target.get('cmd'):
        run('Skin.SetString(%s_cmd,%s)' % (key, skin_quote(target['cmd'])))
        run('Skin.Reset(%s_path)' % key)
    else:
        from resources.libs import custom_rows
        run('Skin.SetString(%s_path,%s)' % (key, custom_rows.quoted(target['path'])))
        run('Skin.Reset(%s_cmd)' % key)


# ---------------------------------------------------------------- the dialogs
def choose(part=None):
    import xbmc
    import xbmcgui
    dialog = xbmcgui.Dialog()
    data = menu()
    bar = Bar(data, xbmc.getInfoLabel, xbmc.getCondVisibility, xbmc.executebuiltin)
    if part == 'rows':
        return rows(dialog)
    while True:
        a = dialog.select(HEADING, ['סידור הכפתורים בסרגל העליון', 'הוספת כפתור משלי לסרגל', 'הקיצורים מתחת לכפתורים',
                                    'השורות במסך הבית', 'החזרת הסרגל לברירת המחדל'])
        if a < 0:
            return
        if a == 0:
            arrange(dialog, bar)
        elif a == 1:
            add_own_tab(dialog, bar, xbmc.executeJSONRPC)
        elif a == 2:
            chips(dialog, data, xbmc.getInfoLabel, xbmc.getCondVisibility, xbmc.executebuiltin, xbmc.executeJSONRPC)
        elif a == 3:
            rows(dialog)
        elif dialog.yesno(HEADING, 'להחזיר את הסרגל העליון לסדר, לשמות ולכפתורים של הבילד?\n'
                                   'כפתורים משלכם בסרגל יימחקו. הקיצורים והשורות נשארים.'):
            bar.reset()
        xbmc.sleep(300)


def arrange(dialog, bar):
    """The bar's order, names and the ones off it."""
    import xbmc
    order = bar.order()
    while True:
        lines = ['%d. %s%s' % (n + 1, bar.name(t), ' (מוסתר)' if bar.hidden(t) else '') for n, t in enumerate(order)]
        s = dialog.select('הסרגל העליון (1 = הימני)', lines)
        if s < 0:
            return
        tab_id = order[s]
        own = tab_id in bar.data['own_tabs']
        always = bar.data['tabs'].get(tab_id, {}).get('always')
        actions = []
        if s > 0:
            actions.append(('right', 'הזזה ימינה'))
        if s < len(order) - 1:
            actions.append(('left', 'הזזה שמאלה'))
        actions.append(('rename', 'שינוי שם'))
        if not own and bar.read('Skin.String(POVILTabName_%s)' % tab_id):
            actions.append(('original', 'חזרה לשם המקורי'))
        if not always:
            actions.append(('show', 'הצגה בסרגל') if bar.hidden(tab_id) else ('hide', 'הסתרה מהסרגל'))
        if own:
            actions += [('target', 'שינוי מה שהכפתור פותח'), ('delete', 'מחיקת הכפתור')]
        a = dialog.select(bar.name(tab_id), [label for _k, label in actions])
        if a < 0:
            continue
        what = actions[a][0]
        if what in ('right', 'left'):
            order = move(order, s, -1 if what == 'right' else 1)
            bar.write(order)
        elif what == 'rename':
            longest = bar.longest(tab_id)
            name = dialog.input('שם הכפתור (עד %d אותיות)' % longest, bar.name(tab_id))
            if name:
                name = clean_name(name, bar.name(tab_id))[:longest]
                key = ('POVILTabOwn_%s_name' % tab_id[3:]) if own else ('POVILTabName_%s' % tab_id)
                bar.run('Skin.SetString(%s,%s)' % (key, name))
        elif what == 'original':
            bar.run('Skin.Reset(POVILTabName_%s)' % tab_id)
        elif what == 'hide':
            bar.run('Skin.SetBool(POVILHideTab_%s)' % tab_id)
            home_back(tab_id)
        elif what == 'show':
            if len(bar.on_bar(order)) >= MAX_ON_BAR:
                dialog.ok(HEADING, 'בסרגל יש מקום לתשעה כפתורים. הסתירו כפתור אחר קודם.')
            else:
                bar.run('Skin.Reset(POVILHideTab_%s)' % tab_id)
        elif what == 'target':
            target = pick_target(dialog, xbmc.executeJSONRPC)
            if target:
                write_target('POVILTabOwn_%s' % tab_id[3:], target, bar.run)
        elif what == 'delete':
            for part in ('path', 'cmd', 'name'):
                bar.run('Skin.Reset(POVILTabOwn_%s_%s)' % (tab_id[3:], part))
            bar.run('Skin.Reset(POVILHideTab_%s)' % tab_id)
            order = [t for t in order if t != tab_id]
            bar.write(order)
            home_back(tab_id)
        xbmc.sleep(250)


def home_back(tab_id):
    """The screen that was up has left the bar: the home goes back to the films."""
    try:
        import xbmc
        import xbmcgui
        home = xbmcgui.Window(10000)
        if home.getProperty('povil.tab') == tab_id:
            home.setProperty('povil.tab', 'movies')
            films = button_id('movies', xbmc.getInfoLabel, xbmc.getCondVisibility)
            if films:
                xbmc.executebuiltin('SetFocus(%d)' % films)
    except Exception:
        pass


def add_own_tab(dialog, bar, rpc):
    order = bar.order()
    free = [t for t in bar.data['own_tabs'] if not bar.own_set(t)]
    if not free:
        dialog.ok(HEADING, 'יש כבר %d כפתורים משלכם בסרגל. אפשר לשנות או למחוק אותם ב"סידור הכפתורים".' % len(bar.data['own_tabs']))
        return
    if len(bar.on_bar(order)) >= MAX_ON_BAR:
        dialog.ok(HEADING, 'בסרגל יש מקום לתשעה כפתורים. הסתירו כפתור (בסידור הכפתורים) כדי לפנות מקום.')
        return
    target = pick_target(dialog, rpc)
    if not target:
        return
    tab_id = free[0]
    longest = bar.longest(tab_id)
    name = dialog.input('שם הכפתור (עד %d אותיות)' % longest, (target.get('name') or '')[:longest])
    name = clean_name(name or '', 'שלי')[:longest]
    key = 'POVILTabOwn_%s' % tab_id[3:]
    write_target(key, target, bar.run)
    bar.run('Skin.SetString(%s_name,%s)' % (key, name))
    bar.run('Skin.Reset(POVILHideTab_%s)' % tab_id)
    # before the settings, the leftmost
    order = [t for t in order if t != tab_id]
    at = order.index('settings') if 'settings' in order else len(order)
    order.insert(at, tab_id)
    bar.write(order)


# ---------------------------------------------------------------- the chips under each tab
def chips(dialog, data, read, visible, run, rpc):
    t = dialog.select('לאיזה כפתור?', [name for _t, name in CHIP_TABS])
    if t < 0:
        return
    tab, tab_name = CHIP_TABS[t]
    info = (data.get('chips') or {}).get(tab) or {}
    count = int(data.get('own_chips') or 6)
    while True:
        mine = []
        for n in range(1, count + 1):
            key = 'POVILChip_%s_%d' % (tab, n)
            if read('Skin.String(%s_path)' % key) or read('Skin.String(%s_cmd)' % key):
                mine.append(n)
        lines = ['%s (%s)' % (read('Skin.String(POVILChip_%s_%d_name)' % (tab, n)) or 'הקיצור שלי', point_name(read, tab, n, info))
                 for n in mine]
        lines += ['+ הוספת קיצור', 'הקיצורים של הבילד (הסתרה)']
        s = dialog.select('הקיצורים מתחת ל«%s»' % tab_name, lines)
        if s < 0:
            return
        if s < len(mine):
            own_chip(dialog, tab, mine[s], info, read, run, rpc)
        elif s == len(mine):
            free = [n for n in range(1, count + 1) if n not in mine]
            if not free:
                dialog.ok(HEADING, 'יש כבר %d קיצורים משלכם מתחת לכפתור הזה.' % count)
                continue
            target = pick_target(dialog, rpc, 'מה הקיצור יפתח?')
            if not target:
                continue
            key = 'POVILChip_%s_%d' % (tab, free[0])
            name = dialog.input('שם הקיצור', target.get('name') or 'הקיצור שלי')
            write_target(key, target, run)
            run('Skin.SetString(%s_name,%s)' % (key, clean_name(name or '', 'הקיצור שלי')))
        else:
            build_chips(dialog, tab, tab_name, info, visible, run, mine)
        import xbmc
        xbmc.sleep(250)


def point_name(read, tab, n, info):
    at = read('Skin.String(POVILChip_%s_%d_at)' % (tab, n)) or ('mid' if info.get('mid') else 'end')
    if at == 'mid' and not info.get('mid'):
        at = 'end'
    return dict(POINTS)[at]


def own_chip(dialog, tab, n, info, read, run, rpc):
    key = 'POVILChip_%s_%d' % (tab, n)
    actions = ['שינוי מה שהקיצור פותח', 'שינוי שם', 'מיקום', 'מחיקת הקיצור']
    a = dialog.select(read('Skin.String(%s_name)' % key) or 'הקיצור שלי', actions)
    if a == 0:
        target = pick_target(dialog, rpc, 'מה הקיצור יפתח?')
        if target:
            write_target(key, target, run)
    elif a == 1:
        name = dialog.input('שם הקיצור', read('Skin.String(%s_name)' % key))
        if name:
            run('Skin.SetString(%s_name,%s)' % (key, clean_name(name, 'הקיצור שלי')))
    elif a == 2:
        points = [(k, label) for k, label in POINTS if k != 'mid' or info.get('mid')]
        p = dialog.select('איפה הקיצור יעמוד?', [label for _k, label in points])
        if p >= 0:
            run('Skin.SetString(%s_at,%s)' % (key, points[p][0]))
    elif a == 3:
        for part in ('path', 'cmd', 'name', 'at'):
            run('Skin.Reset(%s_%s)' % (key, part))


def build_chips(dialog, tab, tab_name, info, visible, run, mine):
    """The build's chips of a screen: the ones marked are hidden. At least one chip stays on the screen."""
    labels = info.get('build') or []
    if not labels:
        return
    hidden = [n for n in range(len(labels)) if visible('Skin.HasSetting(POVILHideChip_%s_%d)' % (tab, n))]
    picked = dialog.multiselect('הקיצורים של הבילד מתחת ל«%s» (מסומן = מוסתר)' % tab_name, labels, preselect=hidden)
    if picked is None:
        return
    if len(picked) >= len(labels) and not mine:
        dialog.ok(HEADING, 'השאירו לפחות קיצור אחד מתחת לכפתור (או הוסיפו קיצור משלכם קודם).')
        return
    for n in range(len(labels)):
        run('Skin.%s(POVILHideChip_%s_%d)' % ('SetBool' if n in picked else 'Reset', tab, n))


def rows(dialog):
    """The rows of the home's screens: the viewer's own, and their order."""
    a = dialog.select('השורות במסך הבית', ['השורות שלי (הוספה ומקור)', 'סדר השורות'])
    if a == 0:
        from resources.libs import custom_rows
        custom_rows.choose(kinds=('Row',))
    elif a == 1:
        from resources.libs import home_rows
        home_rows.choose()
