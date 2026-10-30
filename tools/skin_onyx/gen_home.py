# -*- coding: utf-8 -*-
"""Generate the Kodi POV IL home of skin.povil.onyx.

    python gen_home.py ../../skin.povil.onyx

Writes xml/Home.xml and xml/Includes_POVIL_Home.xml. Edit the TABS table
below, not the generated XML.

Layout (1920x1080): tabs top right (right to left, the first tab is the
rightmost), clock top left, a hero for the focused item on the right
(fanart backdrop, clear logo or title, details, plot), shortcut chips under
it, then up to three rows per tab. Rows of a tab only exist while that tab is
selected, so a tab's lists load the first time it is shown and stay loaded.
"""
import os
import sys
from urllib.parse import quote
from xml.sax.saxutils import escape

from paths import IDAN

NL = chr(10)

# ---------------------------------------------------------------- paths
POV = 'plugin://plugin.video.pov/'
UMB = 'plugin://plugin.video.umbrella/'
# MoranSubs' search engine choice ("מנוע החיפוש"; search_provider.py), read by
# Kodi itself at click time: switching needs no skin rewrite or reload.
SEARCH_IN_UMBRELLA = ('String.IsEqual(Addon.SettingStr(service.subtitles.kodipovilai,search_provider),umbrella)'
                      ' + System.AddonIsEnabled(plugin.video.umbrella)')


def pov_movies(action, **kw):
    q = '&'.join(['mode=build_movie_list', 'action=' + action] + ['%s=%s' % kv for kv in kw.items()])
    return POV + '?' + q


def pov_tv(action, **kw):
    q = '&'.join(['mode=build_tvshow_list', 'action=' + action] + ['%s=%s' % kv for kv in kw.items()])
    return POV + '?' + q


def pov_mode(mode, **kw):
    return POV + '?' + '&'.join(['mode=' + mode] + ['%s=%s' % kv for kv in kw.items()])


def videos(path):
    return 'ActivateWindow(Videos,"%s",return)' % path


def plugin_run(path):
    return 'RunPlugin(%s)' % path


WIZARD = 'plugin://plugin.program.kodipovilwizard/'
# MDBList connected: the Wizard's visibility manager flags each service on the home
# window (povil.svc.<name>) when it reads the accounts; its rows are the fallback
MDBLIST_ON = ('[String.IsEqual(Window(home).Property(povil.svc.mdblist),1)'
              ' | Integer.IsGreater(Container(5064).NumItems,0) | Integer.IsGreater(Container(5065).NumItems,0)]')
# Kodi's own favourites list, off screen: only its count is read (the favourites row)
FAV_COUNT = 9890
MOVIE_GENRE = lambda gid: videos(pov_movies('tmdb_movies_genres', genre_id=gid))
TV_GENRE = lambda gid: videos(pov_tv('tmdb_tv_genres', genre_id=gid))
MOVIE_NET = lambda nid: videos(pov_movies('tmdb_movies_networks', network_id=nid))
TV_NET = lambda nid: videos(pov_tv('tmdb_tv_networks', network_id=nid))
IDAN_KESHET_VOD = ('plugin://plugin.video.idanplus/?name=%5BB%5D%D7%9B%D7%9C+%D7%94%D7%AA%D7%9B%D7%A0%D7%99%D7%95%D7%AA'
                   '%5B%2FB%5D&url=https%253A%252F%252Fwww.mako.co.il%252Fmako-vod-index&mode=1&iconimage=mako.png'
                   '&module=keshet&moredata=')
# Kan 11's "all programs" (its root menu is folders with one logo, and a sort switch)
IDAN_KAN_VOD = ('plugin://plugin.video.idanplus/?name=%5BB%5D%D7%9B%D7%9C+%D7%94%D7%AA%D7%95%D7%9B%D7%A0%D7%99%D7%95%'
                'D7%AA%5B%2FB%5D&url=https%253A%252F%252Fwww.kan.org.il%252Flobby%252Fkan11&mode=1&iconimage=https%25'
                '3A%252F%252Fraw.githubusercontent.com%252FFishenzon%252Frepo%252Fmaster%252Fplugin.video.idanplus%25'
                '2Fimages%252Fkan.jpg&module=kan&moredata=%25D7%259B%25D7%2590%25D7%259F%2B11__4444')
IDAN_RESHET_VOD = ('plugin://plugin.video.idanplus/?iconimage=13.jpg&mode=0&module=reshet&moredata&name=%5bB%5d%d7%9b'
                   '%d7%9c%20%d7%94%d7%aa%d7%9b%d7%a0%d7%99%d7%95%d7%aa%5b%2fB%5d&url=https%253A%252F%252F13tv.co.il'
                   '%252Fallshows%252Fscreen%252F1170108%252F')

# ---------------------------------------------------------------- tabs
# rows: (title, content path, layout, optional). layout: poster | landscape | square.
# optional rows (that can be empty) go last, and their title only shows with items.
# chips: (label, onclick[, visible condition]) - the first chip is the rightmost.
TABS = [
    dict(id='movies', label='סרטים', click=videos(pov_mode('navigator.main', action='MovieList')),
         blurb='סרטים חדשים, פופולריים וכל מה שאתם באמצע לראות.',
         rows=[('פופולריים עכשיו', pov_movies('tmdb_movies_popular'), 'poster', False),
               ('טרנדיים השבוע', pov_movies('tmdb_movies_trending'), 'landscape', False),
               ('ממשיכים לצפות', pov_movies('in_progress_movies'), 'landscape', True)],
         chips=[('נטפליקס', MOVIE_NET(8)), ('דיסני+', MOVIE_NET(337)), ('בכורות', videos(pov_movies('tmdb_movies_premieres'))),
                ('אקשן', MOVIE_GENRE(28)), ('קומדיה', MOVIE_GENRE(35)), ('דרמה', MOVIE_GENRE(18)),
                ('מתח', MOVIE_GENRE(53)), ('אימה', MOVIE_GENRE(27)), ('מדע בדיוני', MOVIE_GENRE(878)),
                ('כל הסרטים', videos(pov_mode('navigator.main', action='MovieList'))),
                ('Umbrella', videos(UMB + '?action=movieNavigator'), 'System.HasAddon(plugin.video.umbrella)')]),
    dict(id='tv', label='סדרות', click=videos(pov_mode('navigator.main', action='TVShowList')),
         blurb='הסדרות שכולם מדברים עליהן, והפרק הבא שלכם.',
         rows=[('טרנדיות עכשיו', pov_tv('trakt_tv_trending'), 'poster', False),
               ('פופולריות', pov_tv('tmdb_tv_popular'), 'landscape', False),
               ('הפרק הבא', pov_mode('build_next_episode'), 'landscape', True)],
         chips=[('נטפליקס', TV_NET(213)), ('דיסני+', TV_NET(2739)),
                ('ישראליות', videos(pov_tv('tmdb_tv_languages', language='he'))),
                ('דרמה', TV_GENRE(18)), ('קומדיה', TV_GENRE(35)), ('פשע', TV_GENRE(80)),
                ('מסתורין', TV_GENRE(9648)), ('מדע בדיוני', TV_GENRE(10765)), ('ריאליטי', TV_GENRE(10764)),
                ('כל הסדרות', videos(pov_mode('navigator.main', action='TVShowList'))),
                ('Umbrella', videos(UMB + '?action=tvNavigator'), 'System.HasAddon(plugin.video.umbrella)')]),
    dict(id='israeli', label='ישראלי', click=videos('plugin://plugin.video.idanplus/'),
         blurb='כאן, קשת, רשת ועוד: התוכניות והסדרות הישראליות.',
         # each row in its pictures' shape: Keshet's are posters (420x600), Reshet's
         # 16:9 (1280x720), Kan's posters 2:3 (239x360 / 1200x1800)
         rows=[('קשת 12', IDAN_KESHET_VOD, 'poster', False),
               ('רשת 13', IDAN_RESHET_VOD, 'landscape', False),
               ('כאן 11', IDAN_KAN_VOD, 'poster', False)],
         chips=[('כאן 11', videos(IDAN['kan11'])), ('קשת 12', videos(IDAN['keshet12'])),
                ('רשת 13', videos(IDAN['reshet13'])), ('עכשיו 14', videos(IDAN['now14'])),
                ('i24NEWS', videos(IDAN['i24'])), ('ערוץ 9', videos(IDAN['ch9'])),
                ('מוסיקה 24', videos(IDAN['music24'])), ('חיפוש', videos(IDAN['idan_search']))]),
    dict(id='live', label='שידור חי', click=videos(IDAN['idan_live']),
         blurb='ערוצי הטלוויזיה והרדיו בשידור חי.',
         rows=[('ערוצים', IDAN['idan_live'], 'square', False),
               ('רדיו', IDAN['radio'], 'square', False)],
         chips=[('ערוצים', videos(IDAN['idan_live'])), ('רדיו', videos(IDAN['radio'])),
                ('ספורט 1', videos(IDAN['sport1'])), ('Eco99', videos(IDAN['eco99'])),
                ('100FM', videos(IDAN['fm100'])),
                ('מדריך שידורים', 'ActivateWindow(TVChannels)', 'PVR.HasTVChannels')]),
    dict(id='kids', label='ילדים', click=MOVIE_GENRE(10751),
         blurb='סרטים, סדרות ותוכניות לכל המשפחה.',
         rows=[('סרטים לכל המשפחה', pov_movies('tmdb_movies_genres', genre_id=10751), 'poster', False),
               ('סרטי אנימציה', pov_movies('tmdb_movies_genres', genre_id=16), 'poster', False),
               ('קטנטנים', IDAN['kan_tots'], 'landscape', False)],
         chips=[('קטנטנים', videos(IDAN['kan_tots'])), ('ילדים ונוער', videos(IDAN['kan_kids'])),
                ('ניקלודיאון', videos(IDAN['nick'])), ('אנימציה', MOVIE_GENRE(16)),
                ('משפחה', MOVIE_GENRE(10751)),
                ('אנימה', videos(IDAN['otaku']), 'System.HasAddon(plugin.video.otaku)')]),
    dict(id='favourites', label='מועדפים', click='ActivateWindow(favouritesbrowser)',
         blurb='הקיצורים והרשימות ששמרתם.',
         # Kodi's favourites through the Wizard (favourites_row.py): last first, so the
         # first favourite starts the row on the right, like every other row
         # (r= the count of Kodi's own favourites list, FAV_COUNT: Kodi refreshes that
         # one when a favourite is added or removed, and a new count reloads the row)
         # (t= set when the home comes back from Kodi's favourites window, where a
         # favourite is renamed or moved without changing the count)
         rows=[('המועדפים שלי', WIZARD + '?mode=favourites_row&r=$INFO[Container(%d).NumItems]&t=$INFO[Window(home).Property(povil.fav.t)]' % FAV_COUNT, 'square', True),
               ('סרטים שמורים', pov_movies('favorites_movies'), 'poster', True),
               ('סדרות שמורות', pov_tv('favorites_tvshows'), 'poster', True),
               ('הסרטים שלי (MDBList)', pov_movies('mdblist_my_movies'), 'poster', True),
               ('הסדרות שלי (MDBList)', pov_tv('mdblist_my_tvshows'), 'poster', True)],
         # MDBList's chips once its rows have items (a connected account): no
         # settings read on every frame
         chips=[('סרטים ב-Trakt', videos(pov_movies('trakt_my_movies'))),
                ('סדרות ב-Trakt', videos(pov_tv('trakt_my_tvshows'))),
                ('סרטים ב-MDBList', videos(pov_movies('mdblist_my_movies')), MDBLIST_ON),
                ('סדרות ב-MDBList', videos(pov_tv('mdblist_my_tvshows')), MDBLIST_ON),
                ('הרשימות שלי', videos(pov_mode('navigator.my_content'))),
                ('כל המועדפים', 'ActivateWindow(favouritesbrowser)')]),
    dict(id='search', label='חיפוש', click=videos(pov_mode('navigator.search')),
         click_alt=(SEARCH_IN_UMBRELLA, videos(UMB + '?action=tools_searchNavigator')),
         blurb='סרטים, סדרות, שחקנים ותוכן ישראלי. במקלדת יש כפתור חיפוש קולי.',
         rows=[('חיפושי סרטים אחרונים', pov_mode('search_history', action='movie'), 'square', True),
               ('חיפושי סדרות אחרונים', pov_mode('search_history', action='tvshow'), 'square', True)],
         chips=[('חיפוש ב-POV', videos(pov_mode('navigator.search'))),
                ('חיפוש ב-Umbrella', videos(UMB + '?action=tools_searchNavigator'), 'System.HasAddon(plugin.video.umbrella)'),
                ('תוכן ישראלי', videos(IDAN['idan_search'])),
                ('YouTube', videos('plugin://plugin.video.youtube/kodion/search/list/'), 'System.HasAddon(plugin.video.youtube)')]),
    dict(id='settings', label='הגדרות', click='ActivateWindow(Settings)',
         blurb='הוויזארד, הכתוביות, POV ו-Umbrella במקום אחד.',
         rows=[('קיצורי דרך', 'static:settings', 'square', False)],
         chips=[]),
]

SETTINGS_ITEMS = [
    # label, icon, onclick, visible
    ('הוויזארד', '$INFO[System.AddonIcon(plugin.program.kodipovilwizard)]', videos(WIZARD), ''),
    ('החלפת סקין', '$INFO[System.AddonIcon(plugin.program.kodipovilwizard)]', plugin_run(WIZARD + '?mode=profile_skin'), ''),
    ('כתוביות', '$INFO[System.AddonIcon(service.subtitles.kodipovilai)]', 'Addon.OpenSettings(service.subtitles.kodipovilai)', 'System.HasAddon(service.subtitles.kodipovilai)'),
    ('מנוע החיפוש', 'special://home/addons/plugin.video.pov/resources/skins/Default/media/search.png',
     'RunScript(service.subtitles.kodipovilai,action=search_provider)', 'System.HasAddon(service.subtitles.kodipovilai)'),
    ('הגדרות POV', '$INFO[System.AddonIcon(plugin.video.pov)]', 'Addon.OpenSettings(plugin.video.pov)', 'System.HasAddon(plugin.video.pov)'),
    ('הגדרות Umbrella', '$INFO[System.AddonIcon(plugin.video.umbrella)]', 'Addon.OpenSettings(plugin.video.umbrella)', 'System.HasAddon(plugin.video.umbrella)'),
    ('הגדרות הסקין', 'DefaultAddonSkin.png', 'ActivateWindow(SkinSettings)', ''),
    ('הגדרות קודי', 'DefaultAddonService.png', 'ActivateWindow(Settings)', ''),
    ('הרחבות', 'DefaultAddonsInstalled.png', 'ActivateWindow(AddonBrowser)', ''),
    ('פרופילים', 'DefaultUser.png', plugin_run(WIZARD + '?mode=profiles'), ''),
    ('כיבוי', 'DefaultAddonProgram.png', 'ActivateWindow(ShutdownMenu)', ''),
]

# ---------------------------------------------------------------- geometry
MARGIN = 90
# A list clips what it draws to its own rectangle: the focused tile's zoom and
# gold glow reach 42 px past the tile. Every list starts PAD before its first
# tile and every item draws its tile PAD in, so nothing is cut at the edges.
PAD = 42
ROWS_Y = 618
TAB_W = 172
GEOM = {
    # list height, row block height (title + list), item size, item spacing
    'poster': dict(list_h=340, block=402, w=196, h=294, step=226),
    'landscape': dict(list_h=300, block=362, w=352, h=198, step=382),
    'square': dict(list_h=290, block=352, w=200, h=200, step=230),
}
GOLD = 'povil_gold'


def tab_cond(tab):
    return 'String.IsEqual(Window(home).Property(povil.tab),%s)' % tab['id']


def tab_button(ti):
    return 9010 + ti



def nav_chain(candidates, fallback=None):
    """[(condition, target)] for the nearest row of `candidates` that has items
    (an empty optional row is hidden: the focus must skip any number of them),
    then `fallback` when none has."""
    has = 'Integer.IsGreater(Container(%d).NumItems,0)'
    chain = []
    for k, target in enumerate(candidates):
        chain.append((' + '.join(['!' + has % c for c in candidates[:k]] + [has % target]), target))
    if fallback is not None:
        chain.append((' + '.join('!' + has % c for c in candidates) or 'true', fallback))
    return chain



def row_focus(ti, ri):
    """The row has the focus -- or nothing has it and the row had it last: on a
    touch screen a touch outside every control (the hero) takes the focus away,
    and the rows and the hero stay where they were (povil.focus, set by every
    focusable control of the home)."""
    rid = row_id(ti, ri)
    return ('[Control.HasFocus(%d) | [String.IsEmpty(System.CurrentControlId) + '
            'String.IsEqual(Window(home).Property(povil.focus),%d)]]' % (rid, rid))


def row_id(ti, ri):
    return 5000 + (ti + 1) * 10 + ri + 1


def chip_ids(ti, tab):
    return [9100 + (ti + 1) * 12 + ci for ci in range(len(tab['chips']))]


# ---------------------------------------------------------------- RTL rows
# The add-on reverses a list whose URL carries povil_rtl=1 and marks its items
# (plugin.program.kodipovilwizard/resources/libs/patches/povil_rtl.py). A timer
# then starts the row on its last item, the original first, on the right.
# The guard property holds the first item's label, so a row moves once per
# load and never when the user walks to its far end.
def named(text, label):
    """POV names a list after its name= parameter (Kodi's Container.FolderName);
    give every POV list the Hebrew name it has in the skin."""
    import re
    def fix(m):
        path = m.group(0)
        if not path.startswith(POV) or 'name=' in path:
            return path
        return path + '&name=' + quote(label)
    return re.sub(r'plugin://plugin\.video\.pov/[^"]*', fix, text)


def is_rtl(path):
    return path.startswith('plugin://') or path.startswith('static:')


def rtl_path(path):
    if not path.startswith('plugin://'):
        return path
    return path + ('&' if '?' in path else '?') + 'povil_rtl=1'


def rtl_waiting(cid, home=True):
    c = 'Container(%d)' % cid if cid else 'Container'
    prop = 'Window(home).Property(povil.rtl.%s)' % (cid or 'view')
    return ('!%(c)s.IsUpdating + Integer.IsGreater(%(c)s.NumItems,1) + Integer.IsEqual(%(c)s.CurrentItem,1)'
            ' + String.IsEqual(%(c)s.ListItemAbsolute(0).Property(povil_rtl),1)'
            # the container's label FIRST: as the second argument Kodi reads
            # Container(id).ListItemAbsolute(0).Label as plain text, the guard never
            # matched, and a row's far end threw the user back to its start
            ' + !String.IsEqual(%(c)s.ListItemAbsolute(0).Label,%(p)s)') % {'c': c, 'p': prop}


def gen_timers():
    x = X()
    x(1, '<!-- POVIL RTL BEGIN: generated by tools/skin_onyx/gen_home.py -->')
    # A swipe on a phone (the touch keymap) names its direction; Onyx moves the focus
    x(1, '<timer>')
    x(2, '<name>povil_swipe</name>')
    x(2, '<start reset="true">!String.IsEmpty(Window(home).Property(povil.swipe))</start>')
    # the finger touched the hero first: nothing has the focus, and Down would go
    # to the window's default (the first tab) -- give it back to where it was
    x(2, '<onstart condition="Window.IsActive(home) + String.IsEmpty(System.CurrentControlId) + !String.IsEmpty(Window(home).Property(povil.focus))">'
         'SetFocus($INFO[Window(home).Property(povil.focus)])</onstart>')
    x(2, '<onstart condition="Window.IsActive(home) + String.IsEqual(Window(home).Property(povil.swipe),down)">Action(Down)</onstart>')
    x(2, '<onstart condition="Window.IsActive(home) + String.IsEqual(Window(home).Property(povil.swipe),up)">Action(Up)</onstart>')
    x(2, '<onstart>ClearProperty(povil.swipe,home)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # The hero's soft wash takes the chosen item's picture once the screen is still (ambient())
    x(1, '<timer>')
    x(2, '<name>povil_blur</name>')
    x(2, '<start reset="true">Window.IsActive(home) + !System.HasModalDialog + System.IdleTime(2) + !String.IsEqual(Control.GetLabel(9803),Window(home).Property(povil.blur))</start>')
    x(2, '<onstart>SetProperty(povil.blur,$INFO[Control.GetLabel(9803)],home)</onstart>')
    x(2, '<onstart>SetProperty(povil.blurpng,$INFO[Control.GetLabel(9804)],home)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # The tabs need no timer: the focused tab button names itself (gen_home tabs),
    # the window's default control is the first tab.
    # A row that came back empty (a failed or cancelled request -- on a phone,
    # switching tabs mid-load; a network blip) asks again after 3 s, twice at
    # most. Only the tab on screen, only rows that are never empty by design.
    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            if not retries(row):
                continue
            rid = row_id(ti, ri)
            prop = 'Window(home).Property(povil.retry.%d)' % rid
            empty = ('!Integer.IsGreater(Container(%d).NumItems,0) + !Container(%d).IsUpdating' % (rid, rid))
            x(1, '<timer>')
            x(2, '<name>povil_retry_%d</name>' % rid)
            x(2, '<start reset="true">%s + Window.IsActive(home) + !String.IsEmpty(Window(home).Property(%s)) + %s + !String.IsEqual(%s,2)</start>'
              % (tab_cond(tab), row_gate(ti, ri), empty, prop))
            x(2, '<stop>Integer.IsGreaterOrEqual(Skin.TimerElapsed(povil_retry_%d),3) | Integer.IsGreater(Container(%d).NumItems,0) | Container(%d).IsUpdating</stop>'
              % (rid, rid, rid))
            # second retry first: the first one's action would satisfy it at once
            x(2, '<onstop condition="%s + String.IsEqual(%s,1)">SetProperty(povil.retry.%d,2,home)</onstop>' % (empty, prop, rid))
            x(2, '<onstop condition="%s + String.IsEmpty(%s)">SetProperty(povil.retry.%d,1,home)</onstop>' % (empty, prop, rid))
            x(1, '</timer>')
    # One per tab: a condition cannot name a property through $INFO
    for tab in TABS:
        if len(tab['rows']) < 2:
            continue
        x(1, '<timer>')
        x(2, '<name>povil_deep_%s</name>' % tab['id'])
        x(2, '<start reset="true">Window.IsActive(home) + %s + !ControlGroup(9000).HasFocus() + !Skin.HasSetting(POVILChild) + '
             'String.IsEmpty(Window(home).Property(povil.deep.%s))</start>' % (tab_cond(tab), tab['id']))
        x(2, '<onstart>SetProperty(povil.deep.%s,1,home)</onstart>' % tab['id'])
        x(2, '<stop>true</stop>')
        x(1, '</timer>')
    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            if not is_rtl(row[1]):
                continue
            rid = row_id(ti, ri)
            x(1, '<timer>')
            x(2, '<name>povil_rtl_%d</name>' % rid)
            x(2, '<start reset="true">Window.IsVisible(home) + %s + %s</start>' % (tab_cond(tab), rtl_waiting(rid)))
            x(2, '<onstart>SetProperty(povil.rtl.%d,$ESCINFO[Container(%d).ListItemAbsolute(0).Label],home)</onstart>' % (rid, rid))
            x(2, '<onstart>Control.Move(%d,-1)</onstart>' % rid)
            x(2, '<stop>true</stop>')
            x(1, '</timer>')
    # The power menu (its items are in right-to-left order): open on the rightmost, once per opening
    x(1, '<timer>')
    x(2, '<name>povil_rtl_powermenu</name>')
    x(2, '<start>Window.IsActive(shutdownmenu) + Integer.IsGreater(Container(9000).NumItems,1)</start>')
    x(2, '<onstart>Control.Move(9000,-1)</onstart>')
    x(2, '<stop>!Window.IsActive(shutdownmenu)</stop>')
    x(1, '</timer>')
    # The keyboard opens in Hebrew the first time (Kodi then remembers the layout the user leaves it on)
    x(1, '<timer>')
    x(2, '<name>povil_keyboard_hebrew</name>')
    x(2, '<start>Window.IsActive(virtualkeyboard) + !Skin.HasSetting(PovilKeyboardHebrew) + String.Contains(Control.GetLabel(309),English)</start>')
    x(2, '<onstart>Skin.SetBool(PovilKeyboardHebrew)</onstart>')
    x(2, '<onstart>SendClick(309)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # The keyboard's search suggestions (plugin.program.autocompletion, povil_rtl=1)
    x(1, '<timer>')
    x(2, '<name>povil_rtl_9010</name>')
    x(2, '<start reset="true">Window.IsActive(virtualkeyboard) + %s</start>' % rtl_waiting(9010))
    x(2, '<onstart>SetProperty(povil.rtl.9010,$ESCINFO[Container(9010).ListItemAbsolute(0).Label],home)</onstart>')
    x(2, '<onstart>Control.Move(9010,-1)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    x(1, '<!-- POVIL RTL END -->')
    return x.text()


def write_timers(folder):
    path = os.path.join(folder, 'Timers.xml')
    text = open(path, encoding='utf-8').read()
    begin, end = '<!-- POVIL RTL BEGIN', '<!-- POVIL RTL END -->'
    if begin in text:
        start = text.rindex(NL, 0, text.index(begin)) + 1
        stop = text.index(NL, text.index(end)) + 1
        text = text[:start] + text[stop:]
    text = text.replace('</timers>', gen_timers() + '</timers>')
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text)


# ---------------------------------------------------------------- helpers
class X:
    def __init__(self):
        self.lines = []

    def __call__(self, depth, text):
        self.lines.append('\t' * depth + text)

    def text(self):
        return '\n'.join(self.lines) + '\n'


def e(s):
    return escape(s)


# ---------------------------------------------------------------- includes
def gen_includes():
    x = X()
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_home.py. Do not edit by hand. -->')
    x(0, '<includes>')
    sources = []  # (condition, container id)
    kinds = {}
    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            sources.append((row_focus(ti, ri), row_id(ti, ri)))
            kinds[row_id(ti, ri)] = row[2]
    for ti, tab in enumerate(TABS):
        if tab['rows']:
            sources.append((tab_cond(tab), row_id(ti, 0)))

    def var(name, fmt, fallback=None, empty_check=None):
        x(1, '<variable name="%s">' % name)
        for cond, cid in sources:
            check = (' + !String.IsEmpty(%s)' % (empty_check % cid)) if empty_check else ''
            x(2, '<value condition="%s%s">%s</value>' % (cond, check, e(fmt % {'c': cid})))
        if fallback:
            for cond, val in fallback:
                x(2, '<value condition="%s">%s</value>' % (cond, e(val)) if cond else '<value>%s</value>' % e(val))
        x(1, '</variable>')

    tab_titles = [(tab_cond(t), t['label']) for t in TABS]
    tab_blurbs = [(tab_cond(t), t['blurb']) for t in TABS]
    # Backdrop: fanart, else a landscape / thumb (Israeli VOD), else nothing (the ambient base shows).
    x(1, '<variable name="POVIL_HeroFanart">')
    for cond, cid in sources:
        if kinds[cid] == 'square':
            continue  # channel logos and icons: the ambient backdrop, never a stretched logo
        # A poster row's thumb is its poster, and a "fanart" that is the thumb again
        # (Idan Plus: Keshet's 420x600 posters) would fill the screen ~250% enlarged:
        # the ambient backdrop then
        poster_row = kinds[cid] == 'poster'
        for art in (('fanart', 'landscape') if poster_row else ('fanart', 'landscape', 'thumb')):
            same = (' + !String.IsEqual(Container(%d).ListItem.Art(%s),Container(%d).ListItem.Art(thumb))' % (cid, art, cid)) if poster_row else ''
            x(2, '<value condition="%s + ![String.Contains(Container(%d).ListItem.FolderPath,new_page=) | String.Contains(Container(%d).ListItem.FolderPath,Page&amp;url=)] + !String.IsEmpty(Container(%d).ListItem.Art(%s))%s">$INFO[Container(%d).ListItem.Art(%s)]</value>'
              % (cond, cid, cid, cid, art, same, cid, art))
    x(1, '</variable>')
    # No backdrop of its own (Keshet's posters, whose "fanart" is the poster again; a
    # channel's or a station's logo): its picture, blurred, becomes a soft wash of its
    # colours behind the hero (ambient() in backdrop()), never the picture enlarged
    for name, art in (('POVIL_HeroAmbient', 'povil_blur'), ('POVIL_HeroAmbientFile', 'povil_blurfile'),
                      ('POVIL_HeroAmbientPng', 'povil_blurpng')):
        x(1, '<variable name="%s">' % name)
        for cond, cid in sources:
            if kinds[cid] != 'landscape':  # a landscape row always has its own backdrop
                more = '![String.Contains(Container(%d).ListItem.FolderPath,new_page=) | String.Contains(Container(%d).ListItem.FolderPath,Page&amp;url=)]' % (cid, cid)
                own = ''
                if kinds[cid] == 'poster':
                    own = (' + [String.IsEmpty(Container(%d).ListItem.Art(fanart)) | String.IsEqual(Container(%d).ListItem.Art(fanart),Container(%d).ListItem.Art(thumb))]'
                           ' + String.IsEmpty(Container(%d).ListItem.Art(landscape))' % (cid, cid, cid, cid))
                x(2, '<value condition="%s + %s%s">$INFO[Container(%d).ListItem.Art(%s)]</value>' % (cond, more, own, cid, art))
            # the row on screen decides, also when it wants no wash: Kodi would go on
            # to the tab's first row (the fallback below) and wash over Reshet's backdrop
            x(2, '<value condition="%s"></value>' % cond)
        x(1, '</variable>')
    # Only a logo that suits a Hebrew screen (POV's povil_logo art); else the title is written
    var('POVIL_HeroLogo', '$INFO[Container(%(c)d).ListItem.Art(povil_logo)]')
    x(1, '<variable name="POVIL_HeroTitle">')
    for cond, cid in sources:
        x(2, '<value condition="%s + [String.Contains(Container(%d).ListItem.FolderPath,new_page=) | String.Contains(Container(%d).ListItem.FolderPath,Page&amp;url=)]">עוד תוצאות</value>' % (cond, cid, cid))
    for cond, cid in sources:
        x(2, '<value condition="%s + String.IsEqual(Container(%d).ListItem.DBType,episode)">$INFO[Container(%d).ListItem.TVShowTitle]</value>' % (cond, cid, cid))
        x(2, '<value condition="%s + !String.IsEmpty(Container(%d).ListItem.Title)">$INFO[Container(%d).ListItem.Title]</value>' % (cond, cid, cid))
        x(2, '<value condition="%s">$INFO[Container(%d).ListItem.Label]</value>' % (cond, cid))
    for cond, val in tab_titles:
        x(2, '<value condition="%s">%s</value>' % (cond, e(val)))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroEpisode">')
    for cond, cid in sources:
        x(2, '<value condition="%s + String.IsEqual(Container(%d).ListItem.DBType,episode)">$INFO[Container(%d).ListItem.Season,עונה , · ]$INFO[Container(%d).ListItem.Episode,פרק ]$INFO[Container(%d).ListItem.Title,  ·  ]</value>'
          % (cond, cid, cid, cid, cid))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroMeta">')
    for cond, cid in sources:
        x(2, '<value condition="%s + !String.IsEmpty(Container(%d).ListItem.Year)">$INFO[Container(%d).ListItem.Year]$INFO[Container(%d).ListItem.Genre,  •  ]$INFO[Container(%d).ListItem.Duration(mins),  •  , דק\']$INFO[Container(%d).ListItem.MPAA,  •  ]</value>'
          % (cond, cid, cid, cid, cid, cid))
        x(2, '<value condition="%s">$INFO[Container(%d).ListItem.Genre]$INFO[Container(%d).ListItem.Duration(mins),  •  , דק\']</value>' % (cond, cid, cid))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroRating">')
    for cond, cid in sources:
        x(2, '<value condition="%s + Integer.IsGreater(Container(%d).ListItem.Rating,0)">$INFO[Container(%d).ListItem.Rating]</value>' % (cond, cid, cid))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroPlot">')
    for cond, cid in sources:
        x(2, '<value condition="%s + !String.IsEmpty(Container(%d).ListItem.Plot) + !String.IsEqual(Container(%d).ListItem.Plot,Container(%d).ListItem.Label)">$INFO[Container(%d).ListItem.Plot]</value>' % (cond, cid, cid, cid, cid))
        x(2, '<value condition="%s + !String.IsEmpty(Container(%d).ListItem.PlotOutline)">$INFO[Container(%d).ListItem.PlotOutline]</value>' % (cond, cid, cid))
    for cond, val in tab_blurbs:
        x(2, '<value condition="%s">%s</value>' % (cond, e(val)))
    x(1, '</variable>')

    # Item art inside a row (ListItem = the item being drawn)
    x(1, '<variable name="POVIL_ItemLandscape">')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,episode) + !String.IsEmpty(ListItem.Art(thumb))">$INFO[ListItem.Art(thumb)]</value>')
    for art in ('landscape', 'fanart', 'thumb', 'poster'):
        x(2, '<value condition="!String.IsEmpty(ListItem.Art(%s))">$INFO[ListItem.Art(%s)]</value>' % (art, art))
    x(2, '<value>$INFO[ListItem.Icon]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_ItemPoster">')
    x(2, '<value condition="!String.IsEmpty(ListItem.Art(poster))">$INFO[ListItem.Art(poster)]</value>')
    x(2, '<value condition="!String.IsEmpty(ListItem.Art(tvshow.poster))">$INFO[ListItem.Art(tvshow.poster)]</value>')
    x(2, '<value>$INFO[ListItem.Art(thumb)]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_ItemSquare">')
    x(2, '<value condition="!String.IsEmpty(ListItem.Art(thumb))">$INFO[ListItem.Art(thumb)]</value>')
    x(2, '<value>$INFO[ListItem.Icon]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_ItemTitle">')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,episode)">$INFO[ListItem.TVShowTitle]</value>')
    x(2, '<value>$INFO[ListItem.Label]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_ItemEpisodeTitle">')
    x(2, '<value condition="!String.IsEmpty(ListItem.Title)">$INFO[ListItem.Title]</value>')
    x(2, '<value>$INFO[ListItem.Label]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_ItemEpisodeNumber">')
    x(2, "<value condition=\"!String.IsEmpty(ListItem.Episode)\">$INFO[ListItem.Episode,פרק ]$INFO[ListItem.Duration(mins),  •  , דק']</value>")
    x(1, '</variable>')
    x(1, '<variable name="POVIL_ItemSubtitle">')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,episode)">$INFO[ListItem.Season,עונה , · ]$INFO[ListItem.Episode,פרק ]</value>')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,movie)">$INFO[ListItem.Year]</value>')
    x(1, '</variable>')

    # Lazy rows: Kodi fills every list of a window when it opens, visible or not.
    # A tab's first row loads the first time the tab is selected (timer povil_tabs),
    # the rows below it once the user leaves the tabs for its chips or rows
    # (timer povil_deep): browsing the tabs costs one list each.
    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            if row[1].startswith('static:'):
                continue
            x(1, '<variable name="POVIL_Path_%d">' % row_id(ti, ri))
            gate = row_gate(ti, ri)
            path = rtl_path(named(row[1], row[0]))
            if retries(row):
                # a row that came back empty asks again (povil_retry_<id>): a new
                # address makes Kodi fetch it anew; the plain one stays first in the
                # file for the Wizard's prebuild, which skips addresses with $INFO
                x(2, '<value condition="!String.IsEmpty(Window(home).Property(%s)) + !String.IsEmpty(Window(home).Property(povil.retry.%d))">%s</value>'
                  % (gate, row_id(ti, ri), e(path + '&povil_retry=$INFO[Window(home).Property(povil.retry.%d)]' % row_id(ti, ri))))
            x(2, '<value condition="!String.IsEmpty(Window(home).Property(%s))">%s</value>'
              % (gate, e(path)))
            x(1, '</variable>')
    for ti, tab in enumerate(TABS):
        for ri, _ in enumerate(tab['rows']):
            rid = row_id(ti, ri)
            x(1, '<variable name="POVIL_RowTitleColor_%d">' % rid)
            x(2, '<value condition="%s">povil_white</value>' % row_focus(ti, ri))
            x(2, '<value>povil_dim</value>')
            x(1, '</variable>')
    for tab in TABS:
        x(1, '<variable name="POVIL_TabColor_%s">' % tab['id'])
        x(2, '<value condition="%s">povil_white</value>' % tab_cond(tab))
        x(2, '<value>povil_faint</value>')
        x(1, '</variable>')
    item_layouts(x)
    x(0, '</includes>')
    return x.text()


# View item layouts (Videos window): the layout follows the list's content.
VIEW_COND = {
    'poster': 'Container.Content(movies) | Container.Content(tvshows) | Container.Content(seasons) | Container.Content(sets)',
    'landscape': 'Container.Content(episodes) | Container.Content(videos) | Container.Content(musicvideos)',
}
VIEW_COND['square'] = '![%s | %s]' % (VIEW_COND['poster'], VIEW_COND['landscape'])


def item_layouts(x):
    for kind in ('poster', 'landscape', 'square'):
        item_layout(x, 'POVIL_Item_%s' % kind, kind)
    item_layout(x, 'POVIL_ViewItem_poster', 'poster', VIEW_COND['poster'])
    item_layout(x, 'POVIL_ViewItem_landscape', 'landscape', VIEW_COND['landscape'])
    item_layout(x, 'POVIL_ViewItem_square', 'square', VIEW_COND['square'])
    # A show's own episodes: each tile names its episode, not the show again
    item_layout(x, 'POVIL_ViewItem_episodes', 'landscape', title='POVIL_ItemEpisodeTitle', subtitle='POVIL_ItemEpisodeNumber')


def item_layout(x, name, kind, cond=None, title='POVIL_ItemTitle', subtitle='POVIL_ItemSubtitle'):
    if True:
        g = GEOM[kind]
        w, h, step = g['w'], g['h'], g['step']
        top = 22
        x(1, '<include name="%s">' % name)
        x(2, '<param name="id" />')
        x(2, '<definition>')
        for focused in (False, True):
            tag = 'focusedlayout' if focused else 'itemlayout'
            cattr = (' condition="%s"' % cond) if cond else ''
            x(3, '<%s width="%d" height="%d"%s>' % (tag, step, g['list_h'], cattr))
            x(4, '<control type="group">')
            x(5, '<left>%d</left><top>0</top>' % PAD)
            if focused:
                x(5, '<animation effect="zoom" start="100" end="%d" center="%d,%d" time="240" tween="cubic" easing="out" condition="Control.HasFocus($PARAM[id])">Conditional</animation>'
                  % (106 if kind == 'poster' else 105, PAD + w // 2, top + h // 2))
            # drop shadow
            x(5, '<control type="image">')
            x(6, '<left>-30</left><top>%d</top><width>%d</width><height>%d</height>' % (top - 22, w + 60, h + 60))
            x(6, '<texture border="54">povil/shadow.png</texture>')
            x(5, '</control>')
            if focused:
                x(5, '<control type="image">')
                x(6, '<left>-36</left><top>%d</top><width>%d</width><height>%d</height>' % (top - 36, w + 72, h + 72))
                x(6, '<texture border="60" colordiffuse="99D9B77E">povil/focus_glow.png</texture>')
                x(6, '<visible>Control.HasFocus($PARAM[id])</visible>')
                x(5, '</control>')
            if kind == 'square':
                x(5, '<control type="image">')
                x(6, '<left>0</left><top>%d</top><width>%d</width><height>%d</height>' % (top, w, h))
                x(6, '<texture border="30" colordiffuse="%s">povil/rounded_fill.png</texture>' % ('33FFFFFF' if focused else '1FFFFFFF'))
                x(5, '</control>')
                x(5, '<control type="image">')
                x(6, '<left>30</left><top>%d</top><width>%d</width><height>%d</height>' % (top + 30, w - 60, h - 60))
                x(6, '<texture background="true" fallback="DefaultFolder.png">$VAR[POVIL_ItemSquare]</texture>')
                x(6, '<aspectratio>keep</aspectratio>')
                x(5, '</control>')
            else:
                art = 'POVIL_ItemPoster' if kind == 'poster' else 'POVIL_ItemLandscape'
                mask = 'povil/mask_poster.png' if kind == 'poster' else 'povil/mask_landscape.png'
                x(5, '<control type="image">')
                x(6, '<left>0</left><top>%d</top><width>%d</width><height>%d</height>' % (top, w, h))
                x(6, '<texture border="30" colordiffuse="1FFFFFFF">povil/rounded_fill.png</texture>')
                x(5, '</control>')
                x(5, '<control type="label">')
                x(6, '<left>16</left><top>%d</top><width>%d</width><height>%d</height>' % (top, w - 32, h))
                x(6, '<font>povil_small</font><align>center</align><aligny>center</aligny><wrapmultiline>true</wrapmultiline>')
                x(6, '<textcolor>povil_dim</textcolor><label>$INFO[ListItem.Label]</label>')
                x(6, '<visible>![String.Contains(ListItem.FolderPath,new_page=) | String.Contains(ListItem.FolderPath,Page&amp;url=)] + !ListItem.IsParentFolder</visible>')
                x(5, '</control>')
                # The picture whole (keep) over a dim fill of itself (scale): a poster in a
                # 16:9 tile, or a 16:9 picture in a poster tile, is never cropped to its
                # middle; a picture of the tile's own shape covers the fill exactly.
                for diffuse, ratio in (('4DFFFFFF', 'scale'), ('FFFFFFFF', 'keep')):
                    x(5, '<control type="image">')
                    x(6, '<left>0</left><top>%d</top><width>%d</width><height>%d</height>' % (top, w, h))
                    x(6, '<texture background="true" diffuse="%s" colordiffuse="%s">$VAR[%s]</texture>' % (mask, diffuse, art))
                    x(6, '<aspectratio scalediffuse="false">%s</aspectratio>' % ratio)
                    x(6, '<visible>![String.Contains(ListItem.FolderPath,new_page=) | String.Contains(ListItem.FolderPath,Page&amp;url=)] + !ListItem.IsParentFolder</visible>')
                    x(5, '</control>')
                # POV's next-page item: "more", the arrow pointing on to the left
                x(5, '<control type="group"><left>0</left><top>%d</top><visible>[String.Contains(ListItem.FolderPath,new_page=) | String.Contains(ListItem.FolderPath,Page&amp;url=)]</visible>' % top)
                x(6, '<control type="image"><left>0</left><top>0</top><width>%d</width><height>%d</height>'
                     '<texture border="30" colordiffuse="%s">povil/rounded_fill.png</texture></control>' % (w, h, '33D9B77E' if focused else '1AD9B77E'))
                x(6, '<control type="image"><left>%d</left><top>%d</top><width>64</width><height>64</height>'
                     '<texture colordiffuse="povil_gold">povil/osd/rewind.png</texture></control>' % (w // 2 - 32, h // 2 - 56))
                x(6, '<control type="label"><left>0</left><top>%d</top><width>%d</width><height>44</height><font>povil_row</font>'
                     '<textcolor>povil_white</textcolor><align>center</align><aligny>center</aligny><label>עוד</label></control>' % (h // 2 + 14, w))
                x(5, '</control>')
                # Kodi's parent folder item (".."): "back", the arrow pointing to the right,
                # where the list began
                x(5, '<control type="group"><left>0</left><top>%d</top><visible>ListItem.IsParentFolder</visible>' % top)
                x(6, '<control type="image"><left>0</left><top>0</top><width>%d</width><height>%d</height>'
                     '<texture border="30" colordiffuse="%s">povil/rounded_fill.png</texture></control>' % (w, h, '33FFFFFF' if focused else '14FFFFFF'))
                x(6, '<control type="image"><left>%d</left><top>%d</top><width>64</width><height>64</height>'
                     '<texture colordiffuse="povil_dim">povil/osd/forward.png</texture></control>' % (w // 2 - 32, h // 2 - 56))
                x(6, '<control type="label"><left>0</left><top>%d</top><width>%d</width><height>44</height><font>povil_row</font>'
                     '<textcolor>povil_white</textcolor><align>center</align><aligny>center</aligny><label>חזרה</label></control>' % (h // 2 + 14, w))
                x(5, '</control>')
            # gold ring
            if focused:
                x(5, '<control type="image">')
                x(6, '<left>-6</left><top>%d</top><width>%d</width><height>%d</height>' % (top - 6, w + 12, h + 12))
                x(6, '<texture border="30" colordiffuse="%s">povil/focus_ring.png</texture>' % GOLD)
                x(6, '<visible>Control.HasFocus($PARAM[id])</visible>')
                x(5, '</control>')
            # watched / progress
            x(5, '<control type="progress">')
            x(6, '<left>14</left><top>%d</top><width>%d</width><height>6</height>' % (top + h - 18, w - 28))
            x(6, '<texturebg border="3" colordiffuse="99000000">povil/progress.png</texturebg>')
            x(6, '<midtexture border="3" colordiffuse="%s">povil/progress.png</midtexture>' % GOLD)
            x(6, '<info>ListItem.PercentPlayed</info>')
            x(6, '<reveal>false</reveal><lefttexture></lefttexture><righttexture></righttexture><overlaytexture></overlaytexture>')
            x(6, '<visible>Integer.IsGreater(ListItem.PercentPlayed,0)</visible>')
            x(5, '</control>')
            x(5, '<control type="image">')
            x(6, '<left>%d</left><top>%d</top><width>34</width><height>34</height>' % (w - 44, top + 10))
            x(6, '<texture colordiffuse="%s">povil/check.png</texture>' % GOLD)
            x(6, '<visible>Integer.IsGreater(ListItem.PlayCount,0)</visible>')
            x(5, '</control>')
            if kind in ('landscape', 'square'):
                x(5, '<control type="%s">' % ('label' if kind == 'landscape' else 'textbox'))
                x(6, '<left>0</left><top>%d</top><width>%d</width><height>%d</height>' % (top + h + 12, w, 34 if kind == 'landscape' else 58))
                x(6, '<font>%s</font><align>%s</align>%s' % ('povil_row' if kind == 'landscape' else 'povil_small', 'right' if kind == 'landscape' else 'center', '<aligny>center</aligny>' if kind == 'landscape' else ''))
                x(6, '<textcolor>%s</textcolor><label>$VAR[%s]</label>' % ('povil_white' if focused else 'povil_dim', title))
                x(5, '</control>' if kind == 'landscape' else '</control>')
                if kind == 'landscape':
                    x(5, '<control type="label">')
                    x(6, '<left>0</left><top>%d</top><width>%d</width><height>28</height>' % (top + h + 46, w))
                    x(6, '<font>povil_small</font><align>right</align><aligny>center</aligny>')
                    x(6, '<textcolor>povil_faint</textcolor><label>$VAR[%s]</label>' % subtitle)
                    x(5, '</control>')
            x(4, '</control>')
            x(3, '</%s>' % tag)
        x(2, '</definition>')
        x(1, '</include>')


# ---------------------------------------------------------------- Home.xml
def gen_home():
    x = X()
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_home.py. Do not edit by hand. -->')
    x(0, '<window>')
    x(1, '<defaultcontrol>9000</defaultcontrol>')
    # Kodi's ".." item would sit after "more" at a list's far end: off, unless the user
    # chose it in the skin settings (POVILParentDirChosen; Onyx's own toggle script)
    x(1, '<onload condition="System.GetBool(filelists.showparentdiritems) + !Skin.HasSetting(POVILParentDirChosen)'
         ' + !Skin.HasSetting(POVILParentDirOff)">RunScript(special://skin/scripts/onyx_tools.py,parentdir)</onload>')
    x(1, '<onload condition="!Skin.HasSetting(POVILParentDirOff)">Skin.SetBool(POVILParentDirOff)</onload>')
    # Back from Kodi's favourites window: the favourites row reads the file again
    x(1, '<onload condition="Window.Previous(favouritesbrowser)">SetProperty(povil.fav.t,$INFO[System.Time(hh:mm:ss)],home)</onload>')
    # Phones: a vertical swipe moves between the rows (Onyx's keymap names the swipe in
    # povil.swipe, the timer povil_swipe moves; once per session). A swipe left over
    # from another skin does not move anything here.
    x(1, '<onload>ClearProperty(povil.swipe,home)</onload>')
    x(1, '<onload condition="System.Platform.Android + String.IsEmpty(Window(home).Property(povil.touchmap))">'
         'RunScript(special://skin/scripts/onyx_tools.py,touchkeymap)</onload>')
    x(1, '<onload condition="System.Platform.Android">SetProperty(povil.touchmap,1,home)</onload>')
    # The first tab's content from the first frame (its button names the tab once focused)
    x(1, '<onload condition="String.IsEmpty(Window(home).Property(povil.tab))">SetProperty(povil.tab,%s,home)</onload>' % TABS[0]['id'])
    x(1, '<onload condition="String.IsEmpty(Window(home).Property(povil.tab.%s))">SetProperty(povil.tab.%s,1,home)</onload>' % (TABS[0]['id'], TABS[0]['id']))
    x(1, '<backgroundcolor>FF000000</backgroundcolor>')
    x(1, '<onload>RunScript(special://home/addons/plugin.program.kodipovilwizard/profile_bootstrap.py)</onload>')
    # Onyx's one-time defaults (used by its other windows)
    for line in ('Skin.SetBool(ShowClock)', 'Skin.SetString(shutdown,quit)', 'Skin.SetBool(LibUpdateOff)',
                 'Skin.SetBool(UseExtInfo)', 'Skin.SetString(AutoCloseTimeVideoOSD,4)', 'Skin.SetBool(_ShowWatched)',
                 'Skin.SetBool(_ShowUnwatched)', 'Skin.SetBool(NoFocusBox)', 'Skin.SetBool(TintFrame)',
                 'Skin.SetBool(OnyxFirstRun)'):
        x(1, '<onload condition="!Skin.HasSetting(OnyxFirstRun)">%s</onload>' % line)
    # Start on the rightmost tab (Movies) once per session
    # A reloaded skin (or profile) refills the rows from their first item: let
    # each RTL row move to its right end again.
    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            if is_rtl(row[1]):
                x(1, '<onload>ClearProperty(povil.rtl.%d,home)</onload>' % row_id(ti, ri))
    # The views' guard: a season opened again from the home starts on its first item
    x(1, '<onload>ClearProperty(povil.rtl.view,home)</onload>')
    x(1, '<onload>ClearProperty(povil.rtl.view.prev,home)</onload>')
    x(1, '<controls>')
    backdrop(x, 2)
    top_bar(x, 2)
    hero(x, 2)
    chips(x, 2)
    rows(x, 2)
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


def backdrop(x, d):
    x(d, '<control type="image" description="ambient base">')
    x(d + 1, '<left>0</left><top>0</top><width>1920</width><height>1080</height>')
    x(d + 1, '<texture>povil/ambient.jpg</texture>')
    x(d, '</control>')
    x(d, '<control type="image" description="backdrop">')
    x(d + 1, '<left>0</left><top>0</top><width>1920</width><height>1080</height>')
    x(d + 1, '<texture background="true">$VAR[POVIL_HeroFanart]</texture>')
    x(d + 1, '<aspectratio>scale</aspectratio><fadetime>420</fadetime>')
    x(d, '</control>')
    ambient(x, d)
    for desc, l, t, w, h, tex in (('hero shade', 520, 0, 1400, 1080, 'povil/grad_right.png'),
                                  ('rows shade', 0, 330, 1920, 750, 'povil/grad_bottom.png'),
                                  ('top shade', 0, 0, 1920, 240, 'povil/grad_top.png'),
                                  ('vignette', 0, 0, 1920, 1080, 'povil/vignette.png')):
        x(d, '<control type="image" description="%s">' % desc)
        x(d + 1, '<left>%d</left><top>%d</top><width>%d</width><height>%d</height>' % (l, t, w, h))
        x(d + 1, '<texture>%s</texture>' % tex)
        x(d, '</control>')


def ambient(x, d):
    """A picture with no backdrop of its own (POVIL_HeroAmbient), as a soft wash of
    its colours: povil_rtl gives every item of a home row the art povil_blur, the
    item's picture that Kodi itself shrinks to 10 pixels wide (image://.../transform
    ?width=10) -- drawn over the whole screen it is a smooth blur, in one layer.
    Kodi shows a picture full size the first time it shrinks it (only the copy it
    keeps is small) and hands every control showing the same address the same
    picture, so an invisible pixel asks for povil_blur once the screen has been
    still for a second, and the wash draws the kept file itself (povil_blurfile / povil_blurpng,
    copied to Window(home).Property(povil.blur) by the timer povil_blur a second
    later, never under a dialog): by then the small copy is kept, and fast
    scrolling fetches nothing. A copy not kept yet (a slow network) leaves the
    plain backdrop until the item is chosen again. Darkened by its colour so the
    hero text stays clear; hidden at once on an item with a backdrop of its own."""
    x(d, '<control type="image" description="ambient wash: the small copy is made">')
    x(d + 1, '<left>0</left><top>0</top><width>1</width><height>1</height>')
    x(d + 1, '<texture background="true" colordiffuse="01FFFFFF">$VAR[POVIL_HeroAmbient]</texture>')
    x(d + 1, '<visible>System.IdleTime(1)</visible>')   # fast scrolling fetches nothing
    x(d, '</control>')
    # Kodi keeps a picture with transparency (a channel's logo) as .png, any other
    # as .jpg: a picture that is not a JPEG tries both (povil_blurpng), and the
    # one Kodi did not keep draws nothing
    for desc, prop in (('jpg', 'povil.blur'), ('png', 'povil.blurpng')):
        x(d, '<control type="image" description="ambient wash %s">' % desc)
        x(d + 1, '<left>-60</left><top>-60</top><width>2040</width><height>1200</height>')
        x(d + 1, '<texture background="true" colordiffuse="FF999999">$INFO[Window(home).Property(%s)]</texture>' % prop)
        x(d + 1, '<aspectratio>scale</aspectratio><fadetime>600</fadetime>')
        x(d + 1, '<visible>!String.IsEmpty(Control.GetLabel(9803)) + !String.IsEmpty(Window(home).Property(%s))</visible>' % prop)
        x(d + 1, '<animation effect="fade" time="300">Visible</animation><animation effect="fade" time="150">Hidden</animation>')
        x(d, '</control>')
    # Hidden label: the wash the hero wants now (the timer compares it)
    x(d, '<control type="label" id="9803"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_HeroAmbientFile]</label></control>')
    x(d, '<control type="label" id="9804"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_HeroAmbientPng]</label></control>')


def top_bar(x, d):
    # Clock and date (top left)
    x(d, '<control type="label" description="clock">')
    x(d + 1, '<left>%d</left><top>30</top><width>400</width><height>52</height>' % MARGIN)
    x(d + 1, '<font>povil_clock</font><textcolor>povil_white</textcolor><aligny>center</aligny>')
    x(d + 1, '<label>$INFO[System.Time]</label>')
    x(d, '</control>')
    x(d, '<control type="label" description="date">')
    x(d + 1, '<left>%d</left><top>80</top><width>400</width><height>30</height>' % MARGIN)
    x(d + 1, '<font>povil_small</font><textcolor>povil_faint</textcolor><aligny>center</aligny>')
    x(d + 1, '<label>$INFO[System.Date(DDDD)]$INFO[System.Date(d MMMM),  •  ]</label>')
    x(d, '</control>')
    x(d, '<control type="list" id="%d" description="Kodi favourites, counted for the favourites row">' % FAV_COUNT)
    x(d + 1, '<left>-4000</left><top>0</top><width>20</width><height>20</height>')
    x(d + 1, '<itemlayout width="20" height="20" /><focusedlayout width="20" height="20" />')
    x(d + 1, '<content>favourites://</content>')
    x(d, '</control>')
    # Tabs: one button per tab, the first tab on the right. The window's default
    # control is the first tab's button, so the home opens on it at once -- also
    # under a dialog (the skin-change confirmation) and after a skin reload.
    # A focused tab names itself in Window(home).Property(povil.tab).
    n = len(TABS)
    x(d, '<control type="group" id="9000" description="tabs">')
    x(d + 1, '<left>%d</left><top>34</top><width>%d</width><height>72</height>' % (1920 - MARGIN - n * TAB_W, n * TAB_W))
    x(d + 1, '<defaultcontrol>%d</defaultcontrol>' % tab_button(0))
    for ti, tab in enumerate(TABS):
        left = (n - 1 - ti) * TAB_W
        target = chip_ids(ti, tab)[0] if tab['chips'] else (row_id(ti, 0) if tab['rows'] else tab_button(ti))
        x(d + 1, '<control type="button" id="%d" description="tab %s">' % (tab_button(ti), tab['id']))
        x(d + 2, '<left>%d</left><top>0</top><width>%d</width><height>60</height>' % (left, TAB_W))
        x(d + 2, '<texturefocus /><texturenofocus />')
        x(d + 2, '<font>povil_menu</font><align>center</align><aligny>center</aligny>')
        x(d + 2, '<textcolor>$VAR[POVIL_TabColor_%s]</textcolor><focusedcolor>povil_white</focusedcolor>' % tab['id'])
        x(d + 2, '<label>%s</label>' % e(tab['label']))
        x(d + 2, '<onfocus>SetProperty(povil.tab,%s,home)</onfocus>' % tab['id'])
        x(d + 2, '<onfocus>SetProperty(povil.tab.%s,1,home)</onfocus>' % tab['id'])
        x(d + 2, '<onfocus>SetProperty(povil.focus,%d,home)</onfocus>' % tab_button(ti))
        # a row whose retries ran out (a box that started before its network) asks
        # again when its tab is chosen again
        for ri, row in enumerate(tab['rows']):
            if retries(row):
                rid = row_id(ti, ri)
                x(d + 2, '<onfocus condition="String.IsEqual(Window(home).Property(povil.retry.%d),2) + !Integer.IsGreater(Container(%d).NumItems,0)">'
                         'ClearProperty(povil.retry.%d,home)</onfocus>' % (rid, rid, rid))
        if tab.get('click_alt'):
            cond, action = tab['click_alt']
            x(d + 2, '<onclick condition="%s">%s</onclick>' % (e(cond), e(named(action, tab['label']))))
            x(d + 2, '<onclick condition="![%s]">%s</onclick>' % (e(cond), e(named(tab['click'], tab['label']))))
        else:
            x(d + 2, '<onclick>%s</onclick>' % e(named(tab['click'], tab['label'])))
        if ti + 1 < n:
            x(d + 2, '<onleft>%d</onleft>' % tab_button(ti + 1))
        if ti:
            x(d + 2, '<onright>%d</onright>' % tab_button(ti - 1))
        x(d + 2, '<ondown>%d</ondown>' % target)
        x(d + 1, '</control>')
        x(d + 1, '<control type="image">')
        x(d + 2, '<left>%d</left><top>60</top><width>44</width><height>4</height>' % (left + (TAB_W - 44) // 2))
        x(d + 2, '<texture colordiffuse="%s">povil/underline.png</texture>' % GOLD)
        x(d + 2, '<visible>%s</visible>' % tab_cond(tab))
        x(d + 2, '<animation effect="zoom" start="40,100" end="100,100" center="auto" time="220" tween="cubic" easing="out">Visible</animation>')
        x(d + 1, '</control>')
    x(d, '</control>')

def hero(x, d):
    right = 1920 - MARGIN
    x(d, '<control type="group" description="hero">')
    x(d + 1, '<left>0</left><top>0</top>')
    # Clear logo, else the title
    x(d + 1, '<control type="image" description="clear logo">')
    x(d + 2, '<left>%d</left><top>138</top><width>620</width><height>176</height>' % (right - 620))
    x(d + 2, '<texture background="true">$VAR[POVIL_HeroLogo]</texture>')
    x(d + 2, '<aspectratio align="right" aligny="bottom">keep</aspectratio><fadetime>120</fadetime>')
    x(d + 1, '</control>')
    x(d + 1, '<control type="label" description="title">')
    x(d + 2, '<left>%d</left><top>184</top><width>1100</width><height>130</height>' % (right - 1100))
    x(d + 2, '<font>povil_hero</font><textcolor>povil_white</textcolor><align>right</align><aligny>bottom</aligny>')
    x(d + 2, '<label>$VAR[POVIL_HeroTitle]</label>')
    x(d + 2, '<visible>String.IsEmpty(Control.GetLabel(9800))</visible>')
    x(d + 1, '</control>')
    # Hidden label: tells the title whether a logo exists
    x(d + 1, '<control type="label" id="9800"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_HeroLogo]</label></control>')
    x(d + 1, '<control type="label" description="episode">')
    x(d + 2, '<left>%d</left><top>322</top><width>1100</width><height>34</height>' % (right - 1100))
    x(d + 2, '<font>povil_meta_bold</font><textcolor>%s</textcolor><align>right</align><aligny>center</aligny>' % GOLD)
    x(d + 2, '<label>$VAR[POVIL_HeroEpisode]</label>')
    x(d + 1, '</control>')
    # Details: rating (gold star) then year, genre, length, rating age
    x(d + 1, '<control type="grouplist" description="details">')
    x(d + 2, '<left>%d</left><top>%s</top><width>1100</width><height>40</height>' % (right - 1100, 356))
    x(d + 2, '<orientation>horizontal</orientation><align>right</align><itemgap>16</itemgap><usecontrolcoords>true</usecontrolcoords>')
    x(d + 2, '<control type="label">')
    x(d + 3, '<width>auto</width><height>40</height><font>povil_meta</font><textcolor>povil_dim</textcolor><aligny>center</aligny>')
    x(d + 3, '<label>$VAR[POVIL_HeroMeta]</label>')
    x(d + 2, '</control>')
    x(d + 2, '<control type="label">')
    x(d + 3, '<width>auto</width><height>40</height><font>povil_meta_bold</font><textcolor>%s</textcolor><aligny>center</aligny>' % GOLD)
    x(d + 3, '<label>$VAR[POVIL_HeroRating]</label>')
    x(d + 2, '</control>')
    x(d + 2, '<control type="image">')
    x(d + 3, '<top>9</top><width>22</width><height>22</height>')
    x(d + 3, '<texture colordiffuse="%s">povil/star.png</texture>' % GOLD)
    x(d + 3, '<visible>!String.IsEmpty(Control.GetLabel(9801))</visible>')
    x(d + 2, '</control>')
    x(d + 1, '</control>')
    x(d + 1, '<control type="label" id="9801"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_HeroRating]</label></control>')
    x(d + 1, '<control type="textbox" description="plot">')
    x(d + 2, '<left>%d</left><top>402</top><width>860</width><height>114</height>' % (right - 860))
    x(d + 2, '<font>povil_plot</font><textcolor>povil_dim</textcolor><align>right</align>')
    x(d + 2, '<label>$VAR[POVIL_HeroPlot]</label>')
    x(d + 1, '</control>')
    x(d, '</control>')


def chips(x, d):
    for tab in TABS:
        assert not tab['chips'] or len(tab['chips'][0]) < 3, 'a tab\'s first chip must always show: %s' % tab['id']
    x(d, '<control type="grouplist" id="9100" description="chips">')
    x(d + 1, '<left>%d</left><top>538</top><width>%d</width><height>50</height>' % (MARGIN, 1920 - 2 * MARGIN))
    x(d + 1, '<orientation>horizontal</orientation><align>right</align><itemgap>14</itemgap>')
    x(d + 1, '<scrolltime tween="cubic" easing="out">240</scrolltime>')
    x(d + 1, '<onup>9000</onup>')
    for ti, tab in enumerate(TABS):
        ids = chip_ids(ti, tab)
        down = row_id(ti, 0) if tab['rows'] else ''
        # XML order is left to right: last chip first, so the first chip is the rightmost
        for ci in reversed(range(len(tab['chips']))):
            chip = tab['chips'][ci]
            label, click = chip[0], named(chip[1], chip[0])
            vis = tab_cond(tab) + (' + ' + chip[2] if len(chip) > 2 else '')
            x(d + 1, '<control type="button" id="%d">' % ids[ci])
            x(d + 2, '<width>auto</width><height>48</height><textoffsetx>28</textoffsetx>')
            x(d + 2, '<font>povil_chip</font><align>center</align><aligny>center</aligny>')
            x(d + 2, '<textcolor>povil_white</textcolor><focusedcolor>povil_ink</focusedcolor>')
            x(d + 2, '<texturenofocus border="24" colordiffuse="24FFFFFF">povil/pill48.png</texturenofocus>')
            x(d + 2, '<texturefocus border="24" colordiffuse="%s">povil/pill48.png</texturefocus>' % GOLD)
            x(d + 2, '<label>%s</label>' % e(label))
            x(d + 2, '<onclick>%s</onclick>' % e(click))
            x(d + 2, '<onfocus>SetProperty(povil.tab,%s,home)</onfocus>' % tab['id'])
            x(d + 2, '<onfocus>SetProperty(povil.focus,%d,home)</onfocus>' % ids[ci])
            x(d + 2, '<onup>%d</onup>' % tab_button(ti))
            if down:
                x(d + 2, '<ondown>%d</ondown>' % down)
            x(d + 2, '<visible>%s</visible>' % vis)
            x(d + 1, '</control>')
    x(d, '</control>')


def rtl_slots(g):
    """A right-to-left row: whole item slots only, the last one flush with the
    right margin. Kodi counts every slot inside a list as visible, so a slot cut
    by the screen edge would hold the row's far end ("עוד" included) half off
    screen. Returns the list's left and width (PAD wider on each side), and the
    left of the tile before the first one (the peek)."""
    gap = g['step'] - g['w']
    end = 1920 - MARGIN + gap
    slots = end // g['step']
    left = end - slots * g['step']
    # PAD on the left (the far end's frame); on the right the list ends where the
    # next slot would start, so an item past the first never shows a sliver.
    # Still `slots` items per page for Kodi (PAD < step).
    return left - PAD, slots * g['step'] + PAD, left - g['step']


def short_rows(x, d, container, kind, when=None, count='NumItems'):
    """Kodi lays a list out from its left edge: a right-to-left list shorter than
    a page (a show's two seasons) slides right by its empty slots, so it starts
    at the right margin like every longer one."""
    g = GEOM[kind]
    slots = rtl_slots(g)[1] // g['step']
    for n in range(1, slots):
        cond = 'Integer.IsEqual(%s.%s,%d)' % (container, count, n)
        if when:
            cond = '[%s] + %s' % (when, cond)
        x(d, '<animation effect="slide" end="%d,0" time="0" condition="%s">Conditional</animation>'
          % ((slots - n) * g['step'], cond))


def peek(x, d, cid, kind, top):
    """The item past a right-to-left row's left end, dimmed at the screen edge:
    a picture only (ListItemPosition(-1)), it never takes the focus."""
    g = GEOM[kind]
    left = rtl_slots(g)[2]
    if left + g['w'] <= 0:
        return
    item = 'Container(%d).ListItemPosition(-1)' % cid
    art = ('thumb', 'poster') if kind == 'poster' else ('thumb', 'fanart')
    x(d, '<control type="group" description="peek">')
    x(d + 1, '<left>%d</left><top>%d</top>' % (left, top + 22))
    x(d + 1, '<visible>!String.IsEmpty(%s.Label) + !Container(%d).IsUpdating</visible>' % (item, cid))
    x(d + 1, '<control type="image"><left>0</left><top>0</top><width>%d</width><height>%d</height>'
             '<texture border="30" colordiffuse="1FFFFFFF">povil/rounded_fill.png</texture></control>' % (g['w'], g['h']))
    mask = 'povil/mask_poster.png' if kind == 'poster' else ('povil/mask_square.png' if kind == 'square' else 'povil/mask_landscape.png')
    for key in art:
        x(d + 1, '<control type="image"><left>0</left><top>0</top><width>%d</width><height>%d</height>'
                 '<texture background="true" diffuse="%s" colordiffuse="66FFFFFF">$INFO[%s.Art(%s)]</texture>'
                 '<aspectratio scalediffuse="false">scale</aspectratio></control>' % (g['w'], g['h'], mask, item, key))
    x(d, '</control>')



def retries(row):
    """Rows that are never empty by design and come from an add-on: when one
    comes back empty, the request failed and is worth asking again."""
    title, path, kind, optional = row
    return path.startswith('plugin://') and not optional


def row_gate(ti, ri):
    """The home property that opens a row's path (lazy loading, POVIL_Path_<id>)."""
    return 'povil.tab.%s' % TABS[ti]['id'] if ri == 0 else 'povil.deep.%s' % TABS[ti]['id']


def skeleton(x, d, ti, ri, rid, kind, path, optional):
    """While a row has nothing to show yet -- not opened, loading, or waiting to
    start on the right -- dim tiles stand where its items will be (still: a
    pulse would redraw the screen every frame, on a phone's battery), so a slow
    list (a phone, a list never seen before) reads as loading, not as empty.
    A row that retries (gen_home retries) keeps them up until its retries are
    spent, and only then says it has nothing."""
    g = GEOM[kind]
    has = 'Integer.IsGreater(Container(%d).NumItems,0)' % rid
    opened = '!String.IsEmpty(Window(home).Property(%s))' % row_gate(ti, ri)
    closed = 'String.IsEmpty(Window(home).Property(%s))' % row_gate(ti, ri)
    spent = 'String.IsEqual(Window(home).Property(povil.retry.%d),2)' % rid
    parts = ['Container(%d).IsUpdating' % rid]
    if is_rtl(path) and not path.startswith('static:'):
        parts.append('[%s]' % rtl_waiting(rid))
    if retries((None, path, kind, optional)):
        parts.append('[!%s + !%s]' % (has, spent))       # until the retries are spent
    elif not optional:
        parts.append('[!%s + %s]' % (has, closed))
    if is_rtl(path):
        left = rtl_slots(g)[0] + PAD
        slots = [left + k * g['step'] for k in range(rtl_slots(g)[1] // g['step'])]
    else:
        slots = [MARGIN + k * g['step'] for k in range((1920 - 2 * MARGIN + g['step'] - g['w']) // g['step'])]
    x(d, '<control type="group" description="loading">')
    x(d + 1, '<visible>%s</visible>' % ' | '.join(parts))
    x(d + 1, '<animation effect="fade" time="200">Visible</animation><animation effect="fade" time="200">Hidden</animation>')
    for left in slots:
        x(d + 1, '<control type="image"><left>%d</left><top>62</top><width>%d</width><height>%d</height>'
                 '<texture border="30" colordiffuse="14FFFFFF">povil/rounded_fill.png</texture></control>' % (left, g['w'], g['h']))
    x(d, '</control>')
    if retries((None, path, kind, optional)):
        x(d, '<control type="label" description="nothing here">')
        x(d + 1, '<left>%d</left><top>%d</top><width>%d</width><height>60</height>' % (MARGIN, 62 + g['h'] // 2 - 30, 1920 - 2 * MARGIN))
        x(d + 1, '<font>povil_meta</font><textcolor>povil_faint</textcolor><align>right</align><aligny>center</aligny>')
        x(d + 1, '<label>אין כרגע מה להציג כאן</label>')
        x(d + 1, '<visible>%s + %s + !Container(%d).IsUpdating + !%s</visible>' % (opened, spent, rid, has))
        x(d + 1, '<animation effect="fade" start="0" end="100" time="300">Visible</animation>')
        x(d, '</control>')


def rows(x, d):
    for ti, tab in enumerate(TABS):
        if not tab['rows']:
            continue
        ids = [row_id(ti, ri) for ri in range(len(tab['rows']))]
        offsets, y = [], 0
        for r in tab['rows']:
            offsets.append(y)
            y += GEOM[r[2]]['block']
        x(d, '<control type="group" description="rows %s">' % tab['id'])
        x(d + 1, '<left>0</left><top>%d</top>' % ROWS_Y)
        x(d + 1, '<visible>%s</visible>' % tab_cond(tab))
        # Slide the rows up so the focused row sits where the first one was
        for ri in range(1, len(ids)):
            x(d + 1, '<animation effect="slide" end="0,-%d" time="320" tween="cubic" easing="out" condition="%s">Conditional</animation>'
              % (offsets[ri], row_focus(ti, ri)))
        for ri, (title, path, kind, optional) in enumerate(tab['rows']):
            g = GEOM[kind]
            rid = ids[ri]
            x(d + 1, '<control type="group" description="%s">' % e(title))
            x(d + 2, '<left>0</left><top>%d</top>' % offsets[ri])
            # Rows above the focused one fade out (they would cover the hero)
            hide = ' | '.join(row_focus(ti, j) for j in range(ri + 1, len(ids)))
            if hide:
                x(d + 2, '<animation effect="fade" start="100" end="0" time="220" condition="%s">Conditional</animation>' % hide)
            x(d + 2, '<control type="label">')
            x(d + 3, '<left>%d</left><top>0</top><width>%d</width><height>44</height>' % (MARGIN, 1920 - 2 * MARGIN))
            x(d + 3, '<font>povil_row</font><align>right</align><aligny>center</aligny>')
            x(d + 3, '<textcolor>$VAR[POVIL_RowTitleColor_%d]</textcolor><label>%s</label>' % (rid, e(title)))
            vis = 'Integer.IsGreater(Container(%d).NumItems,0)' % rid if optional else ''
            if vis:
                x(d + 3, '<visible>%s</visible>' % vis)
            x(d + 2, '</control>')
            skeleton(x, d + 2, ti, ri, rid, kind, path, optional)
            x(d + 2, '<control type="list" id="%d">' % rid)
            gap = g['step'] - g['w']
            if is_rtl(path):
                left, width, _peek = rtl_slots(g)
                x(d + 3, '<left>%d</left><top>40</top><width>%d</width><height>%d</height>' % (left, width, g['list_h']))
            else:
                x(d + 3, '<left>%d</left><top>40</top><width>%d</width><height>%d</height>' % (MARGIN - PAD, 1920 - MARGIN + PAD, g['list_h']))
            x(d + 3, '<orientation>horizontal</orientation><preloaditems>2</preloaditems>')
            x(d + 3, '<scrolltime tween="cubic" easing="out">260</scrolltime>')
            top_up = chip_ids(ti, tab)[0] if tab['chips'] else tab_button(ti)
            for cond, target in nav_chain(list(reversed(ids[:ri])), top_up):
                x(d + 3, '<onup condition="%s">%d</onup>' % (cond, target))
            # Kodi wraps a list with no action at its edge: the row's far end would
            # jump back to its start (and the start, on the right, to the far end)
            x(d + 3, '<onleft>noop</onleft><onright>noop</onright>')
            # Focus decides the tab: Kodi's skin reload gives the focus back to the
            # control that had it, after the first tab's button took it
            x(d + 3, '<onfocus>SetProperty(povil.tab,%s,home)</onfocus>' % tab['id'])
            x(d + 3, '<onfocus>SetProperty(povil.focus,%d,home)</onfocus>' % rid)
            for cond, target in nav_chain(ids[ri + 1:]):
                x(d + 3, '<ondown condition="%s">%d</ondown>' % (cond, target))
            if is_rtl(path):
                x(d + 3, '<animation effect="fade" start="100" end="0" time="0" condition="%s">Conditional</animation>' % rtl_waiting(rid))
                short_rows(x, d + 3, 'Container(%d)' % rid, kind)
            x(d + 3, '<include content="POVIL_Item_%s"><param name="id" value="%d" /></include>' % (kind, rid))
            if path == 'static:settings':
                x(d + 3, '<content>')
                for label, icon, click, vis_item in reversed(SETTINGS_ITEMS):
                    x(d + 4, '<item>')
                    x(d + 5, '<label>%s</label>' % e(label))
                    x(d + 5, '<property name="povil_rtl">1</property>')
                    x(d + 5, '<icon>%s</icon>' % e(icon))
                    x(d + 5, '<onclick>%s</onclick>' % e(click))
                    if vis_item:
                        x(d + 5, '<visible>%s</visible>' % vis_item)
                    x(d + 4, '</item>')
                x(d + 3, '</content>')
            else:
                x(d + 3, '<content target="videos">$VAR[POVIL_Path_%d]</content>' % rid)
            x(d + 2, '</control>')
            if is_rtl(path):
                peek(x, d + 2, rid, kind, 40)
            x(d + 1, '</control>')
        x(d, '</control>')


def main():
    skin = sys.argv[1]
    folder = os.path.join(skin, 'xml')
    with open(os.path.join(folder, 'Includes_POVIL_Home.xml'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(gen_includes())
    with open(os.path.join(folder, 'Home.xml'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(gen_home())
    write_timers(folder)
    print('home generated:', sum(len(t['rows']) for t in TABS), 'rows,', sum(len(t['chips']) for t in TABS), 'chips')


if __name__ == '__main__':
    main()
