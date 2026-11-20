# -*- coding: utf-8 -*-
"""Generate the Kodi POV IL home of skin.povil.onyx.

    python gen_home.py ../../skin.povil.onyx

Writes xml/Home.xml and xml/Includes_POVIL_Home.xml. Edit the TABS table
below, not the generated XML.

Layout (1920x1080): tabs top right (right to left, the first tab is the
rightmost), clock top left, a hero for the focused item on the right
(fanart backdrop, clear logo or title, details, plot), shortcut chips under
it, then the tab's rows. Rows of a tab only exist while that tab is
selected, so a tab's lists load the first time it is shown and stay loaded.
One tab has no button: a streaming service's page (see "service hubs").
"""
import os
import sys
from urllib.parse import quote
from xml.sax.saxutils import escape

import ratings_row as RR
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


# A row of the viewer's own saved titles is asked again the moment one is added or removed: its address
# carries this home-window property, which the Wizard's two toggle hooks in POV set (POV's own favourites,
# and the Trakt / MDBList / TMDb list manager). A changed address reloads that row alone; the ping that
# reloads every row (UpdateLibrary) once crashed Kodi beside Container.Refresh, and is not used here.
LISTS_TOKEN = '&povil_t=$INFO[Window(home).Property(povil.lists.t)]'
# The time the last film or episode ended (the timers povil_play_seen / povil_play_done; never a trailer): a row on a
# screen of SLOT_TABS that changes after a film carries it, so Kodi reads it again then -- those slots ask nothing
# again at every playback (sortby size), and POV's own refresh after a film (UpdateLibrary) did not reach a row in QA
PLAY_TOKEN = '&povil_p=$INFO[Window(home).Property(povil.play.t)]'


def personal(path):
    return path + LISTS_TOKEN


# The ratings row (ratings_row.py, the Wizard's ratings.py): the hidden label that holds the title's key
# (the label after it tests TMDb's number), and the home-window properties the answer comes in. The
# player's are its own: what is playing is another title than the one the home has in its hero.
RATINGS_KEY, RATINGS_SLOT = 9807, 'povil.rt.'
# The trailer behind the hero (the Wizard's trailers.py): the hidden label that holds the address of the
# hero title's trailer, the viewer's switch, and how long the screen rests on a title before it is asked.
# The switch says OFF: a skin setting is unset until someone sets it, and the trailers are on for everyone
# until the viewer says otherwise (the owner, Nov 2026).
# (9809: 9808 is the ratings row's hidden TMDb label, RATINGS_KEY + 1 -- the two shared an id until 1.0.17,
# and Kodi hands out whichever control of an id is visible first)
TRAILER_KEY, TRAILER_OFF_SWITCH = 9809, 'POVILNoTrailers'
# The watched mark's colour on the home's pictures, the viewer's choice (a viewer, Nov 2026: "how do I make the V
# green?"): Kodi's own Skin.SelectBool list -- one of these on, the others off; none on (as until now) is gold.
# (SelectBool names its heading and choices by string id only -- plain text showed Kodi's string 0, "Programs", seen
# in the QA Kodi: the skin's own strings 31900-31904, gen_strings.py)
WATCHED_COLOURS = (('POVILWatchedGold', 'זהב', 'povil_gold', 31901), ('POVILWatchedGreen', 'ירוק', 'FF34C759', 31902),
                   ('POVILWatchedWhite', 'לבן', 'FFFFFFFF', 31903), ('POVILWatchedBlue', 'תכלת', 'FF5AC8FA', 31904))
WATCHED_CHOICE = 'Skin.SelectBool(31900,%s)' % ','.join('%d|%s' % (sid, s) for s, _name, _c, sid in WATCHED_COLOURS)
# The players the controls can show besides Onyx's own (gen_osd_styles.py), as the settings tile names them
PLAYER_STYLES = (('netflix', 'נטפליקס'), ('advanced', 'מתקדם'), ('simple', 'פשוט'), ('pretty', 'גדול'))
TRAILERS_ON, TRAILERS_OFF = '!Skin.HasSetting(%s)' % TRAILER_OFF_SWITCH, 'Skin.HasSetting(%s)' % TRAILER_OFF_SWITCH
# Where a title's trailer plays behind its hero: the home, and the Videos window's views 51 and 55 (gen_views.py --
# a season's list, a search's results, the inner lists; Onyx 1.0.26). Each has the hidden label TRAILER_KEY.
TRAILER_SCREEN = '[Window.IsActive(home) | Window.IsActive(videos)]'


def by_choice(setting, default, choices, cond):
    """cond(seconds) for the number of seconds the viewer chose in Skin.String(setting) (the Wizard's
    trailer_timing.py writes it): the default while none is chosen; a value not among the choices never holds."""
    parts = []
    for seconds in choices:
        chosen = 'String.IsEqual(Skin.String(%s),%d)' % (setting, seconds)
        if seconds == default:
            chosen = '[%s | String.IsEmpty(Skin.String(%s))]' % (chosen, setting)
        parts.append('[%s + %s]' % (chosen, cond(seconds)))
    return '[%s]' % ' | '.join(parts)


# How long the screen rests on a title before its trailer is asked -- the viewer's choice (the tile "תזמון
# טריילרים"). The owner, Nov 2026: "the trailer should play as fast as possible, almost at once" -- it took
# about 4 s on his LG: a 3 s rest, then the trailer was read from YouTube. Now 1 s by default, and the Wizard
# reads the trailer while the screen rests (povil.tr.peek, the timer povil_trailer_peek).
TRAILER_WAIT, TRAILER_WAIT_S, TRAILER_WAITS = 'POVILTrailerWait', 1, (1, 2, 3, 5)
TRAILER_REST = by_choice(TRAILER_WAIT, TRAILER_WAIT_S, TRAILER_WAITS, lambda seconds: 'System.IdleTime(%d)' % seconds)
# (and its first picture has come: the Wizard clears povil.tr.opening then. On the owner's LG, Nov 2026, the
# player said it had a video while it hung opening one that never showed a picture -- the home faded away into
# "the trailer to itself" over nothing, and only a key brought it back)
TRAILER_SHOWN = ('Player.HasVideo + !String.IsEmpty(Window(home).Property(povil.tr.on)) + '
                 'String.IsEqual(Window(home).Property(povil.tr.on),Window(home).Property(povil.tr.ask)) + '
                 'String.IsEmpty(Window(home).Property(povil.tr.opening))')
# The trailer to itself (the owner, Nov 2026: "so the viewer can watch the trailer if they want, and read
# it" -- POV names a title's Hebrew trailer when TMDb has one, and its words are in the picture): once
# the trailer has been on for a few seconds and the remote is still, everything over the picture fades
# away and the whole screen is the trailer. Any key brings the home back.
# How long that takes is the viewer's choice too (the same tile; "0" there: never) -- 4 s by default, as it
# always was (the owner: "no later than it is today").
TRAILER_FULL, TRAILER_ALONE_AFTER_S, TRAILER_FULLS, TRAILER_STILL_S = 'POVILTrailerFull', 4, (2, 3, 4, 6, 8, 12), 3
# (Skin.TimerIsRunning: a stopped timer keeps its last count -- 39.7 s, read in the QA Kodi after a title
# change -- and until Kodi starts it again for the next trailer, about half a second later, that count was
# read: the home faded at the new trailer's first picture, 2 titles of 6 on 0.5.19)
TRAILER_ALONE = '%s + Skin.TimerIsRunning(povil_trailer_shown) + %s' % (TRAILER_SHOWN, by_choice(
    TRAILER_FULL, TRAILER_ALONE_AFTER_S, TRAILER_FULLS,
    lambda seconds: 'Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_trailer_shown),%d) + System.IdleTime(%d)'
                    % (seconds, min(seconds, TRAILER_STILL_S))))
TRAILER_FADE = ('<animation effect="fade" start="100" end="0" time="900" tween="sine" easing="inout" condition="%s">Conditional</animation>'
                % TRAILER_ALONE)
# The trailer's Hebrew subtitles, DRAWN BY THE SKIN (Onyx 1.0.30): the Wizard (trailer_subs.py, 0.5.33) writes the line
# of the moment into this property as the trailer plays. Kodi draws no subtitles over a video window when the video
# is on a layer of its own -- Android's MediaCodec surface, the owner's devices: CGUIVideoControl::Render only clears
# a hole there and never renders the overlays (Kodi 21's code); on a PC the picture and its subtitles are drawn
# together, which is why the QA Kodi showed them. The owner, Nov 2026: "much of the trailer passed, and no Hebrew
# subtitle appeared yet" -- his log had the subtitle loaded at once.
TRAILER_LINE = 'Window(home).Property(povil.tsub.line)'
TRAILER_HAS_LINES = 'Window(home).Property(povil.tsub.on)'     # the trailer playing has them (the shade)
PLAYER_RATINGS_KEY, PLAYER_RATINGS_SLOT = 7920, 'povil.rtp.'


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
# ---------------------------------------------------------------- service hubs
# A streaming service's own page (a viewer sent another app's: "the same view as the home, filtered to
# Netflix / Disney / Apple, with films / series / all at the top" -- and its author: "take it"). It is a
# tab of the home that has no button: a service's chip names the service in home-window properties and
# shows it. One tab serves every service and all three choices: each row's address carries the service
# (povil.hub.id, TMDb's watch provider; povil.hub.net, its network) and follows povil.hub.type, so
# choosing films, series or another service only changes what the same rows ask for.
# The lists are TMDb's discover through POV (tmdb_media_discover); povil_hub=1 lets the Wizard keep them
# as saved lists and keeps them out of POV's own discover history.
HUB = 'hub'
HUB_TYPES = ('all', 'movie', 'tv')
# (chip label, the name shown, TMDb watch provider id, TMDb network id)
SERVICES = [('נטפליקס', 'Netflix', 8, 213), ('דיסני+', 'Disney+', 337, 2739), ('Apple TV+', 'Apple TV+', 350, 2552),
            ('Prime Video', 'Prime Video', 9, 1024), ('HBO Max', 'HBO Max', 1899, 3186)]
# (Paramount+ is not here: its provider id, 531, answered two series in the QA Kodi on 18 Nov 2026 -- TMDb
# lists the service under newer ids now; a page that is nearly empty is worse than no page)
# ("new" lists end with this month, not today: the address is the saved list's name, and a date in it
# would keep a new copy of every such row every day)
TODAY = '$INFO[System.Date(yyyy-mm)]-28'


def hub_prop(name):
    return '$INFO[Window(home).Property(povil.hub.%s)]' % name


def hub_type(kind):
    return 'String.IsEqual(Window(home).Property(povil.hub.type),%s)' % kind


def hub_service(provider):
    return 'String.IsEqual(Window(home).Property(povil.hub.id),%d)' % provider


def hub_open(service, kind=None):
    """What a service's chip does: name the service (and, from a tab, what to show of it) and show the page."""
    _label, name, provider, network = service
    steps = ['SetProperty(povil.hub.id,%d,home)' % provider, 'SetProperty(povil.hub.net,%d,home)' % network,
             'SetProperty(povil.hub.name,%s,home)' % name]
    if kind:
        # (the page's lower rows wait again for the viewer to go down to them: another service is nine new lists)
        steps += ['ClearProperty(povil.deep.%s,home)' % HUB, 'ClearProperty(povil.far.%s,home)' % HUB,
                  'SetProperty(povil.hub.type,%s,home)' % kind, 'SetProperty(povil.tab.%s,1,home)' % HUB,
                  'SetProperty(povil.tab,%s,home)' % HUB,
                  # the page's chips are not on the screen until the next frame: a timer moves the focus (povil_hub_enter)
                  'SetProperty(povil.hub.enter,1,home)']
    return steps


def hub_list(kind, title, extra, provider=True):
    """(title, address) of one list of the service: TMDb's discover for films or series, through POV."""
    query = 'discover/%s?language=en-US&region=US' % ('movie' if kind == 'movie' else 'tv')
    if provider:
        query += '&watch_region=US&with_watch_monetization_types=flatrate&with_watch_providers=' + hub_prop('id')
    query += extra + '&page=%s'
    mode = 'build_movie_list' if kind == 'movie' else 'build_tvshow_list'
    # ($INFO[...] stays as it is for Kodi to fill; everything else is one parameter's value)
    return title, POV + '?mode=%s&action=tmdb_media_discover&povil_hub=1&name=%s&query=%s' % (
        mode, quote(title), quote(query, safe='$[]().-'))


def _hub_rows():
    m_pop, t_pop = '&sort_by=popularity.desc', '&sort_by=popularity.desc'
    m_new = '&sort_by=primary_release_date.desc&primary_release_date.lte=%s&vote_count.gte=15' % TODAY
    t_new = '&sort_by=first_air_date.desc&first_air_date.lte=%s&vote_count.gte=10' % TODAY
    m_top = '&sort_by=vote_average.desc&vote_count.gte=400'
    t_top = '&sort_by=vote_average.desc&vote_count.gte=200'
    originals = '&sort_by=popularity.desc&with_networks=' + hub_prop('net')
    genre = lambda ids: '&sort_by=popularity.desc&with_genres=' + ids
    film = lambda title, extra: hub_list('movie', title, extra)
    show = lambda title, extra, provider=True: hub_list('tv', title, extra, provider)
    # per row: its tiles' shape, and what it lists for each choice (all / films / series)
    return [
        ('ranked', dict(all=film('הסרטים המובילים', m_pop), movie=film('המובילים עכשיו', m_pop), tv=show('המובילות עכשיו', t_pop))),
        ('landscape', dict(all=show('סדרות פופולריות', t_pop), movie=film('חדשים', m_new), tv=show('חדשות', t_new))),
        ('poster', dict(all=film('סרטים חדשים', m_new), movie=film('המדורגים ביותר', m_top), tv=show('הפקות מקור', originals, False))),
        ('landscape', dict(all=show('סדרות חדשות', t_new), movie=film('אקשן והרפתקאות', genre('28|12')), tv=show('המדורגות ביותר', t_top))),
        ('poster', dict(all=show('הפקות מקור', originals, False), movie=film('קומדיה', genre('35')), tv=show('דרמה', genre('18')))),
        ('landscape', dict(all=film('סרטים שאהבו במיוחד', m_top), movie=film('דרמה', genre('18')), tv=show('קומדיה', genre('35')))),
        ('poster', dict(all=show('סדרות שאהבו במיוחד', t_top), movie=film('מדע בדיוני ופנטזיה', genre('878|14')), tv=show('פשע ומסתורין', genre('80|9648')))),
        ('landscape', dict(all=film('אקשן והרפתקאות', genre('28|12')), movie=film('מתח ואימה', genre('53|27')), tv=show('מדע בדיוני ופנטזיה', genre('10765')))),
        ('poster', dict(all=show('דרמה', genre('18')), movie=film('לכל המשפחה', genre('10751|16')), tv=show('ילדים ומשפחה', genre('10762|10751')))),
    ]


HUB_ROWS = _hub_rows()
# The rows of the page beyond its third wait until the viewer goes down into the rows (nine lists at
# once would be nine POV calls the moment the page opens)
HUB_NEAR_ROWS = 3

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
         chips=[(s[0], hub_open(s, 'movie')) for s in SERVICES[:4]] + [('בכורות', videos(pov_movies('tmdb_movies_premieres'))),
                ('אקשן', MOVIE_GENRE(28)), ('קומדיה', MOVIE_GENRE(35)), ('דרמה', MOVIE_GENRE(18)),
                ('מתח', MOVIE_GENRE(53)), ('אימה', MOVIE_GENRE(27)), ('מדע בדיוני', MOVIE_GENRE(878)),
                ('כל הסרטים', videos(pov_mode('navigator.main', action='MovieList'))),
                ('Umbrella', videos(UMB + '?action=movieNavigator'), 'System.HasAddon(plugin.video.umbrella)')]),
    dict(id='tv', label='סדרות', click=videos(pov_mode('navigator.main', action='TVShowList')),
         blurb='הסדרות שכולם מדברים עליהן, והפרק הבא שלכם.',
         rows=[('טרנדיות עכשיו', pov_tv('trakt_tv_trending'), 'poster', False),
               ('פופולריות', pov_tv('tmdb_tv_popular'), 'landscape', False),
               ('הפרק הבא', pov_mode('build_next_episode'), 'landscape', True)],
         chips=[(s[0], hub_open(s, 'tv')) for s in SERVICES[:4]] + [
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
         # the user's own live TV (IPTV Simple and the like, Kodi's PVR): a chip and a
         # row of its channels (the Wizard's pvr_row), both hidden without one
         rows=[('ערוצים', IDAN['idan_live'], 'square', False),
               ('רדיו', IDAN['radio'], 'square', False),
               # (p= set once Kodi has its channels: IPTV Simple loads its list after
               # the start, and a row asked before then would stay empty)
               ('ערוצי ה-IPTV שלי', WIZARD + '?mode=pvr_row&p=$INFO[Window(home).Property(povil.pvr)]', 'square', True)],
         chips=[('ערוצים', videos(IDAN['idan_live'])),
                # (any live-TV client of Kodi's, not IPTV Simple alone -- a viewer, Nov 2026, after moving to Onyx: "my
                # IPTV is not found; in the earlier skins it was there"; Onyx 1.0.28)
                ('IPTV שלי', 'ActivateWindow(TVChannels)', '[PVR.HasTVChannels | System.HasPVRAddon | System.HasAddon(pvr.iptvsimple)]'),
                ('רדיו', videos(IDAN['radio'])),
                ('ספורט 1', videos(IDAN['sport1'])), ('Eco99', videos(IDAN['eco99'])),
                ('100FM', videos(IDAN['fm100'])),
                ('מדריך שידורים', 'ActivateWindow(TVGuide)', 'PVR.HasTVChannels')]),
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
               ('סרטים שמורים', personal(pov_movies('favorites_movies')), 'poster', True),
               ('סדרות שמורות', personal(pov_tv('favorites_tvshows')), 'poster', True),
               ('הסרטים שלי (MDBList)', personal(pov_movies('mdblist_my_movies')), 'poster', True),
               ('הסדרות שלי (MDBList)', personal(pov_tv('mdblist_my_tvshows')), 'poster', True)],
         # MDBList's chips once its rows have items (a connected account): no
         # settings read on every frame
         # POV's own saved lists first: they need no account (asked for by a viewer: the chips named
         # Trakt and MDBList only, and the two POV rows had no way to open in full)
         chips=[('סרטים ב-POV', videos(pov_movies('favorites_movies'))),
                ('סדרות ב-POV', videos(pov_tv('favorites_tvshows'))),
                # POV's own favourites newest first or by name (a viewer: "the ascending / descending order
                # does nothing -- it needs an A-to-Z setting"); the Wizard switches and says which
                ('מיון: א-ב / חדש קודם', plugin_run(WIZARD + '?mode=pov_favorites_order')),
                ('סרטים ב-Trakt', videos(pov_movies('trakt_my_movies'))),
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
    # A streaming service's page: no button in the tab bar (hidden) -- a service's chip shows it. Its
    # first chip names the service and shows all of it; then films and series, the other services, back.
    dict(id=HUB, hidden=True, label=hub_prop('name'), click='noop',
         blurb='מה שיש לצפות בו בשירות הזה: בחרו הכול, סרטים או סדרות.',
         rows=[('$VAR[POVIL_HubTitle_%d]' % k, 'hub:%d' % k, kind, False) for k, (kind, _lists) in enumerate(HUB_ROWS)],
         chips=[(hub_prop('name') + '  ·  הכול', ['SetProperty(povil.hub.type,all,home)'], None, hub_type('all')),
                ('סרטים', ['SetProperty(povil.hub.type,movie,home)'], None, hub_type('movie')),
                ('סדרות', ['SetProperty(povil.hub.type,tv,home)'], None, hub_type('tv'))] +
               [(s[0], hub_open(s), None, hub_service(s[2])) for s in SERVICES] +
               [('חזרה', ['SetFocus(9000)'])]),
    # Everything the viewer is in the middle of, films and series together (the owner, Nov 2026: "where is
    # continue watching for whatever I am in the middle of? ... I want it as continue watching for films and
    # for series"). The films and series tabs keep their own rows of it; this is the one place for all of it.
    # It comes LAST here (a tab's place in TABS numbers its rows and chips, so nothing that was there moves --
    # not the service page's either); its place in the BAR is third.
    dict(id='continue', label='המשך צפייה', click=videos(pov_mode('build_next_episode')),
         blurb='כל מה שאתם באמצע: הפרק הבא של הסדרות שלכם, והסרטים והפרקים שהתחלתם.',
         rows=[('הפרק הבא', pov_mode('build_next_episode'), 'landscape', True),
               ('סרטים שהתחלתם', pov_movies('in_progress_movies'), 'landscape', True),
               ('פרקים שהתחלתם', pov_mode('build_in_progress_episode'), 'landscape', True)],
         chips=[('סדרות שהתחלתם', videos(pov_tv('in_progress_tvshows'))),
                ('כל הסרטים שהתחלתם', videos(pov_movies('in_progress_movies'))),
                ('כל הפרקים הבאים', videos(pov_mode('build_next_episode')))]),
]

# The build's Wizard is installed. Onyx also runs on a Kodi without it (a viewer, Nov 2026: Onyx alone on his CoreELEC
# box, the build on his Shield -- the tiles that ran the Wizard did nothing there). A tile asks the Wizard when it is
# there and the skin's own dialog when it is not (gen_standalone.py); a tile with nothing to do without the Wizard
# shows only with it.
WIZ = 'System.HasAddon(plugin.program.kodipovilwizard)'


# ... and says it can do what a tile asks (the Wizard's start-up names the modes it has, from 0.5.27): the skin can be
# newer than the Wizard for a while, and a Wizard that does not know a mode does nothing at all
WIZARD_MODES = 'Window(home).Property(povil.wizard.modes)'


# the build's menu editor inside the skin, for Onyx without the Wizard (gen_standalone.py, Onyx 1.0.29)
EDITOR_SCRIPT = 'special://skin/scripts/povil_menu_editor.py'


def by_wizard(wizard_action, *own_actions, mode=None):
    """onclick for a tile: the Wizard's action when it is installed (and, with `mode`, says it has that mode), else
    the skin's own (in order)."""
    able = WIZ if not mode else 'String.Contains(%s,%s)' % (WIZARD_MODES, mode)
    return [(able, wizard_action)] + [('!' + able, action) for action in own_actions]


# The log, without the Wizard: Kodi's own uploader (script.kodi.loguploader, in Kodi's official repository), installed
# the first time it is asked for (Kodi asks the viewer); with the Wizard, its uploader (address and QR), as the
# favourite "שליחת לוג" does.
LOG_UPLOADER = 'script.kodi.loguploader'
SEND_LOG = [(WIZ, plugin_run(WIZARD + '?mode=uploadlog')),
            ('!%s + System.HasAddon(%s)' % (WIZ, LOG_UPLOADER), 'RunScript(%s)' % LOG_UPLOADER),
            ('!%s + !System.HasAddon(%s)' % (WIZ, LOG_UPLOADER), 'InstallAddon(%s)' % LOG_UPLOADER)]

SETTINGS_ITEMS = [
    # label, icon, onclick (one action, or [(condition, action)] run in order), visible
    ('הוויזארד', '$INFO[System.AddonIcon(plugin.program.kodipovilwizard)]', videos(WIZARD), WIZ),
    ('החלפת סקין', '$INFO[System.AddonIcon(plugin.program.kodipovilwizard)]', plugin_run(WIZARD + '?mode=profile_skin'), WIZ),
    ('כתוביות', '$INFO[System.AddonIcon(service.subtitles.kodipovilai)]', 'Addon.OpenSettings(service.subtitles.kodipovilai)', 'System.HasAddon(service.subtitles.kodipovilai)'),
    ('מנוע החיפוש', 'special://home/addons/plugin.video.pov/resources/skins/Default/media/search.png',
     'RunScript(service.subtitles.kodipovilai,action=search_provider)', 'System.HasAddon(service.subtitles.kodipovilai)'),
    ('הגדרות POV', '$INFO[System.AddonIcon(plugin.video.pov)]', 'Addon.OpenSettings(plugin.video.pov)', 'System.HasAddon(plugin.video.pov)'),
    ('הגדרות Umbrella', '$INFO[System.AddonIcon(plugin.video.umbrella)]', 'Addon.OpenSettings(plugin.video.umbrella)', 'System.HasAddon(plugin.video.umbrella)'),
    # POV's own clear-all-cache (the owner, 17 Nov 2026: the other skins have the button, Onyx had none)
    ('ניקוי קאש', 'DefaultAddonRepository.png', plugin_run(POV + '?mode=clear_all_cache&isFolder=false'), 'System.HasAddon(plugin.video.pov)'),
    # which screens the top bar shows (the Wizard asks, onyx_tabs.py): any but films and settings can go
    ('בחירת מסכים', 'DefaultAddonLookAndFeel.png',
     by_wizard(plugin_run(WIZARD + '?mode=onyx_tabs'), 'SetProperty(povil.choice,tabs,home)', 'ActivateWindow(1161)'), ''),
    # POV's and Umbrella's own lists on every device of the viewer, through the viewer's own Google Drive
    # (the Wizard's cloud_sync)
    ('סנכרון בין מכשירים', 'DefaultNetwork.png', plugin_run(WIZARD + '?mode=cloud_sync'), WIZ),
    # which player the controls show (the Wizard asks, onyx_player_style.py; gen_osd_styles.py draws them)
    ('$VAR[POVIL_PlayerTile]', 'povil/osd/layout.png',
     by_wizard(plugin_run(WIZARD + '?mode=player_style'), 'SetProperty(povil.choice,player,home)', 'ActivateWindow(1161)'), ''),
    # the viewer's own rows (CUSTOM_TABS)
    # (without the Wizard -- or one before 0.5.28, which knows the rows only: the same dialogs, inside the skin,
    # Onyx 1.0.29: gen_standalone.py copies the Wizard's menu_editor.py, custom_rows.py and home_rows.py)
    ('שורות וכפתורים משלי', 'DefaultFolder.png',
     by_wizard(plugin_run(WIZARD + '?mode=custom_rows'), 'RunScript(%s,custom_rows)' % EDITOR_SCRIPT, mode='custom_chips'), ''),
    # the order of a screen's rows: up, down, hidden, shown again (SLOT_TABS)
    ('סדר השורות', 'DefaultPlaylist.png',
     by_wizard(plugin_run(WIZARD + '?mode=home_rows'), 'RunScript(%s,home_rows)' % EDITOR_SCRIPT, mode='home_rows'), ''),
    # the menu editor (the Wizard's menu_editor.py, Onyx 1.0.28): the bar's order, names and buttons of the viewer's
    # own; the chips under each tab; the rows. Without a Wizard that has it: the same editor inside the skin (a
    # viewer with Onyx alone, Nov 2026, had the rows and chips only -- the skin's windows 1162 and 1163)
    ('עריכת התפריט', 'DefaultAddonLookAndFeel.png',
     by_wizard(plugin_run(WIZARD + '?mode=menu_editor'), 'RunScript(%s)' % EDITOR_SCRIPT, mode='menu_editor'), ''),
    # the watched mark's colour (WATCHED_COLOURS)
    ('$VAR[POVIL_WatchedTile]', 'povil/check.png', WATCHED_CHOICE, ''),
    # the trailer behind the hero (trailers.py): on unless switched off here; the tile says which
    # (the Wizard plays them: without it there are none to switch)
    ('$VAR[POVIL_TrailersTile]', 'DefaultAddonVideo.png', 'Skin.ToggleSetting(%s)' % TRAILER_OFF_SWITCH,
     'System.HasAddon(plugin.video.youtube) + ' + WIZ),
    # how soon it starts, and how soon it has the screen to itself (the Wizard asks, trailer_timing.py)
    ('תזמון טריילרים', 'DefaultAddonVideo.png', plugin_run(WIZARD + '?mode=trailer_timing'),
     'System.HasAddon(plugin.video.youtube) + %s + %s' % (WIZ, TRAILERS_ON)),
    ('שליחת לוג', 'DefaultAddonProgram.png', SEND_LOG, ''),
    ('הגדרות הסקין', 'DefaultAddonSkin.png', 'ActivateWindow(SkinSettings)', ''),
    ('הגדרות קודי', 'DefaultAddonService.png', 'ActivateWindow(Settings)', ''),
    ('הרחבות', 'DefaultAddonsInstalled.png', 'ActivateWindow(AddonBrowser)', ''),
    ('פרופילים', 'DefaultUser.png', plugin_run(WIZARD + '?mode=profiles'), WIZ),
    ('כיבוי', 'DefaultAddonProgram.png', 'ActivateWindow(ShutdownMenu)', ''),
]

# ---------------------------------------------------------------- geometry
MARGIN = 90
# A list clips what it draws to its own rectangle: the focused tile's zoom and
# gold glow reach 42 px past the tile. Every list starts PAD before its first
# tile and every item draws its tile PAD in, so nothing is cut at the edges.
PAD = 42
ROWS_Y = 618
TAB_W = 146         # (172 until 1.0.18: nine tabs now, and the bar must end right of the power button)
# a tab whose name is longer than that (seen cut short in the QA Kodi at one width for all); since the bar's
# bigger font (povil_tab 34, 1.0.23) the longest name has a little more and the two shortest a little less, the
# bar as wide as it was: 'ישראלי' and 'המשך צפייה' read as one phrase otherwise (seen in the QA Kodi)
TAB_WIDE = {'continue': 220, 'favourites': 170, 'live': 166, 'tv': 140, 'kids': 140}
GEOM = {
    # list height, row block height (title + list), item size, item spacing
    'poster': dict(list_h=340, block=402, w=196, h=294, step=226),
    'landscape': dict(list_h=300, block=362, w=352, h=198, step=382),
    'square': dict(list_h=290, block=352, w=200, h=200, step=230),
    # posters with their place in the list beside them, as large as the poster is tall: a poster's
    # size, a wider step for the numeral (the first row of a service's page)
    # (edge: what of a slot lies past the right margin -- for the other rows the gap between two tiles;
    # here the numeral is the slot's right part and must end at the margin)
    'ranked': dict(list_h=340, block=402, w=196, h=294, step=330, edge=16),
}


def shape(kind):
    """The shape of a row's pictures: a ranked row's are posters."""
    return 'poster' if kind == 'ranked' else kind
GOLD = 'povil_gold'


def tab_cond(tab):
    return 'String.IsEqual(Window(home).Property(povil.tab),%s)' % tab['id']


POWER_BUTTON = 9099
# the tabs with a button in the tab bar; a hidden tab (a service's page) comes after them all, so a
# shown tab's place in TABS is its place in the bar
SHOWN_TABS = [tab for tab in TABS if not tab.get('hidden')]


def tab_button(ti):
    return 9010 + ti


# THE BAR. The order the tabs stand in, the first on the right -- not their order in TABS -- and which of them
# the viewer may take off the bar (a viewer, Nov 2026: "I want to remove live TV and Israeli and put a screen
# of my own choice there, say continue watching"). A tab is off the bar while the skin setting
# POVILHideTab_<id> is set (the Wizard's question "בחירת מסכים", resources/libs/onyx_tabs.py, sets and clears
# them); films and settings always stay -- the home opens on the first, and the second is the way back.
BAR = ['movies', 'tv', 'continue', 'israeli', 'live', 'kids', 'favourites', 'search', 'settings']
ALWAYS_SHOWN = ('movies', 'settings')
assert sorted(BAR) == sorted(tab['id'] for tab in SHOWN_TABS)
TAB_INDEX = dict((tab['id'], ti) for ti, tab in enumerate(TABS))


def tab_hidden(tab_id):
    return 'Skin.HasSetting(POVILHideTab_%s)' % tab_id


def tab_width(tab_id):
    return TAB_WIDE.get(tab_id, TAB_W)


def tab_line(tab_id):
    # the line under the chosen tab, a texture as wide as the tab's button (gen_tabline.py)
    return 'tab_line_%d.png' % tab_width(tab_id)


BAR_W = sum(tab_width(tab_id) for tab_id in BAR)

# The viewer's own bar (Onyx 1.0.28 / Wizard 0.5.29, the menu editor "עריכת התפריט"; a viewer, via the owner, Nov
# 2026, with a mod of 1.0.26 his own Claude made: "I'd be glad if you put it in yours -- I want to work only with
# your skin, updates included"). BAR_PLACES places; place p shows the tab named in Skin.String(POVILBar_<p>) once
# Skin.HasSetting(POVILBarOrdered), else BAR[p]. Kodi lays a grouplist out in its children's order, so each place
# holds a button of every tab that may stand there and shows only the one it holds (bar_button). A tab's name:
# Skin.String(POVILTabName_<id>), else the build's (POVIL_TabLabel_<id>). OWN_TABS buttons of the viewer's own
# (POVILTabOwn_<n>_path / _cmd / _name), opened as his chips are: as narrow as the narrowest tab -- one takes a
# hidden tab's place (the Wizard keeps nine on the bar), so the bar is never wider than it was.
OWN_TABS = 2
OWN_TAB_IDS = ['own%d' % n for n in range(1, OWN_TABS + 1)]
OWN_TAB_W = 140
for _own in OWN_TAB_IDS:
    TAB_WIDE[_own] = OWN_TAB_W
BAR_IDS = BAR + OWN_TAB_IDS
BAR_PLACES = len(BAR_IDS)


def bar_shows(p, tab_id):
    """The condition that place p holds tab_id."""
    chosen = 'String.IsEqual(Skin.String(POVILBar_%d),%s)' % (p, tab_id)
    if p < len(BAR) and BAR[p] == tab_id:
        return '[!Skin.HasSetting(POVILBarOrdered) | %s]' % chosen
    return '[Skin.HasSetting(POVILBarOrdered) + %s]' % chosen


def bar_button(p, tab_id):
    return 9600 + p * 16 + BAR_IDS.index(tab_id)


def bar_visible(tab_id):
    """A tab of the bar is on it (not taken off; a button of the viewer's has something to do)."""
    conds = [] if tab_id in ALWAYS_SHOWN else ['!' + tab_hidden(tab_id)]
    if tab_id in OWN_TAB_IDS:
        conds.append(own_set('POVILTabOwn_%s' % tab_id[3:]))
    return ' + '.join(conds)


def to_tab(tab_id):
    """The action that gives the focus to a tab's button, wherever on the bar it stands."""
    return 'SetFocus($VAR[POVIL_TabButton_%s])' % tab_id



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


# The viewer's own rows (the Wizard's custom_rows.py, the settings tile "שורות משלי"; a viewer, Nov 2026: "let me add
# the films on my hard drive"): CUSTOM_SLOTS rows at the end of these tabs, each the folder in a skin string, shown
# only while it has one and it has items
CUSTOM_TABS, CUSTOM_SLOTS = ('movies', 'tv', 'kids', 'favourites'), 3
CUSTOM_TAB_NAMES = (('movies', 'סרטים'), ('tv', 'סדרות'), ('kids', 'ילדים'), ('favourites', 'מועדפים'))
for _tab in TABS:
    if _tab['id'] in CUSTOM_TABS:
        _tab['rows'] = list(_tab['rows']) + [('$VAR[POVIL_RowName_%s_%d]' % (_tab['id'], _n), 'custom:%s_%d' % (_tab['id'], _n),
                                             'poster', True) for _n in range(1, CUSTOM_SLOTS + 1)]


# The viewer's own chips (Onyx 1.0.27 / Wizard 0.5.28; a viewer, via the owner, Nov 2026: "how can I add a button that
# takes me into my films library, like the buttons on top -- Netflix, Disney?"): CUSTOM_CHIPS on each screen of
# CUSTOM_TABS, each the folder in the skin strings POVILChip_<tab>_<n>_path / _name (the same tile and dialogs as the
# rows), shown only while it has one; it opens the folder in the Videos window -- Kodi's library there has its own
# sort menu. After a screen's services (CUSTOM_CHIP_AT), else last. Their ids are their own (custom_chip_ids): the
# build's chips keep theirs.
# Onyx 1.0.28 (the menu editor, "עריכת התפריט"; the same viewer: "add, move and hide shortcuts under each button"):
# CUSTOM_CHIPS of the viewer's own on each screen, each standing where he chose (POVILChip_<tab>_<n>_at: start --
# the rightmost --, mid -- after the services, where a screen has them -- or end), opening a folder (_path) or doing
# what a favourite, an add-on or the live TV does (_cmd: a builtin, own_action); and any of the build's chips of these
# screens hidden (POVILHideChip_<tab>_<n>).
CUSTOM_CHIPS = 6
CUSTOM_CHIP_AT = {'movies': 4, 'tv': 4}
CHIP_POINTS = ('start', 'mid', 'end')


def custom_chip_id(ti, n, point):
    return 9240 + (ti * CUSTOM_CHIPS + n - 1) * 3 + CHIP_POINTS.index(point)


def custom_chip_ids(ti):
    """Every control of the viewer's chips of a screen (each chip at each point it may stand)."""
    return [custom_chip_id(ti, n, point) for n in range(1, CUSTOM_CHIPS + 1) for point in CHIP_POINTS]


def chip_at(tab, n, point):
    """The condition that the viewer's chip n of a screen stands at `point` (None: it never can)."""
    key = 'Skin.String(POVILChip_%s_%d_at)' % (tab['id'], n)
    has_mid = tab['id'] in CUSTOM_CHIP_AT
    if point == 'mid' and not has_mid:
        return None
    conds = ['String.IsEqual(%s,%s)' % (key, point)]
    if point == ('mid' if has_mid else 'end'):
        conds.append('String.IsEmpty(%s)' % key)
    if point == 'end' and not has_mid:
        conds.append('String.IsEqual(%s,mid)' % key)
    return '[%s]' % ' | '.join(conds)


def own_set(key):
    """A chip or a bar button of the viewer's has something to do."""
    return '[!String.IsEmpty(Skin.String(%s_path)) | !String.IsEmpty(Skin.String(%s_cmd))]' % (key, key)


def own_action(key):
    """[(condition, action)]: the viewer's builtin (a favourite, an add-on, the live TV: key_cmd), else his folder
    (key_path) in the Videos window. ($INFO in an action is carried out as written -- QA Kodi; $ESCINFO quotes a
    folder, so a comma in it cannot split the command.)"""
    return [('!String.IsEmpty(Skin.String(%s_cmd))' % key, '$INFO[Skin.String(%s_cmd)]' % key),
            ('String.IsEmpty(Skin.String(%s_cmd))' % key, 'ActivateWindow(Videos,$ESCINFO[Skin.String(%s_path)],return)' % key)]


def chip_hidden(tab, ci):
    return 'Skin.HasSetting(POVILHideChip_%s_%d)' % (tab['id'], ci)


def chip_order(ti, tab):
    """[(condition, id)] of a screen's chips the way they stand, the rightmost first: the viewer's at the start,
    the build's to the services, his after the services, the build's others, his at the end."""
    out, editable = [], tab['id'] in CUSTOM_TABS
    ids = chip_ids(ti, tab)

    def own(point):
        if editable:
            for n in range(1, CUSTOM_CHIPS + 1):
                where = chip_at(tab, n, point)
                if where:
                    out.append(('%s + %s' % (own_set('POVILChip_%s_%d' % (tab['id'], n)), where), custom_chip_id(ti, n, point)))
    own('start')
    at = CUSTOM_CHIP_AT.get(tab['id'], len(tab['chips']))
    for ci, chip in enumerate(tab['chips']):
        if ci == at:
            own('mid')
        chip = tuple(chip) + (None, None)
        conds = [c for c in (chip[2], '!' + chip_hidden(tab, ci) if editable else None) if c]
        out.append((' + '.join(conds), ids[ci]))
    if at >= len(tab['chips']):
        own('mid')
    own('end')
    return out


def first_chip(ti, tab):
    """The action that gives the focus to a screen's first chip on the screen (the rightmost shown)."""
    return 'SetFocus($VAR[POVIL_FirstChip_%s])' % tab['id']


RTL_ADDONS = ('plugin.video.pov', 'plugin.video.umbrella', 'plugin.video.idanplus')   # patches_config.py's povil_rtl hooks


def is_custom(path):
    return path.startswith('custom:')


# The viewer's order of a screen's rows ("התאמת מסך הבית": the Wizard's home_rows.py, else the skin's own dialog, window
# 1163 -- gen_standalone.py). A viewer, via the owner, Nov 2026: "let me change the order -- I can add a row now, but I
# cannot put it where I want", "in the original Onyx it exists". On these screens every row is a SLOT: slot k shows
# the row the viewer put there -- Skin.String(POVILSlot_<tab>_<k>) holds that row's place in the screen's list (TABS),
# once Skin.HasSetting(POVILOrdered_<tab>) -- else the build's own row k, as always. A slot with no row is empty and
# hidden; the dialogs keep the order compact, so no gap opens. Every slot is as tall as the screen's tallest row (a
# row of wide pictures may stand where a row of posters stood), and asks no row again when a playback starts or stops
# (sortby size: POV refreshes the home's rows itself after a film -- UpdateLibrary -- and a trailer is no reason).
SLOT_TABS = CUSTOM_TABS


def slot_tab(tab):
    return tab['id'] in SLOT_TABS


def shows(ti, k, i):
    """The condition that slot k of a screen in SLOT_TABS shows row i: a named expression (slot_expressions), so the
    long condition is written once and not at every control that asks."""
    return '$EXP[POVIL_Shows_%d_%d]' % (row_id(ti, k), i)


def shows_raw(ti, k, i):
    tid = TABS[ti]['id']
    ordered = 'Skin.HasSetting(POVILOrdered_%s)' % tid
    chosen = 'String.IsEqual(Skin.String(POVILSlot_%s_%d),%d)' % (tid, k, i)
    return ('[!%s | %s]' % (ordered, chosen)) if i == k else ('[%s + %s]' % (ordered, chosen))


def candidates(ti, k):
    """[(row, condition)]: the rows slot k may show and when ('' = always: a screen whose order is the build's)."""
    if not slot_tab(TABS[ti]):
        return [(k, '')]
    return [(i, shows(ti, k, i)) for i in range(len(TABS[ti]['rows']))]


def slot_kinds(ti, k):
    """{kind: condition} of the rows slot k may show ('' when only one kind can be there)."""
    groups = {}
    for i, cond in candidates(ti, k):
        groups.setdefault(TABS[ti]['rows'][i][2], []).append(cond)
    if len(groups) == 1:
        return {kind: '' for kind in groups}
    return {kind: '$EXP[POVIL_SlotKind_%d_%s]' % (row_id(ti, k), kind) for kind in groups}


# A row of the viewer's own from Kodi's library (a videodb:// address -- the library, its recently added, a folder
# of it): sorted by the skin as the viewer chose (POVILRow_<tab>_<n>_sort / _order; Kodi 21 applies an address's
# filter, not its order -- QA Kodi, every order came out by name), newest added first unless chosen otherwise, and
# started on the right like the add-ons' rows (rtl_waiting). Kodi reads a list's sortby / sortorder from a variable and
# follows it when it changes (QA Kodi 21: year, name, rating, date added, each in its order).
LIBRARY_SORTS = (('dateadded', 'descending', 'החדשים שנוספו קודם'), ('year', 'descending', 'לפי שנה, החדשים קודם'),
                 ('title', 'ascending', 'לפי שם, א-ת'), ('rating', 'descending', 'לפי דירוג, הגבוה קודם'),
                 ('random', 'descending', 'בסדר אקראי'))


def library_row(ti, k, named=True):
    """The condition that slot k shows a row of the viewer's own from Kodi's library ('' when it never can); named:
    the expression POVIL_Library_<id> (not in Timers.xml: Kodi reads it without the skin's expressions)."""
    tab = TABS[ti]
    if not slot_tab(tab):
        return ''
    parts = []
    for i, _when in candidates(ti, k):
        path = tab['rows'][i][1]
        if is_custom(path):
            parts.append('[%s + String.StartsWith(Skin.String(POVILRow_%s_path),videodb://)]' % (shows_raw(ti, k, i), path[7:]))
    if not parts:
        return ''
    return '$EXP[POVIL_Library_%d]' % row_id(ti, k) if named else ' | '.join(parts)


def slot_sorts(x):
    """POVIL_SortBy_<id> / POVIL_SortOrder_<id>: a slot's order -- by size (none: a stable order that a playback does
    not make Kodi ask again) unless it shows a library row of the viewer's own; then the viewer's order, reversed
    because the row starts at its far end, on the right."""
    for ti, tab in enumerate(TABS):
        if not slot_tab(tab):
            continue
        for k in range(len(tab['rows'])):
            rid = row_id(ti, k)
            customs = [(when, tab['rows'][i][1][7:]) for i, when in candidates(ti, k) if is_custom(tab['rows'][i][1])]
            x(1, '<variable name="POVIL_SortBy_%d">' % rid)
            for when, key in customs:
                lib = '%s + String.StartsWith(Skin.String(POVILRow_%s_path),videodb://)' % (when, key)
                x(2, '<value condition="%s + !String.IsEmpty(Skin.String(POVILRow_%s_sort))">$INFO[Skin.String(POVILRow_%s_sort)]</value>'
                  % (lib, key, key))
                x(2, '<value condition="%s">dateadded</value>' % lib)
            x(2, '<value>size</value>')
            x(1, '</variable>')
            x(1, '<variable name="POVIL_SortOrder_%d">' % rid)
            for when, key in customs:
                lib = '%s + String.StartsWith(Skin.String(POVILRow_%s_path),videodb://)' % (when, key)
                x(2, '<value condition="%s + String.IsEqual(Skin.String(POVILRow_%s_order),ascending)">descending</value>' % (lib, key))
            x(2, '<value>ascending</value>')
            x(1, '</variable>')


def slot_expressions(x):
    """The named conditions of the slots (Includes_POVIL_Home.xml): which row a slot shows, and which kind of row."""
    for ti, tab in enumerate(TABS):
        if not slot_tab(tab):
            continue
        for k in range(len(tab['rows'])):
            rid = row_id(ti, k)
            groups = {}
            for i in range(len(tab['rows'])):
                x(1, '<expression name="POVIL_Shows_%d_%d">%s</expression>' % (rid, i, shows_raw(ti, k, i)))
                groups.setdefault(tab['rows'][i][2], []).append(shows_raw(ti, k, i))
            if len(groups) > 1:
                for kind, conds in groups.items():
                    x(1, '<expression name="POVIL_SlotKind_%d_%s">%s</expression>' % (rid, kind, ' | '.join(conds)))
            if library_row(ti, k):
                x(1, '<expression name="POVIL_Library_%d">%s</expression>' % (rid, library_row(ti, k, named=False)))


def slot_block(tab):
    """A row's height on a screen in SLOT_TABS: its tallest row's."""
    return max(GEOM[row[2]]['block'] for row in tab['rows'])


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


def is_hub(path):
    return path.startswith('hub:')


def follows_no_playback(path):
    """A POV row whose titles no playback changes: not the viewer's own (LISTS_TOKEN), not what is in
    progress or next, not a history."""
    if is_hub(path):
        return True
    if not path.startswith(POV) or LISTS_TOKEN in path:
        return False
    return not any(word in path for word in ('in_progress', 'next_episode', 'favorites_', 'watched_', 'history',
                                              'mdblist_my', 'trakt_my', 'tmdb_my'))


def is_rtl(path):
    # (a viewer's own row: right to left when it is an add-on's list -- its address then carries povil_rtl, see
    # POVIL_Path_<id>; a folder of files is not reversed, and the row's guard leaves it as it is)
    return path.startswith('plugin://') or path.startswith('static:') or is_hub(path) or path.startswith('custom:')


def rtl_path(path):
    if not path.startswith('plugin://'):
        return path
    return path + ('&' if '?' in path else '?') + 'povil_rtl=1'


RESORT = 'Window(home).Property(povil.rtl.reset)'     # a library row's order changed: it starts on the right again


def rtl_waiting(cid, home=True, library=''):
    """library: the condition that the row is a library row of the viewer's own (library_row): sorted reversed by the
    skin, so it too starts at its far end -- an add-on's list says so by the mark on its items."""
    c = 'Container(%d)' % cid if cid else 'Container'
    prop = 'Window(home).Property(povil.rtl.%s)' % (cid or 'view')
    # the container's label FIRST: as the second argument Kodi reads Container(id).ListItemAbsolute(0).Label as plain
    # text, the guard never matched, and a row's far end threw the user back to its start
    changed = '!String.IsEqual(%(c)s.ListItemAbsolute(0).Label,%(p)s)'
    addon = ('Integer.IsEqual(%(c)s.CurrentItem,1) + String.IsEqual(%(c)s.ListItemAbsolute(0).Property(povil_rtl),1) + '
             + changed)
    if library:
        # A library row: whenever its first item is another (a new order, the library read again), wherever its
        # selection is -- Kodi reads the row before the skin's order applies and keeps the selected film through the
        # re-sort (QA Kodi: the focus ended on the 2nd and 3rd tile); the timer moves to the far end from any item
        # (Control.Move by minus the current item). And once more when a dialog re-ordered it (RESORT: the same
        # first item may stand first in the new order).
        addon = '[[%s] | [%s + [%s | !String.IsEmpty(%s)]]]' % (addon, library, changed, RESORT)
    return ('!%(c)s.IsUpdating + Integer.IsGreater(%(c)s.NumItems,1) + ' + addon) % {'c': c, 'p': prop}


def gen_timers():
    x = X()
    x(1, '<!-- POVIL RTL BEGIN: generated by tools/skin_onyx/gen_home.py -->')
    # Ratings from several sites for the title on screen: asked once per title, the moment it is shown
    # (the home's hero; the views, the info screen and the player have their own key labels)
    RR.timer(x, 'povil_ratings', RATINGS_KEY, RATINGS_SLOT, 'home',
             '[Window.IsActive(home) | Window.IsActive(videos) | Window.IsActive(movieinformation)]')
    RR.timer(x, 'povil_ratings_player', PLAYER_RATINGS_KEY, PLAYER_RATINGS_SLOT, 'player',
             '[Window.IsActive(fullscreenvideo) | Window.IsActive(videoosd)] + Player.HasVideo')
    # The trailer behind the hero: asked once the screen has rested on a title, and only while nothing
    # else plays; told to stop the moment the title changes, a dialog opens or the home is left.
    asked = 'Window(home).Property(povil.tr.ask)'
    x(1, '<timer>')
    x(2, '<name>povil_trailer</name>')
    # (none while an add-on is finding or opening a title's sources under Kodi's background progress:
    # the viewer pressed a title, a film is about to start -- review, Nov 2026)
    x(2, '<start reset="true">' + TRAILER_SCREEN + ' + %s + !System.HasActiveModalDialog + '
         '!Window.IsVisible(extendedprogressdialog) + %s + '
         '!String.IsEmpty(Control.GetLabel(%d)) + !String.IsEqual(Control.GetLabel(%d),%s) + '
         '[!Player.HasMedia | !String.IsEmpty(Window(home).Property(povil.tr.on))]</start>'
      % (TRAILERS_ON, TRAILER_REST, TRAILER_KEY, TRAILER_KEY, asked))
    # (the count to "the trailer to itself" starts again with every trailer: Kodi looks at its timers about
    # twice a second, and a timer whose stop was never seen kept the last trailer's count -- the home faded
    # at the new one's first picture. Seen in the QA Kodi: 2 titles of 6 on 0.5.19, 1 of 8 with the faster
    # trailer, which comes sooner after the last one)
    x(2, '<onstart>Skin.TimerStop(povil_trailer_shown)</onstart>')
    x(2, '<onstart>SetProperty(povil.tr.ask,$ESCINFO[Control.GetLabel(%d)],home)</onstart>' % TRAILER_KEY)
    x(2, '<onstart>NotifyAll(povil.trailer,ask)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # ... and the title the screen is on, named to the Wizard the moment it is there (povil.tr.peek): the
    # trailer is read from YouTube while the screen rests, so it is ready when it is asked (the Wizard reads
    # only a title the screen stayed on for a moment: not every poster passed on the way)
    peeked = 'Window(home).Property(povil.tr.peek)'
    x(1, '<timer>')
    x(2, '<name>povil_trailer_peek</name>')
    x(2, '<start reset="true">' + TRAILER_SCREEN + ' + %s + !System.HasActiveModalDialog + '
         '!Window.IsVisible(extendedprogressdialog) + '
         '!String.IsEmpty(Control.GetLabel(%d)) + !String.IsEqual(Control.GetLabel(%d),%s)</start>'
      % (TRAILERS_ON, TRAILER_KEY, TRAILER_KEY, peeked))
    x(2, '<onstart>SetProperty(povil.tr.peek,$ESCINFO[Control.GetLabel(%d)],home)</onstart>' % TRAILER_KEY)
    x(2, '<onstart>NotifyAll(povil.trailer,peek)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # A film or an episode played (not a trailer: the Wizard sets povil.tr.on before it plays one) ...
    x(1, '<timer>')
    x(2, '<name>povil_play_seen</name>')
    x(2, '<start reset="true">Player.HasVideo + String.IsEmpty(Window(home).Property(povil.tr.on)) + '
         'String.IsEmpty(Window(home).Property(povil.play.on))</start>')
    x(2, '<onstart>SetProperty(povil.play.on,1,home)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # ... and ended: 3 s later (POV has saved the place or the watched mark), the time of it, PLAY_TOKEN
    x(1, '<timer>')
    x(2, '<name>povil_play_done</name>')
    x(2, '<start reset="true">!Player.HasMedia + !String.IsEmpty(Window(home).Property(povil.play.on))</start>')
    x(2, '<stop>Player.HasMedia | Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_play_done),3)</stop>')
    x(2, '<onstop condition="!Player.HasMedia">ClearProperty(povil.play.on,home)</onstop>')
    x(2, '<onstop condition="!Player.HasMedia">SetProperty(povil.play.t,$INFO[System.Time(hh:mm:ss)],home)</onstop>')
    x(1, '</timer>')
    # how long the trailer has been opening (Kodi's busy dialog is hidden for the first seconds of it only,
    # gen_dialogs.py)
    x(1, '<timer>')
    x(2, '<name>povil_trailer_opening</name>')
    x(2, '<start reset="true">!String.IsEmpty(Window(home).Property(povil.tr.opening))</start>')
    x(2, '<stop>String.IsEmpty(Window(home).Property(povil.tr.opening))</stop>')
    x(1, '</timer>')
    # how long the trailer has been on the screen (TRAILER_ALONE counts from it)
    x(1, '<timer>')
    x(2, '<name>povil_trailer_shown</name>')
    x(2, '<start reset="true">%s + %s</start>' % (TRAILER_SCREEN, TRAILER_SHOWN))
    x(2, '<stop>!%s | ![%s]</stop>' % (TRAILER_SCREEN, TRAILER_SHOWN))
    x(1, '</timer>')
    # The trailer has the screen to itself, and when the home comes back over it: the Wizard shows the trailer's
    # Hebrew subtitles only meanwhile (trailer_subs.py; Onyx 1.0.28) -- Kodi draws subtitles over the home's video
    # window too, under the rows (QA Kodi)
    x(1, '<timer>')
    x(2, '<name>povil_trailer_alone</name>')
    x(2, '<start reset="true">%s + %s</start>' % (TRAILER_SCREEN, TRAILER_ALONE))
    x(2, '<onstart>NotifyAll(povil.trailer,alone)</onstart>')
    x(2, '<stop>!%s | ![%s]</stop>' % (TRAILER_SCREEN, TRAILER_ALONE))
    x(2, '<onstop>NotifyAll(povil.trailer,shared)</onstop>')
    x(1, '</timer>')
    x(1, '<timer>')
    x(2, '<name>povil_trailer_stop</name>')
    # (Kodi's own busy dialog comes up for a moment while any playback opens -- the trailer's too: it is
    # not a dialog the viewer opened; seen in the QA Kodi stopping the very trailer it announced)
    dialog = '[System.HasActiveModalDialog + !Window.IsActive(busydialog) + !Window.IsActive(busydialognocancel)]'
    # ... and while it is up NOTHING of the home can be read: Control.GetLabel answers for the dialog on top,
    # so the title's label reads empty. That was "the title changed" -- the trailer was stopped at its first
    # picture and asked for again, over and over, on a device slow enough for the dialog to come up at every
    # start (the owner's phone, Nov 2026: five times in ten seconds, then a frozen screen; reproduced in the
    # QA Kodi by opening the busy dialog over a playing trailer). The title is compared only with no busy
    # dialog on the screen.
    changed = ('[!Window.IsActive(busydialog) + !Window.IsActive(busydialognocancel) + '
               '!String.IsEqual(Control.GetLabel(%d),%s)]' % (TRAILER_KEY, asked))
    x(2, '<start reset="true">!String.IsEmpty(%s) + [!%s | %s | '
         '%s | %s]</start>' % (asked, TRAILER_SCREEN, dialog, TRAILERS_OFF, changed))
    x(2, '<onstart>Skin.TimerStop(povil_trailer_shown)</onstart>')
    x(2, '<onstart>ClearProperty(povil.tr.ask,home)</onstart>')
    x(2, '<onstart>NotifyAll(povil.trailer,stop)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # A screen's chips, brought to their right end -- the first chip -- the first time the screen is shown (Kodi shows
    # a row longer than the screen from its left end until a chip of it has the focus: chips()). The focus goes to the
    # first chip and straight back in one go (nothing is drawn between), and povil.focus is put back as it was.
    # (not while a dialog is up, not while a service's page is being entered: povil_hub_enter gives the focus there)
    for ti, tab in enumerate(TABS):
        if not tab['chips'] or tab.get('hidden'):
            continue
        x(1, '<timer>')
        x(2, '<name>povil_chips_%s</name>' % tab['id'])
        x(2, '<start reset="true">Window.IsActive(home) + !System.HasActiveModalDialog + Control.IsVisible(9100) + '
             '!String.IsEmpty(System.CurrentControlId) + String.IsEmpty(Window(home).Property(povil.%s.enter)) + '
             'String.IsEqual(Window(home).Property(povil.tab),%s) + !String.IsEqual(Window(home).Property(povil.chips.at),%s)</start>'
          % (HUB, tab['id'], tab['id']))
        x(2, '<onstart>SetProperty(povil.chips.at,%s,home)</onstart>' % tab['id'])
        x(2, '<onstart>SetProperty(povil.chips.back,$INFO[System.CurrentControlId],home)</onstart>')
        x(2, '<onstart>SetProperty(povil.chips.focus,$INFO[Window(home).Property(povil.focus)],home)</onstart>')
        x(2, '<onstart>%s</onstart>' % first_chip(ti, tab))
        x(2, '<onstart>SetFocus($INFO[Window(home).Property(povil.chips.back)])</onstart>')
        x(2, '<onstart>SetProperty(povil.focus,$INFO[Window(home).Property(povil.chips.focus)],home)</onstart>')
        x(2, '<stop>true</stop>')
        x(1, '</timer>')
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
    # Kodi's live TV has its channels (IPTV Simple loads them after the start):
    # the live tab's own-channels row asks again (its p=)
    x(1, '<timer>')
    x(2, '<name>povil_pvr</name>')
    x(2, '<start reset="true">PVR.HasTVChannels + String.IsEmpty(Window(home).Property(povil.pvr))</start>')
    x(2, '<onstart>SetProperty(povil.pvr,1,home)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # The Wizard fetches what the hero lacks for the Israeli show on screen
    # (hero_details.py) once the screen is still; $ESCINFO: the path holds commas
    x(1, '<timer>')
    x(2, '<name>povil_details</name>')
    x(2, '<start reset="true">Window.IsActive(home) + !System.HasModalDialog + System.IdleTime(1) + !String.IsEmpty(Control.GetLabel(9805)) + '
         '!String.IsEqual(Control.GetLabel(9805),Window(home).Property(povil.details.key))</start>')
    x(2, '<onstart>SetProperty(povil.details.near,$ESCINFO[Control.GetLabel(9806)],home)</onstart>')
    x(2, '<onstart>SetProperty(povil.details.key,$ESCINFO[Control.GetLabel(9805)],home)</onstart>')
    x(2, '<onstart>RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=hero_details)</onstart>')
    x(2, '<stop>true</stop>')
    x(1, '</timer>')
    # Kan's list (every programme's picture) is read once a Kodi session, when the
    # Israeli tab opens -- before the user reaches Kan's row
    x(1, '<timer>')
    x(2, '<name>povil_details_warm</name>')
    x(2, '<start reset="true">Window.IsActive(home) + String.IsEqual(Window(home).Property(povil.tab),israeli) + String.IsEmpty(Window(home).Property(povil.details.warm))</start>')
    x(2, '<onstart>SetProperty(povil.details.warm,1,home)</onstart>')
    x(2, '<onstart>RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=hero_warm)</onstart>')
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
            # (written out: a timer's condition is read without the skin's named expressions -- $EXP there was
            # "Error parsing boolean expression" at every start and the slot rows never asked again, Onyx 1.0.26; 1.0.27)
            whens = [(shows_raw(ti, ri, i) if slot_tab(tab) else when)
                     for i, when in candidates(ti, ri) if retries(tab['rows'][i])]
            if not whens:
                continue
            # (a slot: only while it shows one of the rows that retry)
            showing = ('[%s] + ' % ' | '.join(whens)) if all(whens) else ''
            rid = row_id(ti, ri)
            prop = 'Window(home).Property(povil.retry.%d)' % rid
            empty = ('!Integer.IsGreater(Container(%d).NumItems,0) + !Container(%d).IsUpdating' % (rid, rid))
            x(1, '<timer>')
            x(2, '<name>povil_retry_%d</name>' % rid)
            x(2, '<start reset="true">%s%s + Window.IsActive(home) + !String.IsEmpty(Window(home).Property(%s)) + %s + !String.IsEqual(%s,2)</start>'
              % (showing, tab_cond(tab), row_gate(ti, ri), empty, prop))
            x(2, '<stop>Integer.IsGreaterOrEqual(Skin.TimerElapsed(povil_retry_%d),3) | Integer.IsGreater(Container(%d).NumItems,0) | Container(%d).IsUpdating</stop>'
              % (rid, rid, rid))
            # second retry first: the first one's action would satisfy it at once
            x(2, '<onstop condition="%s + String.IsEqual(%s,1)">SetProperty(povil.retry.%d,2,home)</onstop>' % (empty, prop, rid))
            x(2, '<onstop condition="%s + String.IsEmpty(%s)">SetProperty(povil.retry.%d,1,home)</onstop>' % (empty, prop, rid))
            x(1, '</timer>')
    for ti, tab in enumerate(TABS):
        if not tab.get('hidden'):
            continue
        ids = chip_ids(ti, tab)
        # A service's chip named the service and chose the page; its chips are on the screen a frame
        # later, and only then can one take the focus: the one of what is shown (all / films / series)
        x(1, '<timer>')
        x(2, '<name>povil_%s_enter</name>' % tab['id'])
        x(2, '<start reset="true">Window.IsActive(home) + String.IsEqual(Window(home).Property(povil.%s.enter),1) + Control.IsVisible(%d)</start>'
          % (tab['id'], ids[0]))
        x(2, '<onstart>ClearProperty(povil.%s.enter,home)</onstart>' % tab['id'])
        for n, kind in enumerate(HUB_TYPES):
            x(2, '<onstart condition="%s">SetFocus(%d)</onstart>' % (hub_type(kind), ids[n]))
        x(2, '<stop>true</stop>')
        x(1, '</timer>')
        # the mark never outlives the entering (while it is set the tab buttons do not choose their tabs)
        x(1, '<timer>')
        x(2, '<name>povil_%s_enter_guard</name>' % tab['id'])
        # ... whatever happens to the page meanwhile: two seconds at most
        x(2, '<start reset="true">String.IsEqual(Window(home).Property(povil.%s.enter),1)</start>' % tab['id'])
        x(2, '<stop>String.IsEmpty(Window(home).Property(povil.%s.enter)) | !Window.IsActive(home) | !%s | '
             'Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_%s_enter_guard),2)</stop>' % (tab['id'], tab_cond(tab), tab['id']))
        x(2, '<onstop>ClearProperty(povil.%s.enter,home)</onstop>' % tab['id'])
        x(1, '</timer>')
        # the rows beyond the third open once the focus is on one of the page's rows
        rows_focused = ' | '.join('Control.HasFocus(%d)' % row_id(ti, ri) for ri in range(len(tab['rows'])))
        x(1, '<timer>')
        x(2, '<name>povil_far_%s</name>' % tab['id'])
        x(2, '<start reset="true">Window.IsActive(home) + %s + [%s] + String.IsEmpty(Window(home).Property(povil.far.%s))</start>'
          % (tab_cond(tab), rows_focused, tab['id']))
        x(2, '<onstart>SetProperty(povil.far.%s,1,home)</onstart>' % tab['id'])
        x(2, '<stop>true</stop>')
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
            if not any(is_rtl(tab['rows'][i][1]) for i, _when in candidates(ti, ri)):
                continue
            rid = row_id(ti, ri)
            x(1, '<timer>')
            x(2, '<name>povil_rtl_%d</name>' % rid)
            x(2, '<start reset="true">Window.IsVisible(home) + %s + %s</start>'
              % (tab_cond(tab), rtl_waiting(rid, library=library_row(ti, ri, named=False))))
            x(2, '<onstart>SetProperty(povil.rtl.%d,$ESCINFO[Container(%d).ListItemAbsolute(0).Label],home)</onstart>' % (rid, rid))
            if library_row(ti, ri):
                # (to the far end from any item: back by the current item's number, the last wrapping round)
                x(2, '<onstart>Control.Move(%d,-$INFO[Container(%d).CurrentItem])</onstart>' % (rid, rid))
                x(2, '<onstart>ClearProperty(povil.rtl.reset,home)</onstart>')
            else:
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
    slot_expressions(x)
    slot_sorts(x)
    sources = []  # (condition, container id)
    # (condition, container, its kind): a slot that may show rows of several kinds is one source per kind
    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            for kind, kcond in slot_kinds(ti, ri).items():
                sources.append(('%s + %s' % (row_focus(ti, ri), kcond) if kcond else row_focus(ti, ri), row_id(ti, ri), shape(kind)))
    for ti, tab in enumerate(TABS):
        if tab['rows']:
            for kind, kcond in slot_kinds(ti, 0).items():
                sources.append(('[%s] + %s' % (tab_cond(tab), kcond) if kcond else tab_cond(tab), row_id(ti, 0), shape(kind)))
    # ... and one per container where its kind does not matter (the title, the logo, the plot): the variables stay
    # as short as before for every value but the backdrop's
    plain_sources = []
    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            plain_sources.append((row_focus(ti, ri), row_id(ti, ri)))
    for ti, tab in enumerate(TABS):
        if tab['rows']:
            plain_sources.append((tab_cond(tab), row_id(ti, 0)))

    def var(name, fmt, fallback=None, empty_check=None):
        x(1, '<variable name="%s">' % name)
        for cond, cid in plain_sources:
            check = (' + !String.IsEmpty(%s)' % (empty_check % cid)) if empty_check else ''
            x(2, '<value condition="%s%s">%s</value>' % (cond, check, e(fmt % {'c': cid})))
        if fallback:
            for cond, val in fallback:
                x(2, '<value condition="%s">%s</value>' % (cond, e(val)) if cond else '<value>%s</value>' % e(val))
        x(1, '</variable>')

    tab_titles = [(tab_cond(t), '$VAR[POVIL_TabLabel_%s]' % t['id'] if t['id'] in BAR_IDS else t['label']) for t in TABS]
    tab_blurbs = [(tab_cond(t), t['blurb']) for t in TABS]
    for _own in OWN_TAB_IDS:
        _cond = 'String.IsEqual(Window(home).Property(povil.tab),%s)' % _own
        tab_titles.append((_cond, '$VAR[POVIL_TabLabel_%s]' % _own))
        tab_blurbs.append((_cond, 'כפתור משלכם בסרגל: לחצו OK כדי לפתוח.'))
    more_page = '![String.Contains(Container(%d).ListItem.FolderPath,new_page=) | String.Contains(Container(%d).ListItem.FolderPath,Page&amp;url=)]'

    # What the Wizard fetched for the Israeli show on screen (hero_details.py): Keshet
    # 12's summary, picture and logo, Kan 11's picture -- Idan Plus lists them with the
    # name as the plot and the poster as the backdrop. An item fetched before carries
    # them itself (povil_rtl, from the Wizard's index): its fanart is no longer its
    # poster, and nothing is asked. Otherwise label 9805 names the item
    # (POVIL_HeroDetailsKey), label 9806 its two neighbours on each side
    # (POVIL_HeroDetailsNear), timer povil_details asks; the item's answer comes in
    # povil.details.*, the neighbours' in povil.details.1. ... .4., so a step to one
    # of them shows its details at once.
    detail_rows = {row_id(ti, ri) for ti, tab in enumerate(TABS) for ri, row in enumerate(tab['rows'])
                   if row[1] in (IDAN_KESHET_VOD, IDAN_KAN_VOD)}
    slots = ('', '1.', '2.', '3.', '4.')

    def matched(slot):
        # (never an empty 9805: an item that carries its details names none)
        return ('!String.IsEmpty(Control.GetLabel(9805)) + '
                'String.IsEqual(Control.GetLabel(9805),Window(home).Property(povil.details.%sfor))' % slot)

    def detail(field):
        for slot in slots:
            x(2, '<value condition="%s + !String.IsEmpty(Window(home).Property(povil.details.%s%s))">$INFO[Window(home).Property(povil.details.%s%s)]</value>'
              % (matched(slot), slot, field, slot, field))

    bare = 'String.IsEqual(Container(%d).ListItem.Art(fanart),Container(%d).ListItem.Art(thumb))'
    x(1, '<variable name="POVIL_HeroDetailsKey">')
    for cond, cid in plain_sources:
        if cid in detail_rows:
            x(2, '<value condition="%s + %s + %s">$INFO[Container(%d).ListItem.FolderPath]</value>' % (cond, more_page % (cid, cid), bare % (cid, cid), cid))
        x(2, '<value condition="%s"></value>' % cond)
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroDetailsNear">')
    for cond, cid in plain_sources:
        if cid in detail_rows:
            x(2, '<value condition="%s">%s</value>' % (cond, ' '.join('$INFO[Container(%d).ListItem(%d).FolderPath]' % (cid, o) for o in (-2, -1, 1, 2))))
        x(2, '<value condition="%s"></value>' % cond)
    x(1, '</variable>')
    # Backdrop: fanart, else a landscape / thumb (Israeli VOD), else nothing (the ambient base shows).
    x(1, '<variable name="POVIL_HeroFanart">')
    detail('fanart')
    for cond, cid, _kind in sources:
        if _kind == 'square':
            continue  # channel logos and icons: the ambient wash, never a stretched logo
        # A poster row's thumb is its poster, and a "fanart" that is the thumb again
        # (Idan Plus: Keshet's 420x600 posters) would fill the screen ~250% enlarged:
        # the ambient backdrop then
        poster_row = _kind == 'poster'
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
        # a picture the Wizard fetched (hero_details) is a real backdrop: no wash then
        for slot in slots:
            x(2, '<value condition="%s + !String.IsEmpty(Window(home).Property(povil.details.%sfanart))"></value>' % (matched(slot), slot))
        for cond, cid, _kind in sources:
            if _kind != 'landscape':  # a landscape row always has its own backdrop
                more = more_page % (cid, cid)
                own = ''
                if _kind == 'poster':
                    own = (' + [String.IsEmpty(Container(%d).ListItem.Art(fanart)) | String.IsEqual(Container(%d).ListItem.Art(fanart),Container(%d).ListItem.Art(thumb))]'
                           ' + String.IsEmpty(Container(%d).ListItem.Art(landscape))' % (cid, cid, cid, cid))
                x(2, '<value condition="%s + %s%s">$INFO[Container(%d).ListItem.Art(%s)]</value>' % (cond, more, own, cid, art))
            # the row on screen decides, also when it wants no wash: Kodi would go on
            # to the tab's first row (the fallback below) and wash over Reshet's backdrop
            x(2, '<value condition="%s"></value>' % cond)
        x(1, '</variable>')
    # Only a logo that suits a Hebrew screen (POV's povil_logo art, Keshet's own Hebrew
    # title logo); else the title is written
    x(1, '<variable name="POVIL_HeroLogo">')
    detail('logo')
    for cond, cid in plain_sources:
        x(2, '<value condition="%s">$INFO[Container(%d).ListItem.Art(povil_logo)]</value>' % (cond, cid))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroTitle">')
    for cond, cid in plain_sources:
        x(2, '<value condition="%s + [String.Contains(Container(%d).ListItem.FolderPath,new_page=) | String.Contains(Container(%d).ListItem.FolderPath,Page&amp;url=)]">עוד תוצאות</value>' % (cond, cid, cid))
    for cond, cid in plain_sources:
        x(2, '<value condition="%s + String.IsEqual(Container(%d).ListItem.DBType,episode)">$INFO[Container(%d).ListItem.TVShowTitle]</value>' % (cond, cid, cid))
        x(2, '<value condition="%s + !String.IsEmpty(Container(%d).ListItem.Title)">$INFO[Container(%d).ListItem.Title]</value>' % (cond, cid, cid))
        x(2, '<value condition="%s">$INFO[Container(%d).ListItem.Label]</value>' % (cond, cid))
    for cond, val in tab_titles:
        x(2, '<value condition="%s">%s</value>' % (cond, e(val)))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroEpisode">')
    for cond, cid in plain_sources:
        x(2, '<value condition="%s + String.IsEqual(Container(%d).ListItem.DBType,episode)">$INFO[Container(%d).ListItem.Season,עונה , · ]$INFO[Container(%d).ListItem.Episode,פרק ]$INFO[Container(%d).ListItem.Title,  ·  ]</value>'
          % (cond, cid, cid, cid, cid))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroMeta">')
    for cond, cid in plain_sources:
        x(2, '<value condition="%s + !String.IsEmpty(Container(%d).ListItem.Year)">$INFO[Container(%d).ListItem.Year]$INFO[Container(%d).ListItem.Genre,  •  ]$INFO[Container(%d).ListItem.Duration(mins),  •  , דק\']$INFO[Container(%d).ListItem.MPAA,  •  ]</value>'
          % (cond, cid, cid, cid, cid, cid))
        x(2, '<value condition="%s">$INFO[Container(%d).ListItem.Genre]$INFO[Container(%d).ListItem.Duration(mins),  •  , דק\']</value>' % (cond, cid, cid))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroRating">')
    for cond, cid in plain_sources:
        x(2, '<value condition="%s + Integer.IsGreater(Container(%d).ListItem.Rating,0)">$INFO[Container(%d).ListItem.Rating]</value>' % (cond, cid, cid))
    x(1, '</variable>')
    # The ratings row (ratings_row.py): the POV title the hero shows, named for the Wizard
    x(1, '<variable name="POVIL_RatingsKey">')
    for cond, cid in plain_sources:
        item = 'Container(%d).ListItem' % cid
        x(2, '<value condition="%s + %s + %s">%s</value>' % (cond, more_page % (cid, cid), RR.has_key(item), RR.key(item)))
        # the row on screen decides, also when its item has no ratings to ask for
        x(2, '<value condition="%s"></value>' % cond)
    x(1, '</variable>')
    RR.tmdb_variable(x, 'POVIL_RatingsTmdb', RATINGS_KEY, RATINGS_SLOT, '$VAR[POVIL_HeroRating]')
    # The trailer POV names for the title in the hero (the YouTube add-on's address); nothing for any
    # other item, so nothing is asked for an Israeli show, a channel or a "more" tile
    x(1, '<variable name="POVIL_HeroTrailer">')
    for cond, cid in plain_sources:
        x(2, '<value condition="%s + %s + String.StartsWith(Container(%d).ListItem.Trailer,plugin://plugin.video.youtube/)">'
             '$INFO[Container(%d).ListItem.Trailer]</value>' % (cond, more_page % (cid, cid), cid, cid))
        x(2, '<value condition="%s"></value>' % cond)
    x(1, '</variable>')
    # a row of the viewer's own: the name given, else "השורה שלי"
    for _tab in CUSTOM_TABS:
        for _n in range(1, CUSTOM_SLOTS + 1):
            x(1, '<variable name="POVIL_RowName_%s_%d">' % (_tab, _n))
            x(2, '<value condition="!String.IsEmpty(Skin.String(POVILRow_%s_%d_name))">$INFO[Skin.String(POVILRow_%s_%d_name)]</value>'
              % (_tab, _n, _tab, _n))
            x(2, '<value>השורה שלי</value>')
            x(1, '</variable>')
    x(1, '<variable name="POVIL_WatchedColour">')
    for setting, _name, colour, _sid in WATCHED_COLOURS[1:]:
        x(2, '<value condition="Skin.HasSetting(%s)">%s</value>' % (setting, colour))
    x(2, '<value>%s</value>' % GOLD)
    x(1, '</variable>')
    x(1, '<variable name="POVIL_WatchedTile">')
    for setting, name, _colour, _sid in WATCHED_COLOURS[1:]:
        x(2, '<value condition="Skin.HasSetting(%s)">סימן נצפה: %s</value>' % (setting, name))
    x(2, '<value>סימן נצפה: זהב</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_PlayerTile">')
    for style, name in PLAYER_STYLES:
        x(2, '<value condition="String.IsEqual(Skin.String(POVILPlayer),%s)">נגן: %s</value>' % (style, name))
    x(2, '<value>נגן: Onyx</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_TrailersTile">')
    # (short: the tile showed the end of "טריילרים במסך הבית: פועל" only -- "פועל", seen in the QA Kodi)
    x(2, '<value condition="%s">טריילרים: כבוי</value>' % TRAILERS_OFF)
    x(2, '<value>טריילרים: פועל</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_HeroPlot">')
    detail('plot')
    for cond, cid in plain_sources:
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
    def path_values(ti, ri, row, gate, pre):
        """The values of slot ri's address for one of its rows; `pre`: the condition that the slot shows it."""
        if is_custom(row[1]):
            key = 'POVILRow_%s_path' % row[1][7:]
            opened = '!String.IsEmpty(Window(home).Property(%s)) + !String.IsEmpty(Skin.String(%s))' % (gate, key)
            plugin = '[%s]' % ' | '.join('String.StartsWith(Skin.String(%s),plugin://%s/)' % (key, a) for a in RTL_ADDONS)
            # a list of the add-ons the Wizard's povil_rtl patches is read right to left like the build's own rows;
            # any other add-on is handed its address untouched (an unknown parameter could break its routing)
            # (POV's: also the time the last film ended -- PLAY_TOKEN -- so a list of films in progress follows them)
            pov_row = 'String.StartsWith(Skin.String(%s),%s)' % (key, POV)
            x(2, '<value condition="' + pre + '%s + %s + String.Contains(Skin.String(%s),?)">$INFO[Skin.String(%s)]&amp;povil_rtl=1%s</value>'
              % (opened, pov_row, key, key, e(PLAY_TOKEN)))
            x(2, '<value condition="' + pre + '%s + %s">$INFO[Skin.String(%s)]?povil_rtl=1%s</value>' % (opened, pov_row, key, e(PLAY_TOKEN)))
            x(2, '<value condition="' + pre + '%s + %s + String.Contains(Skin.String(%s),?)">$INFO[Skin.String(%s)]&amp;povil_rtl=1</value>'
              % (opened, plugin, key, key))
            x(2, '<value condition="' + pre + '%s + %s">$INFO[Skin.String(%s)]?povil_rtl=1</value>' % (opened, plugin, key))
            x(2, '<value condition="' + pre + '%s">$INFO[Skin.String(%s)]</value>' % (opened, key))
            return
        if is_hub(row[1]):
            # one address per choice (all / films / series); the service is in the address itself
            opened = '!String.IsEmpty(Window(home).Property(%s))' % gate
            for kind in HUB_TYPES:
                path = rtl_path(HUB_ROWS[int(row[1][4:])][1][kind][1])
                x(2, '<value condition="' + pre + '%s + %s + !String.IsEmpty(Window(home).Property(povil.retry.%d))">%s</value>'
                  % (opened, hub_type(kind), row_id(ti, ri), e(path + '&povil_retry=$INFO[Window(home).Property(povil.retry.%d)]' % row_id(ti, ri))))
                x(2, '<value condition="' + pre + '%s + %s">%s</value>' % (opened, hub_type(kind), e(path)))
            return
        path = rtl_path(named(row[1], row[0]))
        if slot_tab(TABS[ti]) and path.startswith(POV) and not follows_no_playback(row[1]):
            path += PLAY_TOKEN
        if retries(row):
            # a row that came back empty asks again (povil_retry_<id>): a new
            # address makes Kodi fetch it anew; the plain one stays first in the
            # file for the Wizard's prebuild, which skips addresses with $INFO
            x(2, '<value condition="' + pre + '!String.IsEmpty(Window(home).Property(%s)) + !String.IsEmpty(Window(home).Property(povil.retry.%d))">%s</value>'
              % (gate, row_id(ti, ri), e(path + '&povil_retry=$INFO[Window(home).Property(povil.retry.%d)]' % row_id(ti, ri))))
        x(2, '<value condition="' + pre + '!String.IsEmpty(Window(home).Property(%s))">%s</value>'
          % (gate, e(path)))

    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            if row[1].startswith('static:'):
                continue
            x(1, '<variable name="POVIL_Path_%d">' % row_id(ti, ri))
            gate = row_gate(ti, ri)
            for i, when in candidates(ti, ri):
                path_values(ti, ri, tab['rows'][i], gate, (when + ' + ') if when else '')
            x(1, '</variable>')
    # a slot's title: its row's
    for ti, tab in enumerate(TABS):
        if not slot_tab(tab):
            continue
        for ri in range(len(tab['rows'])):
            x(1, '<variable name="POVIL_SlotTitle_%d">' % row_id(ti, ri))
            for i, when in candidates(ti, ri):
                x(2, '<value condition="%s">%s</value>' % (when, e(tab['rows'][i][0])))
            x(1, '</variable>')
    for ti, tab in enumerate(TABS):
        for ri, _ in enumerate(tab['rows']):
            rid = row_id(ti, ri)
            x(1, '<variable name="POVIL_RowTitleColor_%d">' % rid)
            x(2, '<value condition="%s">povil_white</value>' % row_focus(ti, ri))
            x(2, '<value>povil_dim</value>')
            x(1, '</variable>')
    for k, (_kind, lists) in enumerate(HUB_ROWS):
        x(1, '<variable name="POVIL_HubTitle_%d">' % k)
        for kind in HUB_TYPES:
            x(2, '<value condition="%s">%s</value>' % (hub_type(kind), e(lists[kind][0])))
        x(1, '</variable>')
    for ti, tab in enumerate(TABS):
        for cid, chip in zip(chip_ids(ti, tab), tab['chips']):
            if len(chip) > 3 and chip[3]:
                for name, on, off in (('Text', 'povil_gold', 'povil_white'), ('Fill', '4DD9B77E', '24FFFFFF')):
                    x(1, '<variable name="POVIL_Chip%s_%d">' % (name, cid))
                    x(2, '<value condition="%s">%s</value>' % (chip[3], on))
                    x(2, '<value>%s</value>' % off)
                    x(1, '</variable>')
    for tab in TABS:
        x(1, '<variable name="POVIL_TabColor_%s">' % tab['id'])
        x(2, '<value condition="%s">povil_white</value>' % tab_cond(tab))
        x(2, '<value>povil_faint</value>')
        x(1, '</variable>')
    item_layouts(x)
    for tab_id in BAR_IDS:
        tab_button_include(x, tab_id)
    bar_variables(x)
    x(0, '</includes>')
    return x.text()


# View item layouts (Videos window): the layout follows the list's content.
VIEW_COND = {
    'poster': 'Container.Content(movies) | Container.Content(tvshows) | Container.Content(seasons) | Container.Content(sets)',
    'landscape': 'Container.Content(episodes) | Container.Content(videos) | Container.Content(musicvideos)',
}
VIEW_COND['square'] = '![%s | %s]' % (VIEW_COND['poster'], VIEW_COND['landscape'])


# The rating on a picture's corner: its plate (gen_ratings.py badge) and when an item has one to show --
# a title with a rating above zero; never POV's "more" item or Kodi's ".."
BADGE_W, BADGE_H = 78, 34
ITEM_RATED = ('Integer.IsGreater(ListItem.Rating,0) + !ListItem.IsParentFolder + '
              '![String.Contains(ListItem.FolderPath,new_page=) | String.Contains(ListItem.FolderPath,Page&amp;url=)]')


def item_layouts(x):
    for kind in ('poster', 'landscape', 'square', 'ranked'):
        item_layout(x, 'POVIL_Item_%s' % kind, kind)
    item_layout(x, 'POVIL_ViewItem_poster', 'poster', VIEW_COND['poster'])
    item_layout(x, 'POVIL_ViewItem_landscape', 'landscape', VIEW_COND['landscape'])
    item_layout(x, 'POVIL_ViewItem_square', 'square', VIEW_COND['square'])
    # A show's own episodes: each tile names its episode, not the show again
    item_layout(x, 'POVIL_ViewItem_episodes', 'landscape', title='POVIL_ItemEpisodeTitle', subtitle='POVIL_ItemEpisodeNumber')
    # a slot of a screen in SLOT_TABS: the layout of the kind of row it shows now
    for kind in ('poster', 'landscape', 'square'):
        item_layout(x, 'POVIL_SlotItem_%s' % kind, kind, '$PARAM[when]', params=('when',))


def item_layout(x, name, kind, cond=None, title='POVIL_ItemTitle', subtitle='POVIL_ItemSubtitle', params=()):
    if True:
        g = GEOM[kind]
        ranked, kind = kind == 'ranked', shape(kind)
        w, h, step = g['w'], g['h'], g['step']
        top = 22
        x(1, '<include name="%s">' % name)
        x(2, '<param name="id" />')
        for param in params:
            x(2, '<param name="%s" />' % param)
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
            if ranked:
                # The title's place in the list (povil_rank, the Wizard's povil_rtl), to the right of its
                # poster -- read first, right to left -- and partly behind it: drawn before the poster.
                # Faint at rest, gold on the focused title; never beside POV's "more" tile.
                x(5, '<control type="label" description="rank">')
                x(6, '<left>%d</left><top>%d</top><width>%d</width><height>%d</height>' % (w - 62, top + h - 206, step - w + 46, 220))
                x(6, '<font>povil_rank</font><align>center</align><aligny>center</aligny>')
                x(6, '<textcolor>%s</textcolor><label>$INFO[ListItem.Property(povil_rank)]</label>' % (GOLD if focused else '4DF5F2EC'))
                x(6, '<visible>![String.Contains(ListItem.FolderPath,new_page=) | String.Contains(ListItem.FolderPath,Page&amp;url=)] + !ListItem.IsParentFolder</visible>')
                x(5, '</control>')
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
            # watched: top left since 1.0.15 -- the top right corner is the rating's
            x(5, '<control type="image">')
            x(6, '<left>10</left><top>%d</top><width>34</width><height>34</height>' % (top + 10))
            x(6, '<texture colordiffuse="$VAR[POVIL_WatchedColour]">povil/check.png</texture>')
            x(6, '<visible>Integer.IsGreater(ListItem.PlayCount,0)</visible>')
            x(5, '</control>')
            if kind != 'square':
                # The title's rating on the picture's top right corner (the owner, Nov 2026: "a general
                # rating on the poster itself, top right, as there once was -- something luxurious"):
                # the list's own figure, so it is there with the picture; the sites' full row is the hero's.
                x(5, '<control type="group" description="rating on the picture">')
                x(6, '<left>%d</left><top>%d</top><visible>%s</visible>' % (w - BADGE_W - 10, top + 10, ITEM_RATED))
                x(6, '<control type="image"><left>0</left><top>0</top><width>%d</width><height>%d</height>'
                     '<texture>povil/ratings/badge.png</texture></control>' % (BADGE_W, BADGE_H))
                x(6, '<control type="label"><left>33</left><top>0</top><width>%d</width><height>%d</height><font>povil_badge</font>'
                     '<textcolor>povil_white</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Rating]</label></control>'
                     % (BADGE_W - 33 - 9, BADGE_H))
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
    # (the first tab's button itself: the bar is a list since 1.0.18, and a list asked to take the focus
    # gives it to its first button -- the settings, at the left -- whatever its own default says)
    x(1, '<defaultcontrol>%d</defaultcontrol>' % bar_button(0, BAR[0]))
    # (the viewer's own bar: the films may stand elsewhere -- the first place's button, on Kodi's start only)
    x(1, '<onload condition="String.IsEmpty(Window(home).Property(povil.focus)) + Skin.HasSetting(POVILBarOrdered)">'
         'SetFocus($VAR[POVIL_BarFirst])</onload>')
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
    x(1, '<onload>ClearProperty(povil.chips.at,home)</onload>')
    x(1, '<onload>ClearProperty(povil.%s.enter,home)</onload>' % HUB)
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
                 'Skin.SetString(AutoCloseTimeVideoOSD,4)', 'Skin.SetBool(_ShowWatched)',
                 'Skin.SetBool(_ShowUnwatched)', 'Skin.SetBool(NoFocusBox)', 'Skin.SetBool(TintFrame)',
                 'Skin.SetBool(OnyxFirstRun)'):
        x(1, '<onload condition="!Skin.HasSetting(OnyxFirstRun)">%s</onload>' % line)
    # Start on the rightmost tab (Movies) once per session
    # A reloaded skin (or profile) refills the rows from their first item: let
    # each RTL row move to its right end again.
    for ti, tab in enumerate(TABS):
        for ri, row in enumerate(tab['rows']):
            if any(is_rtl(tab['rows'][i][1]) for i, _when in candidates(ti, ri)):
                x(1, '<onload>ClearProperty(povil.rtl.%d,home)</onload>' % row_id(ti, ri))
    # The views' guard: a season opened again from the home starts on its first item
    x(1, '<onload>ClearProperty(povil.rtl.view,home)</onload>')
    x(1, '<onload>ClearProperty(povil.rtl.view.prev,home)</onload>')
    x(1, '<controls>')
    backdrop(x, 2)
    # everything over the picture is one group: it fades away while a trailer has the screen to itself
    x(2, '<control type="group" description="over the picture">')
    x(3, TRAILER_FADE)
    top_bar(x, 3)
    hero(x, 3)
    chips(x, 3)
    rows(x, 3)
    x(2, '</control>')
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
    # The title's trailer, once the Wizard has started it (trailers.py): Kodi's preview picture, over the
    # backdrop and under every shade, so the hero's text stays as clear as on a still. Only while the
    # trailer that plays is the one of the title on screen.
    # (black under it: a trailer of another shape than the screen leaves no strip of the still showing)
    x(d, '<control type="image" description="under the trailer">')
    x(d + 1, '<left>0</left><top>0</top><width>1920</width><height>1080</height>')
    x(d + 1, '<texture colordiffuse="FF000000">povil/white.png</texture>')
    x(d + 1, '<visible>%s</visible>' % TRAILER_SHOWN)
    x(d + 1, '<animation effect="fade" start="0" end="100" time="400">Visible</animation>')
    x(d, '</control>')
    x(d, '<control type="videowindow" description="trailer">')
    x(d + 1, '<left>0</left><top>0</top><width>1920</width><height>1080</height>')
    # A click (a tap on a phone) on a video window is Kodi's "to full screen": the home left the screen, the
    # trailer was stopped for it, and the home came back from the start -- on the films tab (the owner, Nov
    # 2026: "every time I tap the middle of the trailer to get the screen back, it takes me to the films menu").
    # The window takes no clicks: a tap only brings the home back, where it was.
    x(d + 1, '<hitrect x="-10" y="-10" w="1" h="1"/>')
    x(d + 1, '<visible>%s</visible>' % TRAILER_SHOWN)
    x(d + 1, '<animation effect="fade" start="0" end="100" time="600">Visible</animation>')
    x(d + 1, '<animation effect="fade" start="100" end="0" time="250">Hidden</animation>')
    x(d, '</control>')
    trailer_lines(x, d)
    x(d, '<control type="label" id="%d"><left>-2000</left><top>0</top><width>10</width><height>10</height>'
         '<label>$VAR[POVIL_HeroTrailer]</label></control>' % TRAILER_KEY)
    # a shade only 8 pixels across fades out over its last half pixel at both ends
    # (120 screen pixels when stretched over the screen): each is drawn past the screen's edges
    for desc, l, t, w, h, tex in (('hero shade', 520, -160, 1400, 1400, 'povil/grad_right.png'),
                                  ('rows shade', -320, 330, 2560, 750, 'povil/grad_bottom.png'),
                                  ('top shade', -320, 0, 2560, 240, 'povil/grad_top.png'),
                                  ('vignette', 0, 0, 1920, 1080, 'povil/vignette.png')):
        x(d, '<control type="image" description="%s">' % desc)
        x(d + 1, '<left>%d</left><top>%d</top><width>%d</width><height>%d</height>' % (l, t, w, h))
        x(d + 1, '<texture>%s</texture>' % tex)
        x(d + 1, TRAILER_FADE)          # the trailer to itself: no shade over it
        x(d, '</control>')


def trailer_lines(x, d):
    """The trailer's Hebrew subtitles (TRAILER_LINE), only while the trailer has the screen to itself: a soft shade
    at the bottom, and the line over it -- white, a shadow, centred, two lines at most."""
    shown = '%s + !String.IsEmpty(%s)' % (TRAILER_ALONE, TRAILER_LINE)
    x(d, '<control type="image" description="trailer subtitles backdrop">')
    x(d + 1, '<left>-320</left><top>700</top><width>2560</width><height>420</height>')
    x(d + 1, '<texture colordiffuse="C0FFFFFF">povil/grad_bottom.png</texture>')
    x(d + 1, '<visible>%s + !String.IsEmpty(%s)</visible>' % (TRAILER_ALONE, TRAILER_HAS_LINES))
    x(d + 1, '<animation effect="fade" start="0" end="100" time="300">Visible</animation>')
    x(d + 1, '<animation effect="fade" start="100" end="0" time="200">Hidden</animation>')
    x(d, '</control>')
    x(d, '<control type="label" description="trailer subtitles">')
    x(d + 1, '<left>160</left><top>850</top><width>1600</width><height>180</height>')
    x(d + 1, '<font>povil_trailer_sub</font><textcolor>FFFFFFFF</textcolor><shadowcolor>FF000000</shadowcolor>')
    x(d + 1, '<align>center</align><aligny>bottom</aligny><wrapmultiline>true</wrapmultiline>')
    x(d + 1, '<label>$INFO[%s]</label>' % TRAILER_LINE)
    x(d + 1, '<visible>%s</visible>' % shown)
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
    # Clock and date (top left); they end before the power button
    x(d, '<control type="label" description="clock">')
    x(d + 1, '<left>%d</left><top>30</top><width>250</width><height>52</height>' % MARGIN)
    x(d + 1, '<font>povil_clock</font><textcolor>povil_white</textcolor><aligny>center</aligny>')
    x(d + 1, '<label>$INFO[System.Time]</label>')
    x(d, '</control>')
    x(d, '<control type="label" description="date">')
    x(d + 1, '<left>%d</left><top>80</top><width>250</width><height>30</height>' % MARGIN)
    x(d + 1, '<font>povil_small</font><textcolor>povil_faint</textcolor><aligny>center</aligny>')
    x(d + 1, '<label>$INFO[System.Date(DDDD)]$INFO[System.Date(d MMMM),  •  ]</label>')
    x(d, '</control>')
    # Power, one step left of the last tab (the owner: "a power button within reach"). It opens the power
    # menu, as the settings tab's tile does; the tabs keep their own focus memory.
    x(d, '<control type="button" id="%d" description="power">' % POWER_BUTTON)
    x(d + 1, '<left>350</left><top>32</top><width>60</width><height>60</height>')
    x(d + 1, '<texturenofocus colordiffuse="B3FFFFFF">povil/osd/power.png</texturenofocus><texturefocus>povil/osd/power_fo.png</texturefocus>')
    x(d + 1, '<label></label><onclick>ActivateWindow(ShutdownMenu)</onclick>')
    x(d + 1, '<onright>SetFocus($VAR[POVIL_BarLast])</onright><ondown>SetFocus($VAR[POVIL_BarLast])</ondown>'
             '<onleft>noop</onleft><onup>noop</onup>')
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
    # (1.0.18: a list of buttons, so a tab the viewer took off the bar leaves no gap and the remote steps over
    # it. Kodi steps between a list's OWN children only -- a button inside a cell of its own did not move, seen
    # in the QA Kodi -- so each tab is one button, and the line under the chosen tab is that button's texture
    # (gen_tabline.py). They stand in the BAR's order from the right.)
    x(d, '<control type="grouplist" id="9000" description="tabs">')
    x(d + 1, '<left>%d</left><top>34</top><width>%d</width><height>72</height>' % (1920 - MARGIN - BAR_W, BAR_W))
    x(d + 1, '<orientation>horizontal</orientation><align>right</align><itemgap>0</itemgap><scrolltime>0</scrolltime>')
    x(d + 1, '<defaultcontrol>%d</defaultcontrol>' % bar_button(0, BAR[0]))
    x(d + 1, '<onleft>%d</onleft><onright>noop</onright>' % POWER_BUTTON)
    # every place holds a button of every tab (POVIL_Tab_<id>, gen_includes), shown while it holds that tab -- the
    # last place first: XML order is left to right, place 0 the rightmost
    for p in reversed(range(BAR_PLACES)):
        for tab_id in BAR_IDS:
            vis = ' + '.join(c for c in (bar_shows(p, tab_id), bar_visible(tab_id)) if c)
            x(d + 1, '<include content="POVIL_Tab_%s"><param name="id" value="%d" /><param name="visible" value="%s" /></include>'
              % (tab_id, bar_button(p, tab_id), e(vis)))
    x(d, '</control>')


def tab_button_include(x, tab_id):
    """<include name="POVIL_Tab_<id>">: a tab's button, for any place on the bar ($PARAM[id], $PARAM[visible])."""
    x(1, '<include name="POVIL_Tab_%s">' % tab_id)
    x(2, '<param name="id" />')
    x(2, '<param name="visible" />')
    x(2, '<definition>')
    d = 2
    own = tab_id in OWN_TAB_IDS
    x(d + 1, '<control type="togglebutton" id="$PARAM[id]" description="tab %s">' % tab_id)
    x(d + 2, '<width>%d</width><height>64</height>' % tab_width(tab_id))
    x(d + 2, '<visible>$PARAM[visible]</visible>')
    # (a toggle button: its second pair of textures, shown while the tab is the chosen one, is the line)
    x(d + 2, '<texturefocus /><texturenofocus />')
    line = '<alttexture%%s colordiffuse="%s">povil/%s</alttexture%%s>' % (GOLD, tab_line(tab_id))
    x(d + 2, (line % ('focus', 'focus')) + (line % ('nofocus', 'nofocus')))
    chosen = 'String.IsEqual(Window(home).Property(povil.tab),%s)' % tab_id
    x(d + 2, '<usealttexture>%s</usealttexture>' % chosen)
    x(d + 2, '<font>povil_tab</font><align>center</align><aligny>center</aligny><textoffsetx>0</textoffsetx><textoffsety>-2</textoffsety>')
    x(d + 2, '<textcolor>$VAR[POVIL_TabColor_%s]</textcolor><focusedcolor>povil_white</focusedcolor>' % tab_id)
    x(d + 2, '<label>$VAR[POVIL_TabLabel_%s]</label>' % tab_id)
    # (not while a service's page is being entered: the chip that was pressed leaves the screen with
    # its tab, Kodi hands the focus to the window's default -- a tab's button -- and that must not
    # bring its tab back; the timer povil_hub_enter then gives the focus to the page's chips)
    entering = 'String.IsEmpty(Window(home).Property(povil.%s.enter))' % HUB
    x(d + 2, '<onfocus condition="%s">SetProperty(povil.tab,%s,home)</onfocus>' % (entering, tab_id))
    x(d + 2, '<onfocus condition="%s">SetProperty(povil.tab.%s,1,home)</onfocus>' % (entering, tab_id))
    x(d + 2, '<onfocus>SetProperty(povil.focus,$PARAM[id],home)</onfocus>')
    if own:
        for cond, action in own_action('POVILTabOwn_%s' % tab_id[3:]):
            x(d + 2, '<onclick condition="%s">%s</onclick>' % (cond, action))
        x(d + 2, '<ondown>noop</ondown>')
    else:
        ti = TAB_INDEX[tab_id]
        tab = TABS[ti]
        # a row whose retries ran out (a box that started before its network) asks
        # again when its tab is chosen again
        for ri, row in enumerate(tab['rows']):
            if any(retries(tab['rows'][i]) for i, _when in candidates(ti, ri)):
                rid = row_id(ti, ri)
                x(d + 2, '<onfocus condition="String.IsEqual(Window(home).Property(povil.retry.%d),2) + !Integer.IsGreater(Container(%d).NumItems,0)">'
                         'ClearProperty(povil.retry.%d,home)</onfocus>' % (rid, rid, rid))
        if tab.get('click_alt'):
            cond, action = tab['click_alt']
            x(d + 2, '<onclick condition="%s">%s</onclick>' % (e(cond), e(named(action, tab['label']))))
            x(d + 2, '<onclick condition="![%s]">%s</onclick>' % (e(cond), e(named(tab['click'], tab['label']))))
        else:
            x(d + 2, '<onclick>%s</onclick>' % e(named(tab['click'], tab['label'])))
        # (left and right are the list's: it steps to the next button on the bar, over one that is off it)
        if tab['chips']:
            x(d + 2, '<ondown>%s</ondown>' % first_chip(ti, tab))
        elif tab['rows']:
            x(d + 2, '<ondown>%d</ondown>' % row_id(ti, 0))
    x(d + 1, '</control>')
    x(2, '</definition>')
    x(1, '</include>')


def bar_variables(x):
    """Where the focus goes: a tab's button wherever it stands, the first and the last on the bar; a screen's first
    chip on the screen; a tab's name; the colour of an own button's name."""
    for tab_id in BAR_IDS:
        x(1, '<variable name="POVIL_TabButton_%s">' % tab_id)
        for p in range(BAR_PLACES):
            x(2, '<value condition="%s">%d</value>' % (bar_shows(p, tab_id), bar_button(p, tab_id)))
        x(2, '<value>9000</value>')
        x(1, '</variable>')
        x(1, '<variable name="POVIL_TabLabel_%s">' % tab_id)
        if tab_id in OWN_TAB_IDS:
            x(2, '<value>$INFO[Skin.String(POVILTabOwn_%s_name)]</value>' % tab_id[3:])
        else:
            x(2, '<value condition="!String.IsEmpty(Skin.String(POVILTabName_%s))">$INFO[Skin.String(POVILTabName_%s)]</value>'
              % (tab_id, tab_id))
            x(2, '<value>%s</value>' % e(TABS[TAB_INDEX[tab_id]]['label']))
        x(1, '</variable>')
    for name, places in (('POVIL_BarFirst', range(BAR_PLACES)), ('POVIL_BarLast', reversed(range(BAR_PLACES)))):
        x(1, '<variable name="%s">' % name)
        for p in places:
            for tab_id in BAR_IDS:
                vis = ' + '.join(c for c in (bar_shows(p, tab_id), bar_visible(tab_id)) if c)
                x(2, '<value condition="%s">%d</value>' % (e(vis), bar_button(p, tab_id)))
        x(2, '<value>%d</value>' % bar_button(0, BAR[0]))
        x(1, '</variable>')
    for ti, tab in enumerate(TABS):
        if not tab['chips'] or tab.get('hidden'):
            continue
        x(1, '<variable name="POVIL_FirstChip_%s">' % tab['id'])
        for cond, cid in chip_order(ti, tab):
            x(2, ('<value condition="%s">%d</value>' % (e(cond), cid)) if cond else '<value>%d</value>' % cid)
        x(2, '<value>%d</value>' % chip_ids(ti, tab)[0])
        x(1, '</variable>')
    for tab_id in OWN_TAB_IDS:
        x(1, '<variable name="POVIL_TabColor_%s">' % tab_id)
        x(2, '<value condition="String.IsEqual(Window(home).Property(povil.tab),%s)">povil_white</value>' % tab_id)
        x(2, '<value>povil_faint</value>')
        x(1, '</variable>')

# A soft shadow under the hero's text (Onyx 1.0.26): the shade behind it stops short of black at the screen's edge
# now (gen_textures.py), and the text stays readable over a bright backdrop
HERO_SHADOW = 'B0000000'


def hero(x, d):
    right = 1920 - MARGIN
    x(d, '<control type="group" description="hero">')
    x(d + 1, '<left>0</left><top>0</top>')
    # A POV title has a ratings row between its details and its plot: the title block starts 34
    # pixels higher to make the room. Anything else (an Israeli show, a channel, a tab's own
    # text) has no such row and sits exactly where it always did.
    x(d + 1, '<animation effect="slide" end="0,34" time="140" tween="cubic" easing="out" '
             'condition="String.IsEmpty(Control.GetLabel(%d))">Conditional</animation>' % RATINGS_KEY)
    # Clear logo, else the title
    x(d + 1, '<control type="image" description="clear logo">')
    x(d + 2, '<left>%d</left><top>104</top><width>620</width><height>176</height>' % (right - 620))
    x(d + 2, '<texture background="true">$VAR[POVIL_HeroLogo]</texture>')
    x(d + 2, '<aspectratio align="right" aligny="bottom">keep</aspectratio><fadetime>120</fadetime>')
    x(d + 1, '</control>')
    x(d + 1, '<control type="label" description="title">')
    x(d + 2, '<left>%d</left><top>150</top><width>1100</width><height>130</height>' % (right - 1100))
    x(d + 2, '<font>povil_hero</font><textcolor>povil_white</textcolor><shadowcolor>%s</shadowcolor>' % HERO_SHADOW + '<align>right</align><aligny>bottom</aligny>')
    x(d + 2, '<label>$VAR[POVIL_HeroTitle]</label>')
    x(d + 2, '<visible>String.IsEmpty(Control.GetLabel(9800))</visible>')
    x(d + 1, '</control>')
    # Hidden label: tells the title whether a logo exists
    x(d + 1, '<control type="label" id="9800"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_HeroLogo]</label></control>')
    # Hidden labels: the Israeli show the hero wants details for, and its neighbours (timer povil_details)
    x(d + 1, '<control type="label" id="9805"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_HeroDetailsKey]</label></control>')
    x(d + 1, '<control type="label" id="9806"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_HeroDetailsNear]</label></control>')
    RR.key_label(x, d + 1, RATINGS_KEY, '$VAR[POVIL_RatingsKey]')
    x(d + 1, '<control type="label" description="episode">')
    x(d + 2, '<left>%d</left><top>288</top><width>1100</width><height>34</height>' % (right - 1100))
    x(d + 2, '<font>povil_hero_meta_bold</font><textcolor>%s</textcolor><shadowcolor>%s</shadowcolor><align>right</align><aligny>center</aligny>' % (GOLD, HERO_SHADOW))
    x(d + 2, '<label>$VAR[POVIL_HeroEpisode]</label>')
    x(d + 1, '</control>')
    # Details: rating (gold star) then year, genre, length, rating age
    x(d + 1, '<control type="grouplist" description="details">')
    x(d + 2, '<left>%d</left><top>%s</top><width>1100</width><height>40</height>' % (right - 1100, 322))
    x(d + 2, '<orientation>horizontal</orientation><align>right</align><itemgap>16</itemgap><usecontrolcoords>true</usecontrolcoords>')
    x(d + 2, '<control type="label">')
    x(d + 3, '<width>auto</width><height>40</height><font>povil_hero_meta</font><textcolor>povil_dim</textcolor><shadowcolor>%s</shadowcolor><aligny>center</aligny>' % HERO_SHADOW)
    x(d + 3, '<label>$VAR[POVIL_HeroMeta]</label>')
    x(d + 2, '</control>')
    x(d + 2, '<control type="label">')
    x(d + 3, '<width>auto</width><height>40</height><font>povil_hero_meta_bold</font><textcolor>%s</textcolor><shadowcolor>%s</shadowcolor><aligny>center</aligny>' % (GOLD, HERO_SHADOW))
    x(d + 3, '<label>$VAR[POVIL_HeroRating]</label>')
    # the star and its number are for a title with no ratings row: there TMDb's mark says it
    x(d + 3, '<visible>String.IsEmpty(Control.GetLabel(%d))</visible>' % RATINGS_KEY)
    x(d + 2, '</control>')
    x(d + 2, '<control type="image">')
    x(d + 3, '<top>9</top><width>22</width><height>22</height>')
    x(d + 3, '<texture colordiffuse="%s">povil/star.png</texture>' % GOLD)
    x(d + 3, '<visible>!String.IsEmpty(Control.GetLabel(9801)) + String.IsEmpty(Control.GetLabel(%d))</visible>' % RATINGS_KEY)
    x(d + 2, '</control>')
    x(d + 1, '</control>')
    x(d + 1, '<control type="label" id="9801"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_HeroRating]</label></control>')
    RR.row(x, d + 1, right, 366, RATINGS_KEY, RATINGS_SLOT, 'POVIL_RatingsTmdb', font='povil_hero_meta_bold')
    x(d + 1, '<control type="textbox" description="plot">')
    x(d + 2, '<left>%d</left><top>408</top><width>860</width><height>114</height>' % (right - 860))
    # no ratings row: the plot follows the details as it always did (402 = 408 + 34 - 40)
    x(d + 2, '<animation effect="slide" end="0,-40" time="140" tween="cubic" easing="out" '
             'condition="String.IsEmpty(Control.GetLabel(%d))">Conditional</animation>' % RATINGS_KEY)
    x(d + 2, '<font>povil_plot</font><textcolor>povil_dim</textcolor><shadowcolor>%s</shadowcolor><align>right</align>' % HERO_SHADOW)
    # while the title's trailer plays the plot steps aside: moving pictures behind three lines of text
    # read as neither (the title, its details and its ratings stay)
    x(d + 2, '<animation effect="fade" start="100" end="0" time="400" condition="%s">Conditional</animation>' % TRAILER_SHOWN)
    x(d + 2, '<label>$VAR[POVIL_HeroPlot]</label>')
    x(d + 1, '</control>')
    x(d, '</control>')


def chips(x, d):
    for tab in TABS:
        assert not tab['chips'] or not (tab['chips'][0] + (None,))[2], 'a tab\'s first chip must always show: %s' % tab['id']
    # The screen's whole width, with MARGIN of nothing at either end (CHIP_EDGE): a row that fits stands exactly
    # where it always did, and a longer one is cut at the screen's edges, as the rows of posters are -- never in the
    # middle of the picture. The owner, Nov 2026 (a viewer's shortcuts made the films' row longer than the screen):
    # its first chip stood cut at the margin "even though the picture covers the whole TV". Kodi shows a grouplist
    # longer than itself from its LEFT end until one of its controls has the focus: the timers povil_chips_<tab>
    # (gen_timers) bring each screen's row to its right end -- its first chip -- the first time the screen is shown.
    x(d, '<control type="grouplist" id="9100" description="chips">')
    x(d + 1, '<left>0</left><top>538</top><width>1920</width><height>50</height>')
    x(d + 1, '<orientation>horizontal</orientation><align>right</align><itemgap>%d</itemgap>' % CHIP_GAP)
    x(d + 1, '<scrolltime tween="cubic" easing="out">240</scrolltime>')
    x(d + 1, '<onup>9000</onup>')
    chip_edge(x, d + 1)
    for ti, tab in enumerate(TABS):
        ids = chip_ids(ti, tab)
        down = row_id(ti, 0) if tab['rows'] else ''
        editable = tab['id'] in CUSTOM_TABS
        at = CUSTOM_CHIP_AT.get(tab['id'], len(tab['chips'])) if editable else None
        # XML order is left to right: last chip first, so the first chip is the rightmost (the viewer's chips at
        # the end -- the leftmost -- before them all, his at the start after them all)
        if editable:
            own_chips(x, d + 1, ti, tab, down, 'end')
            if at >= len(tab['chips']):
                own_chips(x, d + 1, ti, tab, down, 'mid')
        for ci in reversed(range(len(tab['chips']))):
            chip = tuple(tab['chips'][ci]) + (None, None)
            label = chip[0]
            # one action, or several in order (a service's chip names the service, then shows its page)
            clicks = [named(c, label) for c in (chip[1] if isinstance(chip[1], list) else [chip[1]])]
            vis = tab_cond(tab) + (' + ' + chip[2] if chip[2] else '') + (' + !' + chip_hidden(tab, ci) if editable else '')
            x(d + 1, '<control type="button" id="%d">' % ids[ci])
            x(d + 2, '<width>auto</width><height>48</height><textoffsetx>28</textoffsetx>')
            x(d + 2, '<font>povil_chip_home</font><align>center</align><aligny>center</aligny>')
            if chip[3]:
                # a choice that is on (films / series / all, the service shown): gold-tinted while it is
                x(d + 2, '<textcolor>$VAR[POVIL_ChipText_%d]</textcolor><focusedcolor>povil_ink</focusedcolor>' % ids[ci])
                x(d + 2, '<texturenofocus border="24" colordiffuse="$VAR[POVIL_ChipFill_%d]">povil/pill48.png</texturenofocus>' % ids[ci])
            else:
                x(d + 2, '<textcolor>povil_white</textcolor><focusedcolor>povil_ink</focusedcolor>')
                x(d + 2, '<texturenofocus border="24" colordiffuse="24FFFFFF">povil/pill48.png</texturenofocus>')
            x(d + 2, '<texturefocus border="24" colordiffuse="%s">povil/pill48.png</texturefocus>' % GOLD)
            x(d + 2, '<label>%s</label>' % e(label))
            for click in clicks:
                x(d + 2, '<onclick>%s</onclick>' % e(click))
            x(d + 2, '<onfocus>SetProperty(povil.tab,%s,home)</onfocus>' % tab['id'])
            x(d + 2, '<onfocus>SetProperty(povil.focus,%d,home)</onfocus>' % ids[ci])
            if tab.get('hidden'):
                # no button of its own in the tab bar: Up and Back leave the page for the tabs
                x(d + 2, '<onup>9000</onup><onback>9000</onback>')
            else:
                x(d + 2, '<onup>%s</onup>' % to_tab(tab['id']))
            if down:
                x(d + 2, '<ondown>%d</ondown>' % down)
            x(d + 2, '<visible>%s</visible>' % vis)
            x(d + 1, '</control>')
            if editable and ci == at:
                own_chips(x, d + 1, ti, tab, down, 'mid')
        if editable:
            own_chips(x, d + 1, ti, tab, down, 'start')
    chip_edge(x, d + 1)
    x(d, '</control>')


CHIP_GAP = 14


def chip_edge(x, d):
    """MARGIN of nothing at an end of the chips' row (with the gap after it)."""
    x(d, '<control type="label" description="edge"><width>%d</width><height>48</height><label></label></control>'
      % (MARGIN - CHIP_GAP))


def own_chips(x, d, ti, tab, down, point):
    """The viewer's own chips of a screen standing at `point` (CHIP_POINTS), right to left: shown while each has
    something to do and he put it there."""
    for n in reversed(range(1, CUSTOM_CHIPS + 1)):
        where = chip_at(tab, n, point)
        if not where:
            continue
        key = 'POVILChip_%s_%d' % (tab['id'], n)
        cid = custom_chip_id(ti, n, point)
        x(d, '<control type="button" id="%d">' % cid)
        x(d + 1, '<width>auto</width><height>48</height><textoffsetx>28</textoffsetx>')
        x(d + 1, '<font>povil_chip_home</font><align>center</align><aligny>center</aligny>')
        x(d + 1, '<textcolor>povil_white</textcolor><focusedcolor>povil_ink</focusedcolor>')
        x(d + 1, '<texturenofocus border="24" colordiffuse="24FFFFFF">povil/pill48.png</texturenofocus>')
        x(d + 1, '<texturefocus border="24" colordiffuse="%s">povil/pill48.png</texturefocus>' % GOLD)
        x(d + 1, '<label>$INFO[Skin.String(%s_name)]</label>' % key)
        for cond, action in own_action(key):
            x(d + 1, '<onclick condition="%s">%s</onclick>' % (cond, action))
        x(d + 1, '<onfocus>SetProperty(povil.tab,%s,home)</onfocus>' % tab['id'])
        x(d + 1, '<onfocus>SetProperty(povil.focus,%d,home)</onfocus>' % cid)
        x(d + 1, '<onup>%s</onup>' % to_tab(tab['id']))
        if down:
            x(d + 1, '<ondown>%d</ondown>' % down)
        x(d + 1, '<visible>%s + %s + %s</visible>' % (tab_cond(tab), own_set(key), where))
        x(d, '</control>')


def rtl_slots(g):
    """A right-to-left row: whole item slots only, the last one flush with the
    right margin. Kodi counts every slot inside a list as visible, so a slot cut
    by the screen edge would hold the row's far end ("עוד" included) half off
    screen. Returns the list's left and width (PAD wider on each side), and the
    left of the tile before the first one (the peek)."""
    gap = g.get('edge', g['step'] - g['w'])
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
    kind = shape(kind)
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
    return (path.startswith('plugin://') or is_hub(path)) and not optional


def row_gate(ti, ri):
    """The home property that opens a row's path (lazy loading, POVIL_Path_<id>)."""
    if TABS[ti].get('hidden') and ri >= HUB_NEAR_ROWS:
        return 'povil.far.%s' % TABS[ti]['id']       # set once the focus is on one of the page's rows
    return 'povil.tab.%s' % TABS[ti]['id'] if ri == 0 else 'povil.deep.%s' % TABS[ti]['id']


def skeleton(x, d, ti, ri, rid, kind, path, optional, members=None):
    """While a row has nothing to show yet -- not opened, loading, or waiting to
    start on the right -- dim tiles stand where its items will be (still: a
    pulse would redraw the screen every frame, on a phone's battery), so a slow
    list (a phone, a list never seen before) reads as loading, not as empty.
    A row that retries (gen_home retries) keeps them up until its retries are
    spent, and only then says it has nothing.
    A slot (SLOT_TABS): `members` are its rows of this kind, [(condition it shows the row, path, optional)] -- one
    group of tiles for all of them."""
    g = GEOM[kind]
    has = 'Integer.IsGreater(Container(%d).NumItems,0)' % rid
    opened = '!String.IsEmpty(Window(home).Property(%s))' % row_gate(ti, ri)
    closed = 'String.IsEmpty(Window(home).Property(%s))' % row_gate(ti, ri)
    spent = 'String.IsEqual(Window(home).Property(povil.retry.%d),2)' % rid
    members = members or [('', path, optional)]
    terms, retrying = [], []
    for when, m_path, m_optional in members:
        parts = ['Container(%d).IsUpdating' % rid]
        if is_rtl(m_path) and not m_path.startswith('static:'):
            parts.append('[%s]' % rtl_waiting(rid, library=library_row(ti, ri)))
        if retries((None, m_path, kind, m_optional)):
            parts.append('[!%s + !%s]' % (has, spent))       # until the retries are spent
            retrying.append(when)
        elif not m_optional:
            parts.append('[!%s + %s]' % (has, closed))
        terms.append(('%s + [%s]' % (when, ' | '.join(parts))) if when else ' | '.join(parts))
    if is_rtl(path):
        left = rtl_slots(g)[0] + PAD
        slots = [left + k * g['step'] for k in range(rtl_slots(g)[1] // g['step'])]
    else:
        slots = [MARGIN + k * g['step'] for k in range((1920 - 2 * MARGIN + g['step'] - g['w']) // g['step'])]
    x(d, '<control type="group" description="loading">')
    x(d + 1, '<visible>%s</visible>' % (terms[0] if len(terms) == 1 else ' | '.join('[%s]' % term for term in terms)))
    x(d + 1, '<animation effect="fade" time="200">Visible</animation><animation effect="fade" time="200">Hidden</animation>')
    for left in slots:
        x(d + 1, '<control type="image"><left>%d</left><top>62</top><width>%d</width><height>%d</height>'
                 '<texture border="30" colordiffuse="14FFFFFF">povil/rounded_fill.png</texture></control>' % (left, g['w'], g['h']))
    x(d, '</control>')
    if retrying:
        showing = ('[%s] + ' % ' | '.join(retrying)) if all(retrying) else ''
        x(d, '<control type="label" description="nothing here">')
        x(d + 1, '<left>%d</left><top>%d</top><width>%d</width><height>60</height>' % (MARGIN, 62 + g['h'] // 2 - 30, 1920 - 2 * MARGIN))
        x(d + 1, '<font>povil_meta</font><textcolor>povil_faint</textcolor><align>right</align><aligny>center</aligny>')
        x(d + 1, '<label>אין כרגע מה להציג כאן</label>')
        x(d + 1, '<visible>%s%s + %s + !Container(%d).IsUpdating + !%s</visible>' % (showing, opened, spent, rid, has))
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
            y += slot_block(tab) if slot_tab(tab) else GEOM[r[2]]['block']
        x(d, '<control type="group" description="rows %s">' % tab['id'])
        x(d + 1, '<left>0</left><top>%d</top>' % ROWS_Y)
        x(d + 1, '<visible>%s</visible>' % tab_cond(tab))
        # Slide the rows up so the focused row sits where the first one was
        for ri in range(1, len(ids)):
            x(d + 1, '<animation effect="slide" end="0,-%d" time="320" tween="cubic" easing="out" condition="%s">Conditional</animation>'
              % (offsets[ri], row_focus(ti, ri)))
        for ri, (title, path, kind, optional) in enumerate(tab['rows']):
            if slot_tab(tab):
                slot_row(x, d + 1, ti, ri, ids, offsets[ri])
                continue
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
            top_up = ((first_chip(ti, tab) if tab['id'] in CUSTOM_TABS else chip_ids(ti, tab)[0]) if tab['chips']
                      else to_tab(tab['id']))
            for cond, target in nav_chain(list(reversed(ids[:ri])), top_up):
                x(d + 3, '<onup condition="%s">%s</onup>' % (cond, target))
            # Kodi wraps a list with no action at its edge: the row's far end would
            # jump back to its start (and the start, on the right, to the far end)
            x(d + 3, '<onleft>noop</onleft><onright>noop</onright>')
            if tab.get('hidden'):
                x(d + 3, '<onback>9000</onback>')
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
                    for cond, action in (click if isinstance(click, list) else [('', click)]):
                        x(d + 5, ('<onclick condition="%s">%s</onclick>' % (cond, e(action))) if cond else
                              ('<onclick>%s</onclick>' % e(action)))
                    if vis_item:
                        x(d + 5, '<visible>%s</visible>' % vis_item)
                    x(d + 4, '</item>')
                x(d + 3, '</content>')
            else:
                # Kodi asks a list with no sort order again whenever any playback starts or stops (it may be
                # "recently played"). A row of titles that no playback changes -- popular, a genre, a
                # service's page -- is given an order that changes nothing: by size, which is 0 for every
                # item, and the sort is stable (a reversed row's "more" tile, a folder, is first already).
                # The viewer's own rows (in progress, the next episode, saved lists) keep following playback.
                quiet = ' sortby="size"' if follows_no_playback(path) else ''
                x(d + 3, '<content target="videos"%s>$VAR[POVIL_Path_%d]</content>' % (quiet, rid))
            x(d + 2, '</control>')
            if is_rtl(path):
                peek(x, d + 2, rid, kind, 40)
            x(d + 1, '</control>')
        x(d, '</control>')


def slot_row(x, d, ti, k, ids, top):
    """Slot k of a screen in SLOT_TABS: the row the viewer put there (shows), drawn for its kind."""
    tab = TABS[ti]
    rows_ = tab['rows']
    rid = ids[k]
    cands = candidates(ti, k)
    kinds = slot_kinds(ti, k)
    x(d, '<control type="group" description="slot %d">' % (k + 1))
    x(d + 1, '<left>0</left><top>%d</top>' % top)
    hide = ' | '.join(row_focus(ti, j) for j in range(k + 1, len(ids)))
    if hide:
        x(d + 1, '<animation effect="fade" start="100" end="0" time="220" condition="%s">Conditional</animation>' % hide)
    x(d + 1, '<control type="label">')
    x(d + 2, '<left>%d</left><top>0</top><width>%d</width><height>44</height>' % (MARGIN, 1920 - 2 * MARGIN))
    x(d + 2, '<font>povil_row</font><align>right</align><aligny>center</aligny>')
    x(d + 2, '<textcolor>$VAR[POVIL_RowTitleColor_%d]</textcolor><label>$VAR[POVIL_SlotTitle_%d]</label>' % (rid, rid))
    # (an optional row's title shows with its items only; a row that is always there shows it from the start)
    x(d + 2, '<visible>%s</visible>' % ' | '.join(['Integer.IsGreater(Container(%d).NumItems,0)' % rid] +
                                                    [when for i, when in cands if not rows_[i][3]]))
    x(d + 1, '</control>')
    # loading tiles: one group per kind of the rows it may show
    groups = {}
    for i, when in cands:
        _title, path, kind, optional = rows_[i]
        groups.setdefault(kind, []).append((when, path, optional))
    for kind, members in groups.items():
        skeleton(x, d + 1, ti, k, rid, kind, members[0][1], members[0][2], members=members)
    base = 'poster' if 'poster' in kinds else sorted(kinds)[0]
    g = GEOM[base]
    left, width, _peek = rtl_slots(g)
    x(d + 1, '<control type="list" id="%d">' % rid)
    x(d + 2, '<left>%d</left><top>40</top><width>%d</width><height>%d</height>'
      % (left, width, max(GEOM[kind]['list_h'] for kind in kinds)))
    x(d + 2, '<orientation>horizontal</orientation><preloaditems>2</preloaditems>')
    x(d + 2, '<scrolltime tween="cubic" easing="out">260</scrolltime>')
    top_up = ((first_chip(ti, tab) if tab['id'] in CUSTOM_TABS else chip_ids(ti, tab)[0]) if tab['chips']
              else to_tab(tab['id']))
    for cond, target in nav_chain(list(reversed(ids[:k])), top_up):
        x(d + 2, '<onup condition="%s">%s</onup>' % (cond, target))
    x(d + 2, '<onleft>noop</onleft><onright>noop</onright>')
    if tab.get('hidden'):
        x(d + 2, '<onback>9000</onback>')
    x(d + 2, '<onfocus>SetProperty(povil.tab,%s,home)</onfocus>' % tab['id'])
    x(d + 2, '<onfocus>SetProperty(povil.focus,%d,home)</onfocus>' % rid)
    for cond, target in nav_chain(ids[k + 1:]):
        x(d + 2, '<ondown condition="%s">%d</ondown>' % (cond, target))
    x(d + 2, '<animation effect="fade" start="100" end="0" time="0" condition="%s">Conditional</animation>'
      % rtl_waiting(rid, library=library_row(ti, k)))
    for kind, kcond in kinds.items():
        if kind != base:
            # a row of another kind in a poster row's place: its whole tiles end flush with the right margin
            # (as the views do, gen_views.py)
            gk = GEOM[kind]
            per_page = (width - gk['step']) // gk['step'] + 1
            shift = (1920 - MARGIN) - (left + PAD + (per_page - 1) * gk['step'] + gk['w'])
            if shift:
                x(d + 2, '<animation effect="slide" end="%d,0" time="0" condition="%s">Conditional</animation>' % (shift, kcond))
        short_rows(x, d + 2, 'Container(%d)' % rid, kind, kcond or None)
    for kind, kcond in kinds.items():
        if kcond:
            x(d + 2, '<include content="POVIL_SlotItem_%s"><param name="id" value="%d" /><param name="when" value="%s" /></include>'
              % (shape(kind) if kind != 'ranked' else 'poster', rid, kcond))
        else:
            x(d + 2, '<include content="POVIL_Item_%s"><param name="id" value="%d" /></include>' % (kind, rid))
    # (by size: no order that a playback makes Kodi ask the row again -- unless a library row of the viewer's own
    # is shown, sorted as the viewer chose: slot_sorts)
    x(d + 2, '<content target="videos" sortby="$VAR[POVIL_SortBy_%d]" sortorder="$VAR[POVIL_SortOrder_%d]">'
             '$VAR[POVIL_Path_%d]</content>' % (rid, rid, rid))
    x(d + 1, '</control>')
    for kind, kcond in kinds.items():
        if kcond:
            x(d + 1, '<control type="group"><visible>%s</visible>' % kcond)
            peek(x, d + 2, rid, kind, 40)
            x(d + 1, '</control>')
        else:
            peek(x, d + 1, rid, kind, 40)
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
