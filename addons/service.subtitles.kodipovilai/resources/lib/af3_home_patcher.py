# Seed Arctic Fuse 3 with POV-first home widgets.
#
# AF3's upstream defaults point at Kodi library smart-playlists
# (InProgressMovies.xsp, NewMovies.xsp, etc.). This build is a
# streaming/POV build, so those lists are empty on fresh installs and
# the user sees "No Results" everywhere. We write script.skinvariables'
# per-user node files instead of patching AF3 XML directly; that keeps
# the skin updatable while giving existing installs a proper POV home.

import json
import os
import time
from urllib.parse import quote

try:
    import ast
    import sqlite3
except Exception:
    ast = None
    sqlite3 = None

try:
    import xbmc
    import xbmcaddon
    import xbmcvfs
except ImportError:
    xbmc = None
    xbmcaddon = None
    xbmcvfs = None


AF3_SKIN_ID = 'skin.arctic.fuse.3'
PATCH_VERSION = '2026-06-01-pov-home-v21'
# Must track wizard.py's AF3_CE_SKIN_VERSION, which is the version actually
# shipped in the pack. It did not: the wizard went to 6.3.2.14 and this stayed
# at 6.3.2.9, so every AF3 user already ON the correct pack was told to
# "upgrade" on every single boot -- a progress dialog and five add-on
# re-registrations, forever, for nothing.
AF3_CE_VERSION = '6.3.2.14'
# AF3's bundled TMDbHelper 6.15.6 imports jurialmunkey.ftools, which only
# exists from script.module.jurialmunkey 0.2.35. Users who switched to AF3
# while an older jurialmunkey (e.g. 0.2.28) was on disk get a TMDbHelper that
# crash-loops its service on every startup -> AF3 widgets/ratings break. If we
# detect an older jurialmunkey we re-trigger the deps-pack install (which now
# has a version gate and overwrites the stale copy).
JURIALMUNKEY_MIN_VERSION = '0.2.35'

BASE_NODES = 'special://profile/addon_data/script.skinvariables/nodes/'
AF3_NODES = BASE_NODES + AF3_SKIN_ID + '/'
# Our merge "baseline" sidecars live in OUR addon_data, NOT in the
# skinvariables nodes folder, so skinvariables never sees/parses them.
POV_BASELINE_DIR = ('special://profile/addon_data/'
                    'service.subtitles.kodipovilai/widget_baselines/')
AF3_FONT_XML = 'special://home/addons/' + AF3_SKIN_ID + '/1080i/Font.xml'
AF3_FONT_DIR = 'special://home/addons/' + AF3_SKIN_ID + '/fonts/'
AF3_NOTO_FONT = AF3_FONT_DIR + 'NotoSans-Regular.ttf'
AF3_XML_DIR = 'special://home/addons/' + AF3_SKIN_ID + '/1080i/'
AF3_INFO_XML = AF3_XML_DIR + 'Includes_Info.xml'
AF3_HEBREW_PO = (
    'special://home/addons/' + AF3_SKIN_ID +
    '/language/resource.language.he_il/strings.po')
POV_NAVIGATOR_DB = 'special://profile/addon_data/plugin.video.pov/navigator.db'
POV_MEDIA_BASE = 'special://home/addons/plugin.video.pov/resources/skins/Default/media/'
BUNDLED_NOTO_FONT = os.path.join(
    os.path.dirname(__file__), 'media_assets', 'fonts', 'NotoSans-Regular.ttf')


FONT_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<fonts>

    <fontset id="Default" unicode="true">
        <include content="Font_Default">
            <param name="font_bold">NotoSans-Regular.ttf</param>
            <param name="font_regular">NotoSans-Regular.ttf</param>
            <param name="font_light">NotoSans-Regular.ttf</param>
            <param name="style_light">light</param>

            <param name="plot_linespacing_head">1.03</param>
            <param name="plot_linespacing_midi">1.45</param>
            <param name="plot_linespacing_main">1.13</param>
            <param name="plot_linespacing_mini">1.20</param>
            <param name="plot_linespacing_tiny">1.11</param>
        </include>
    </fontset>

    <fontset id="Default (Unicode)" unicode="true">
        <include content="Font_Default">
            <param name="font_bold">NotoSans-Regular.ttf</param>
            <param name="font_regular">NotoSans-Regular.ttf</param>
            <param name="font_light">NotoSans-Regular.ttf</param>
            <param name="style_light">light</param>

            <param name="plot_linespacing_head">1.03</param>
            <param name="plot_linespacing_midi">1.45</param>
            <param name="plot_linespacing_main">1.13</param>
            <param name="plot_linespacing_mini">1.20</param>
            <param name="plot_linespacing_tiny">1.11</param>
        </include>
    </fontset>
</fonts>
'''


HEBREW_STRINGS_PO = '''# Kodi Media Center language file
# Addon Name: Arctic Fuse 3
# Language: Hebrew

msgid ""
msgstr ""
"Project-Id-Version: Arctic Fuse 3 POV IL\\n"
"Language: he_IL\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"

msgctxt "#31077"
msgid "More Information"
msgstr "מידע נוסף"

msgctxt "#31600"
msgid "Ends at"
msgstr "מסתיים ב-"
'''


def _pov(action='', mode='', name='', icon='', extra=''):
    params = []
    if action:
        params.append(('action', action))
    if icon:
        params.append(('iconImage', icon))
    if mode:
        params.append(('mode', mode))
    if name:
        params.append(('name', name))
    if extra:
        for part in extra.split('&'):
            if part:
                key, _, value = part.partition('=')
                params.append((key, value))
    return 'plugin://plugin.video.pov/?' + '&'.join(
        '{0}={1}'.format(k, v) for k, v in params)


def _mdblist_connected():
    """True only when POV has an MDBList API key stored. The MDBList home
    widgets route through POV's mdblist_watchlist action, which errors without a
    key -- so we only surface them when MDBList is actually connected. Mirrors
    favourites_personal_tiles_patcher._mdblist_connected()."""
    try:
        if xbmcaddon is None:
            return False
        tok = xbmcaddon.Addon('plugin.video.pov').getSetting('mdblist.token') or ''
        return bool(tok.strip())
    except Exception:
        return False


def _shortcut_folder(name, icon='folder.png'):
    return (
        'plugin://plugin.video.pov/?external_list_item=True'
        '&iconImage={0}'
        '&mode=navigator.build_shortcut_folder_list'
        '&name={1}'
        '&shortcut_folder=True'
    ).format(quote(icon, safe=''), quote(name, safe=''))


# Streaming-network rows (Netflix/Disney+/…). FENtastic ships these as
# individual favourites.xml tiles that open a POV tmdb_tv_networks list
# filtered by network_id; AF3 had none, so we generate one POV widget per
# network. These are POV ListItems -> Hebrew + play through POV scrapers.
# (name, tmdb network_id, icon filename under Twilight/Shows/Networks/)
_NETWORKS = (
    ('Netflix',    '213',  'Shows_Netflix.png'),
    ('Disney+',    '2739', 'Shows_Disney.png'),
    ('Apple TV+',  '2552', 'Shows_Apple_TV.png'),
    ('HBO',        '49',   'Shows_HBO.png'),
    ('HBO Max',    '3186', 'Shows_HBO_Max.png'),
    ('FOX',        '19',   'Shows_FOX.png'),
    ('Amazon',     '1024', 'Shows_Amazon.png'),
    ('Hulu',       '453',  'Shows_Hulu.png'),
    ('The CW',     '71',   'Shows_The_CW.png'),
)

def _net_widget(name, net_id, icon_file):
    icon_path = ('special://home/media/build_icons/Twilight/Shows/Networks/'
                 + icon_file)
    # _pov() does NOT url-encode its args (the existing tiles pass a
    # pre-encoded iconImage and %20-escaped name), so encode here: the
    # icon contains '://' and '/', and names like "The CW"/"Disney+"
    # contain a space/'+' that would corrupt the query string raw.
    return {
        'label': name,
        'icon': icon_path,
        'path': _pov('tmdb_tv_networks', 'build_tvshow_list',
                     quote(name, safe=''), quote(icon_path, safe=''),
                     extra='network_id=' + net_id),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    }


STREAMING_NETWORK_WIDGETS = [
    _net_widget(name, net_id, icon_file)
    for (name, net_id, icon_file) in _NETWORKS
]


HOME_WIDGETS = [
    {
        'label': 'כלים וחיבורים',
        'icon': 'special://home/media/build_icons/POV/Connect_Services.png',
        'path': 'plugin://plugin.program.kodipovilwizard/?mode=install&action=af3_tools',
        'target': 'programs',
        'widget_style': 'Landscape',
        'widget_limit': '7',
    },
    {
        'label': 'סרטים חדשים',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_Popular.png',
        'path': _pov('tmdb_movies_latest_releases', 'build_movie_list', '32461', 'dvd.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        'label': 'סדרות פופולריות',
        'icon': 'special://home/media/build_icons/Twilight/Shows/Shows_Popular.png',
        'path': _pov('trakt_tv_trending', 'build_tvshow_list', '32458', 'trending.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        'label': 'פרקים להמשך צפייה',
        'icon': 'special://home/media/build_icons/Twilight/Shows/Episodes_In_Progress.png',
        'path': _pov('', 'build_next_episode', '32483', 'next_episodes.png'),
        'target': 'videos',
        'widget_style': 'Landscape',
        'widget_limit': '7',
    },
    {
        'label': 'סרטים להמשך צפייה',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_In_Progress.png',
        'path': _pov('in_progress_movies', 'build_movie_list', '32476', 'player.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        # POV-LOCAL favorites: reads watched.db -> favorites (the store
        # the in-app "add to favorites" context menu writes to). This is
        # what populates immediately when the user adds a movie, with no
        # dependency on the online TMDB.org account list.
        'label': 'הסרטים שלי',
        'icon': 'special://home/media/build_icons/Twilight/Movies/My_Movies_TMDB.png',
        'path': _pov('favorites_movies', 'build_movie_list', 'Movie%20Favorites',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        # TMDB.org account favorites (the online list, synced across
        # devices). Kept alongside the local one so the user has both.
        'label': 'הסרטים שלי (TMDB)',
        'icon': 'special://home/media/build_icons/Twilight/Movies/My_Movies_TMDB.png',
        'path': _pov('tmdb_my_movies', 'build_movie_list', 'Movie%20Favorites%20(TMDB)',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        # Trakt collection -- movies. Grouped with the other movie tiles:
        # right after 'הסרטים שלי (TMDB)' and above the shows.
        'label': 'הסרטים שלי (Trakt)',
        'icon': 'special://home/media/build_icons/Twilight/Movies/My_Movies.png',
        'path': _pov('trakt_my_movies', 'build_movie_list', 'Movies',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftrakt.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        # MDBList watchlist -- movies. Routes to POV's mdblist_watchlist, which
        # merges Watchlist + Collection and sorts newest-first (inherited here).
        # Gated on MDBList being connected (see ensure_patched's loop): the row
        # is filtered out of the canonical when no key is stored.
        'label': 'הסרטים שלי (MDBList)',
        'icon': 'special://home/media/build_icons/Twilight/Movies/My_Movies_MDBList.png',
        'path': _pov('mdblist_watchlist', 'build_movie_list', 'MDBList%20Watchlist',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2fmdblist.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        # POV-LOCAL show favorites (watched.db -> favorites).
        'label': 'הסדרות שלי',
        'icon': 'special://home/media/build_icons/Twilight/Shows/My_Shows_TMDB.png',
        'path': _pov('favorites_tvshows', 'build_tvshow_list', 'TV%20Show%20Favorites',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        # TMDB.org account show favorites (online list).
        'label': 'הסדרות שלי (TMDB)',
        'icon': 'special://home/media/build_icons/Twilight/Shows/My_Shows_TMDB.png',
        'path': _pov('tmdb_my_tvshows', 'build_tvshow_list', 'TV%20Show%20Favorites%20(TMDB)',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        # Trakt collection -- shows. Grouped after 'הסדרות שלי (TMDB)'.
        'label': 'הסדרות שלי (Trakt)',
        'icon': 'special://home/media/build_icons/Twilight/Shows/My_Shows.png',
        'path': _pov('trakt_my_tvshows', 'build_tvshow_list', 'TV%20Shows',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftrakt.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        # MDBList watchlist -- shows. Same routing/sort as the movie row above.
        'label': 'הסדרות שלי (MDBList)',
        'icon': 'special://home/media/build_icons/Twilight/Shows/My_Shows_MDBList.png',
        'path': _pov('mdblist_watchlist', 'build_tvshow_list', 'MDBList%20Watchlist',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2fmdblist.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '7',
    },
    {
        'label': 'סרטים לפי ז׳אנר',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_Genres.png',
        'path': _shortcut_folder('FENtastic - סרטים - זאנרים',
                                 'special://home/media/build_icons/Twilight/Movies/Movies_Genres.png'),
        'target': 'videos',
        'widget_style': 'Landscape',
        'widget_limit': '7',
    },
    {
        'label': 'סדרות לפי ז׳אנר',
        'icon': 'special://home/media/build_icons/Twilight/Shows/Shows_Genres.png',
        'path': _shortcut_folder('FENtastic - סדרות - זאנרים',
                                 'special://home/media/build_icons/Twilight/Shows/Shows_Genres.png'),
        'target': 'videos',
        'widget_style': 'Landscape',
        'widget_limit': '7',
    },
] + STREAMING_NETWORK_WIDGETS + [
    {
        # עידן פלוס -- a CONTENT widget must point at a browsable plugin
        # directory, not a RunAddon() command (that gave "No Results").
        # plugin://plugin.video.idanplus/ lists idanplus's own category
        # menu, so the row shows its categories and clicking browses in.
        'label': 'עידן פלוס',
        'icon': 'special://home/media/build_icons/Idan_Plus/idan_plus.png',
        'path': 'plugin://plugin.video.idanplus/',
        'target': 'videos',
        'widget_style': 'Landscape',
        'widget_limit': '7',
    },
]


HOME_SUBMENU = [
    {
        # The other three skins carry this as a favourites tile. AF3 does not
        # read favourites for its home at all -- which is the whole reason this
        # module exists -- so the same entry has to arrive here, or "on all
        # skins" quietly means three. _MERGE_FILES covers this list, so a user
        # who removes it keeps it removed, same as any other row.
        'label': '10 העדכונים האחרונים',
        'icon': 'special://home/media/build_icons/Wizard/wizard_pov_il.png',
        'path': ('RunPlugin("plugin://plugin.program.kodipovilwizard/'
                 '?mode=recentupdates")'),
        'target': '',
    },
    {
        'label': 'POV',
        'icon': 'special://home/media/build_icons/POV/Logo_POV_IL.png',
        'path': 'RunAddon("plugin.video.pov")',
        'target': '',
    },
    {
        'label': 'חיבור שירותים',
        'icon': 'special://home/media/build_icons/POV/Connect_Services.png',
        'path': 'RunPlugin("plugin://plugin.video.pov/?mode=myservices")',
        'target': '',
    },
    {
        'label': 'הגדרת התראות מנוי',
        'icon': 'special://home/media/build_icons/POV/Connect_Services.png',
        'path': 'RunScript(service.subtitles.kodipovilai,action=debrid_notice_settings)',
        'target': '',
    },
    # The two Umbrella-era entries. AF3 does not use Kodi's favourites for its
    # home, so the favourites tiles that carry these on the other three skins
    # never appear here -- these are AF3's copy of the same two buttons, which
    # is what keeps all four skins at the same place. Both are dropped from the
    # canonical unless Umbrella is actually installed (see _UMBRELLA_MENU_PATHS
    # and the filter in ensure_patched), so nobody gets a dead row.
    {
        'label': 'מנוע החיפוש - POV / Umbrella',
        'icon': ('special://home/addons/plugin.video.pov/resources/skins/'
                 'Default/media/search.png'),
        'path': 'RunScript(service.subtitles.kodipovilai,action=search_provider)',
        'target': '',
    },
    {
        'label': 'Umbrella',
        'icon': 'special://home/addons/plugin.video.umbrella/icon.png',
        'path': 'RunAddon("plugin.video.umbrella")',
        'target': '',
    },
    {
        'label': 'תרגום AI',
        'icon': 'special://home/addons/service.subtitles.kodipovilai/icon.png',
        'path': 'Addon.OpenSettings(service.subtitles.kodipovilai)',
        'target': '',
    },
    {
        'label': 'החלף סקין',
        'icon': 'special://home/media/build_icons/Wizard/switch_skin_pov_il.png',
        'path': 'RunPlugin("plugin://plugin.program.kodipovilwizard/?mode=install&action=build_switch_skin")',
        'target': '',
    },
]


POWER_MENU = [
    {
        'label': 'POV',
        'icon': 'special://home/media/build_icons/POV/Logo_POV_IL.png',
        'path': 'RunAddon("plugin.video.pov")',
        'target': '',
    },
    {
        'label': 'חיבור שירותים',
        'icon': 'special://home/media/build_icons/POV/Connect_Services.png',
        'path': 'RunPlugin("plugin://plugin.video.pov/?mode=myservices")',
        'target': '',
    },
    {
        'label': 'הגדרת התראות מנוי',
        'icon': 'special://home/media/build_icons/POV/Connect_Services.png',
        'path': 'RunScript(service.subtitles.kodipovilai,action=debrid_notice_settings)',
        'target': '',
    },
    # The two Umbrella-era entries. AF3 does not use Kodi's favourites for its
    # home, so the favourites tiles that carry these on the other three skins
    # never appear here -- these are AF3's copy of the same two buttons, which
    # is what keeps all four skins at the same place. Both are dropped from the
    # canonical unless Umbrella is actually installed (see _UMBRELLA_MENU_PATHS
    # and the filter in ensure_patched), so nobody gets a dead row.
    {
        'label': 'מנוע החיפוש - POV / Umbrella',
        'icon': ('special://home/addons/plugin.video.pov/resources/skins/'
                 'Default/media/search.png'),
        'path': 'RunScript(service.subtitles.kodipovilai,action=search_provider)',
        'target': '',
    },
    {
        'label': 'Umbrella',
        'icon': 'special://home/addons/plugin.video.umbrella/icon.png',
        'path': 'RunAddon("plugin.video.umbrella")',
        'target': '',
    },
    {
        'label': 'תרגום AI',
        'icon': 'special://home/addons/service.subtitles.kodipovilai/icon.png',
        'path': 'Addon.OpenSettings(service.subtitles.kodipovilai)',
        'target': '',
    },
    {
        'label': 'שליחת לוג',
        'icon': 'special://home/media/build_icons/Twilight/Send_Log/twilight_send_log.png',
        'path': 'ActivateWindow(10025,"plugin://plugin.video.pov/?mode=navigator.log_utils&name=Changelog%20%26%20Log%20Utils",return)',
        'target': '',
    },
    {
        'label': 'החלף סקין',
        'icon': 'special://home/media/build_icons/Wizard/switch_skin_pov_il.png',
        'path': 'RunPlugin("plugin://plugin.program.kodipovilwizard/?mode=install&action=build_switch_skin")',
        'target': '',
    },
    {
        'label': 'עדכון מהיר',
        'icon': 'special://home/media/build_icons/Wizard/fast_update_pov_il.png',
        'path': 'PlayMedia("plugin://plugin.program.kodipovilwizard/?mode=install&action=quick_update&name=Kodi+POV+IL+-+FENtastic&auto_quick_update=false")',
        'target': '',
    },
    {
        'label': 'הגדרות',
        'icon': 'special://skin/extras/icons/settings.png',
        'path': 'ActivateWindow(settings)',
        'target': '',
    },
    {
        'label': 'טעינת סקין מחדש',
        'icon': 'special://skin/extras/icons/refresh.png',
        'path': 'ReloadSkin()',
        'target': '',
    },
    {
        'label': 'יציאה',
        'icon': 'special://skin/extras/icons/power.png',
        'path': 'Quit()',
        'target': '',
    },
]


# Search rows -> POV. The `path` tokens (DefaultSearch-POVMovies/POVTv)
# are resolved by search_path.xml, into which af3_search_pov_patcher
# injects matching rules (POV search path + single-encoded query). This
# replaces AF3's default Movies/TVShows(library) + TMDb rows so typed
# search returns POV results in Hebrew that play through POV scrapers.
# Search rows -> POV. NOTE the explicit 'guid' on each item: AF3's
# script.skinvariables generator assigns a RANDOM guid to any node item
# that lacks one (node.py assign_guid -> f'guid-{random:08x}'), and it
# generates the selector buttons (container 601) and the result rows from
# SEPARATE template passes. Because we rewrite this node on every boot, the
# selector and the rows ended up with DIFFERENT random guids -- and each
# row's visibility is gated on
#   String.IsEqual(Container(601).ListItem.Property(guid), <row guid>)
# so the focused selector button's guid never matched the row's guid and
# the result tiles stayed permanently invisible (blank), while Discover --
# hardcoded with the literal guid 'discover' on both sides -- worked. We
# pin a STABLE explicit guid per item (assign_guid keeps item.get('guid')),
# so the selector button and its row always share the same guid and the
# rows render. The guids just need to be unique + stable; these are.
SEARCH_WIDGETS = [
    {
        'guid': 'pov-search-movies',
        'label': 'סרטים',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_Popular.png',
        'path': 'DefaultSearch-POVMovies',
        'target': 'videos',
        'widget_style': 'Poster',
    },
    {
        'guid': 'pov-search-tv',
        'label': 'סדרות',
        'icon': 'special://home/media/build_icons/Twilight/Shows/Shows_Popular.png',
        'path': 'DefaultSearch-POVTv',
        'target': 'videos',
        'widget_style': 'Poster',
    },
    {
        'guid': 'pov-search-people',
        'label': 'שחקן / במאי',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_Popular.png',
        'path': 'DefaultSearch-POVPeople',
        'target': 'videos',
        'widget_style': 'Poster',
    },
    {
        'guid': 'pov-search-collections',
        'label': 'קולקציות',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_Popular.png',
        'path': 'DefaultSearch-POVCollections',
        'target': 'videos',
        'widget_style': 'Poster',
    },
]


FILES = {
    'skinvariables-shortcut-homewidgets.json': HOME_WIDGETS,
    'skinvariables-shortcut-homesubmenu.json': HOME_SUBMENU,
    'skinvariables-shortcut-powermenu.json': POWER_MENU,
    'skinvariables-shortcut-searchwidgets.json': SEARCH_WIDGETS,
}

TOUCH_CLEANUP_FILES = (
    'DialogVideoInfo.xml',
    'DialogContextMenu.xml',
    'Custom_1172_Dialog_InfoOptions.xml',
    'Custom_1190_TMDbHelper.xml',
)

TOUCH_CLEANUP_BLOCK = '''    <!-- POV_AF3_TOUCH_CLEANUP_v1 -->
    <onunload>ClearProperty(InfoPanel.FullSwitch,Home)</onunload>
    <onunload>ClearProperty(SubGroup.IsVisible,Home)</onunload>
    <onunload>ClearProperty(TMDbHelper.ContextMenu,Home)</onunload>
    <onunload>ClearProperty(TMDbHelper.WidgetContainer,Home)</onunload>
    <onunload>ClearProperty(CurrentID)</onunload>
'''


def _translate(path):
    return xbmcvfs.translatePath(path) if xbmcvfs else path


def _exists(path):
    try:
        return xbmcvfs.exists(_translate(path)) if xbmcvfs else os.path.exists(path)
    except Exception:
        return False


def _mkdir(path):
    real = _translate(path)
    if not os.path.isdir(real):
        os.makedirs(real)


def _read(path):
    with open(_translate(path), 'r', encoding='utf-8') as fh:
        return fh.read()


def _write(path, content):
    real = _translate(path)
    parent = os.path.dirname(real)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(real, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(content)


def _copy(src, dst):
    real_src = _translate(src)
    real_dst = _translate(dst)
    parent = os.path.dirname(real_dst)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(real_src, 'rb') as fh:
        data = fh.read()
    with open(real_dst, 'wb') as fh:
        fh.write(data)


def _version_tuple(ver):
    parts = []
    for chunk in str(ver).split('.'):
        num = ''.join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _read_addon_version(addon_id):
    addon_xml = 'special://home/addons/' + addon_id + '/addon.xml'
    if not _exists(addon_xml):
        return ''
    try:
        text = _read(addon_xml)[:600]
    except Exception:
        return ''
    # jurialmunkey declares version= on the <addon> tag, but the file also
    # opens with <?xml version="1.0"?>. Find the addon-tag version, not the
    # XML-decl one, by searching after the addon id.
    anchor = text.find(addon_id)
    search_from = anchor if anchor >= 0 else 0
    marker = 'version="'
    pos = text.find(marker, search_from)
    if pos < 0:
        return ''
    start = pos + len(marker)
    end = text.find('"', start)
    return text[start:end] if end > start else ''


def _read_af3_version():
    return _read_addon_version(AF3_SKIN_ID)


def _jurialmunkey_too_old():
    """True only when jurialmunkey is installed AND older than the minimum
    TMDbHelper needs. Missing entirely -> not our problem to detect here
    (the normal deps-pack install handles a fresh switch)."""
    current = _read_addon_version('script.module.jurialmunkey')
    if not current:
        return False
    try:
        return _version_tuple(current) < _version_tuple(JURIALMUNKEY_MIN_VERSION)
    except Exception:
        return False


def _request_ce_skin_upgrade():
    if xbmc is None:
        return False
    # Re-run the AF3 deps/skin install when EITHER the skin is on an older
    # version OR jurialmunkey is too old for the bundled TMDbHelper.
    #
    # OLDER, not DIFFERENT. This was an equality test, which reads as "is the
    # skin the version we ship" and behaves as "is it any other version at
    # all" -- so the moment the shipped pack moved ahead of this constant,
    # every up-to-date user was asked to upgrade on every boot. The wizard's
    # own gate (_af3_pack_current) has always compared with >=; this now does
    # the same, and a constant left behind again costs nothing instead of
    # costing a dialog a day.
    try:
        current_ok = (_version_tuple(_read_af3_version())
                      >= _version_tuple(AF3_CE_VERSION))
    except Exception:
        current_ok = _read_af3_version() == AF3_CE_VERSION
    if current_ok and not _jurialmunkey_too_old():
        return False
    try:
        xbmc.executebuiltin(
            'RunPlugin("plugin://plugin.program.kodipovilwizard/'
            '?mode=install&action=install_af3_ce")')
        return True
    except Exception:
        return False


def _json(data):
    return json.dumps(data, ensure_ascii=False, indent=4) + '\n'


def _write_if_changed(filename, data):
    path = AF3_NODES + filename
    content = _json(data)
    try:
        if _exists(path) and _read(path) == content:
            return False
    except Exception:
        pass
    _write(path, content)
    return True


# Node files the user can reorder/remove/add to via AF3's own widget editor.
# For these we MERGE instead of overwrite, so user customizations survive
# updates while we can still deliver new/changed tiles. ALL of the user-
# curatable shortcut/widget lists are merged -- a user who deletes items in the
# submenu (or search/power menu) must keep that deletion across restarts and
# updates, not have it overwritten back to our defaults every boot.
_MERGE_FILES = (
    'skinvariables-shortcut-homewidgets.json',
    'skinvariables-shortcut-homesubmenu.json',
    'skinvariables-shortcut-searchwidgets.json',
    'skinvariables-shortcut-powermenu.json',
)

# The two Umbrella-era rows, by the same 'path' key the merge uses as identity.
# Kept next to _MERGE_FILES because the filter that drops them and the merge
# that delivers them have to agree on what a row IS.
_UMBRELLA_MENU_PATHS = (
    'RunScript(service.subtitles.kodipovilai,action=search_provider)',
    'RunAddon("plugin.video.umbrella")',
)
_UMBRELLA_MENU_FILES = (
    'skinvariables-shortcut-homesubmenu.json',
    'skinvariables-shortcut-powermenu.json',
)


def _umbrella_installed():
    try:
        import xbmcaddon
        xbmcaddon.Addon('plugin.video.umbrella')
        return True
    except Exception:
        return False


def _item_key(item):
    """Stable identity for a widget item across our updates and user edits.
    'path' is unique per tile and present whether or not the user edited
    the node (the skinvariables editor preserves it)."""
    try:
        return item.get('path', '') or item.get('label', '')
    except Exception:
        return ''


def _merge_widget_nodes(filename, canonical):
    """3-way merge for a user-curated widget node, honoring the user's
    intent (keep removals + user-added tiles + their order) while still
    delivering our changes:
      * baseline = what WE last wrote (sidecar .<filename>.povbase).
      * current  = what's on disk now (may be user-edited).
      * canonical= what we ship now.
    Rules per tile keyed by path:
      - in current: keep the USER's copy BUT, if we still ship it, refresh
        its fields to ours (so e.g. limit/style updates propagate) while
        keeping the user's position; tiles the user added (not ours) stay.
      - removed by user (in baseline, not in current): do NOT re-add.
      - brand-new (in canonical, not in baseline, not in current): append
        so everyone gets new tiles.
    On first run (no baseline) we seed canonical verbatim. Returns True if
    the on-disk node changed. Always (re)writes the baseline to canonical.
    """
    path = AF3_NODES + filename
    base_path = POV_BASELINE_DIR + filename
    try:
        _mkdir(POV_BASELINE_DIR)
    except Exception:
        pass

    def _load(p):
        try:
            if _exists(p):
                return json.loads(_read(p))
        except Exception:
            pass
        return None

    canon_content = _json(canonical)

    # First run for this device, or node missing -> seed verbatim.
    current = _load(path)
    if current is None or not isinstance(current, list):
        wrote = _write_if_changed(filename, canonical)
        _write(base_path, canon_content)
        return wrote

    baseline = _load(base_path)
    if baseline is None or not isinstance(baseline, list):
        # We've written this node before the merge feature existed (or the
        # baseline was lost). Treat the CURRENT on-disk state as the
        # baseline so we never resurrect what the user already removed;
        # only genuinely NEW canonical tiles get added below.
        baseline = current

    canon_by_key = {}
    canon_order = []
    for it in canonical:
        k = _item_key(it)
        if k and k not in canon_by_key:
            canon_by_key[k] = it
            canon_order.append(k)
    base_keys = {_item_key(it) for it in baseline}
    cur_keys = {_item_key(it) for it in current}

    merged = []
    # 1) walk the user's current node in order: keep user-added tiles as-is;
    #    for tiles we still ship, refresh fields to ours (keep position).
    for it in current:
        k = _item_key(it)
        if k in canon_by_key:
            merged.append(canon_by_key[k])
        else:
            merged.append(it)  # user-added (or a tile we dropped) -> keep
    # 2) append brand-new canonical tiles: ours, never seen by this device
    #    (not in baseline) and not already present.
    for k in canon_order:
        if k not in base_keys and k not in cur_keys:
            merged.append(canon_by_key[k])

    merged_content = _json(merged)
    changed = False
    try:
        changed = (not _exists(path)) or (_read(path) != merged_content)
    except Exception:
        changed = True
    if changed:
        _write(path, merged_content)
    # Always refresh the baseline to the current canonical so the next
    # update's "brand-new" detection is correct.
    _write(base_path, canon_content)
    return changed


def _patch_font_xml():
    changed = False
    if os.path.isfile(BUNDLED_NOTO_FONT):
        try:
            if (not _exists(AF3_NOTO_FONT)
                    or os.path.getsize(_translate(AF3_NOTO_FONT))
                    != os.path.getsize(BUNDLED_NOTO_FONT)):
                _copy(BUNDLED_NOTO_FONT, AF3_NOTO_FONT)
                changed = True
        except Exception:
            pass
    try:
        if _exists(AF3_FONT_XML) and _read(AF3_FONT_XML) == FONT_XML:
            return changed
    except Exception:
        pass
    _write(AF3_FONT_XML, FONT_XML)
    return True


def _patch_hebrew_language():
    current = ''
    if _exists(AF3_HEBREW_PO):
        try:
            current = _read(AF3_HEBREW_PO)
        except Exception:
            current = ''
    if current == HEBREW_STRINGS_PO:
        return False
    try:
        _write(AF3_HEBREW_PO, HEBREW_STRINGS_PO)
        return True
    except Exception:
        return False


# Stable genre-icon location we control + ship via build_icons_patcher
# (resources/lib/media_assets/build_icons/Genres/genre_*.png). We point
# every genre row's iconImage here instead of POV's own media/genres/
# folder, which isn't shipped by us and vanishes on POV self-updates --
# the reason genre icons were blank on BOTH skins.

# Map of Hebrew genre label (stripped of [B]/[/B]) -> icon filename, so
# we can re-icon a row even when POV rebuilt it WITHOUT the original
# 'genres/...' iconImage prefix (the case the old prefix-only check
# silently skipped). Covers both the movie and TV genre sets.
GENRE_NAME_TO_ICON = {
    'אקשן': 'genre_action.png',
    'הרפתקאות': 'genre_adventure.png',
    'אקשן והרפתקאות': 'genre_action_adventure.png',
    'אנימציה': 'genre_animation.png',
    'קומדיה': 'genre_comedy.png',
    'פשע': 'genre_crime.png',
    'דוקומנטרי': 'genre_documentary.png',
    'דרמה': 'genre_drama.png',
    'משפחה': 'genre_family.png',
    'פנטזיה': 'genre_fantasy.png',
    'היסטוריה': 'genre_history.png',
    'אימה': 'genre_horror.png',
    'מוזיקה': 'genre_music.png',
    'מסתורין': 'genre_mystery.png',
    'רומנטיקה': 'genre_romance.png',
    'מדע בדיוני': 'genre_scifi.png',
    'מדע בדיוני ופנטזיה': 'genre_scifi_fantasy.png',
    'מתח': 'genre_thriller.png',
    'מלחמה': 'genre_war.png',
    'מלחמה ופוליטיקה': 'genre_war_politics.png',
    'מערבון': 'genre_western.png',
    'ילדים': 'genre_kids.png',
    'חדשות': 'genre_news.png',
    'ריאליטי': 'genre_reality.png',
    'אופרת סבון': 'genre_soap.png',
    'אירוח': 'genre_talk.png',
}


# NOTE: the old _genre_icon_for()/GENRE_ICON_BASE helpers (which returned
# an ABSOLUTE special://home/media/build_icons/Genres/... path) were
# REMOVED in v0.2.85. They were the bug: POV's build_shortcut_folder_list
# prepends media_path() to a non-network iconImage, so an absolute value
# got doubled into a broken '.../media/special://...' path -> POV-logo
# fallback. The correct approach is _heal_genre_icon() below, which writes
# the RELATIVE 'genres/<file>' POV already ships and resolves. Keeping the
# dead absolute helpers risked a future re-corruption, so they're gone.


def _heal_genre_icon(item):
    """Return the CORRECT relative iconImage for a genre row item, or ''
    to leave it. POV's build_shortcut_folder_list (navigator.py:446)
    unconditionally prepends media_path() to a non-network item's
    iconImage, so the value MUST be a bare relative path like
    'genres/genre_action.png' -- POV ships those icons in its media dir.
    An earlier version of this patcher wrongly stored an ABSOLUTE
    'special://home/media/build_icons/Genres/...' path, which POV then
    doubled into a broken '.../media/special://home/...' -> POV-logo
    fallback. This heals that: any absolute special:// value (or a
    bare filename without the 'genres/' dir) is mapped back to
    'genres/<file>' by the Hebrew genre name."""
    icon = item.get('iconImage', '') or ''
    # Already the correct relative form -> leave it.
    if icon.startswith('genres/'):
        return ''
    # Map by Hebrew name to the canonical relative path.
    name = (item.get('name', '') or '')
    name = name.replace('[B]', '').replace('[/B]', '').strip()
    fn = GENRE_NAME_TO_ICON.get(name)
    if fn:
        return 'genres/' + fn
    # If it's an absolute special:// path ending in a known genre file,
    # salvage the filename.
    if 'special://' in icon and icon.lower().endswith('.png'):
        base = icon.rsplit('/', 1)[-1]
        if base.startswith('genre_'):
            return 'genres/' + base
    return ''


def _patch_pov_genre_icons():
    if sqlite3 is None or ast is None:
        return False
    db_path = _translate(POV_NAVIGATOR_DB)
    if not os.path.isfile(db_path):
        return False

    changed = False
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=2.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=2000')
        cur = conn.cursor()
        for row_name in (
                'FENtastic - סרטים - זאנרים',
                'FENtastic - סדרות - זאנרים'):
            cur.execute(
                'SELECT list_contents FROM navigator WHERE list_name=?',
                (row_name,))
            row = cur.fetchone()
            if not row:
                continue
            try:
                items = ast.literal_eval(row[0] or '[]')
            except Exception:
                continue
            row_changed = False
            for item in items:
                new_icon = _heal_genre_icon(item)
                if new_icon and item.get('iconImage', '') != new_icon:
                    item['iconImage'] = new_icon
                    row_changed = True
            if not row_changed:
                continue
            cur.execute('BEGIN IMMEDIATE')
            try:
                cur.execute(
                    'UPDATE navigator SET list_contents=? WHERE list_name=?',
                    (repr(items), row_name))
                cur.execute('COMMIT')
                changed = True
            except Exception:
                try:
                    cur.execute('ROLLBACK')
                except Exception:
                    pass
    except Exception:
        return changed
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return changed


def _patch_touch_cleanup_xml():
    changed = False
    for filename in TOUCH_CLEANUP_FILES:
        path = AF3_XML_DIR + filename
        if not _exists(path):
            continue
        try:
            text = _read(path)
        except Exception:
            continue
        if 'POV_AF3_TOUCH_CLEANUP_v1' in text:
            continue
        if '<window' not in text:
            continue
        marker = text.find('>', text.find('<window'))
        if marker < 0:
            continue
        new_text = text[:marker + 1] + '\n' + TOUCH_CLEANUP_BLOCK + text[marker + 1:]
        try:
            _write(path, new_text)
            changed = True
        except Exception:
            pass
    return changed


def _patch_info_plot_autoscroll_xml():
    # v1 set time=26000 (a 26-second crawl -- far slower than other skins).
    # v2 speeds it up to match the others. Revert any prior version of OUR
    # autoscroll line, then (re)apply the current one, so existing installs that
    # already have the slow v1 get the faster value.
    if not _exists(AF3_INFO_XML):
        return False
    try:
        text = _read(AF3_INFO_XML)
    except Exception:
        return False
    if 'POV_AF3_PLOT_AUTOSCROLL_v2' in text:
        return False  # already at the faster value
    import re as _re
    # Strip any earlier version of our marker + autoscroll line.
    text = _re.sub(
        r'[ \t]*<!-- POV_AF3_PLOT_AUTOSCROLL_v\d+ -->\n'
        r'[ \t]*<autoscroll[^\n]*</autoscroll>\n', '', text)
    needle = (
        '                <height>$PARAM[height]</height>\n'
        '                <left>40</left>\n'
        '                <font>font_main_plot</font>\n'
        '                <nested />')
    repl = (
        '                <height>$PARAM[height]</height>\n'
        '                <left>40</left>\n'
        '                <font>font_main_plot</font>\n'
        '                <!-- POV_AF3_PLOT_AUTOSCROLL_v2 -->\n'
        '                <autoscroll delay="2000" time="8000" repeat="5000">true</autoscroll>\n'
        '                <nested />')
    if needle not in text:
        return False
    try:
        _write(AF3_INFO_XML, text.replace(needle, repl, 1))
        return True
    except Exception:
        return False


def _enable_touch_input():
    # AF3's home was built for a remote: the main menu is an off-screen list
    # driven by an invisible focus-holder button, so taps on the visible menu
    # items do nothing. Enabling Kodi's mouse/pointer support is the safe first
    # step for phones - it makes the *real* controls (widget rows, spotlight,
    # the submenu buttons once visible) respond to taps and lets lists be
    # drag-scrolled. It has no effect on remote/TV navigation.
    if xbmc is None:
        return False
    settings = (
        ('input.enablemouse', True),
        # Show the pointer so users can see where their tap lands.
        ('input.enablepointer', True),
    )
    changed = False
    for setting_id, value in settings:
        payload = json.dumps({
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'Settings.SetSettingValue',
            'params': {'setting': setting_id, 'value': value},
        })
        try:
            xbmc.executeJSONRPC(payload)
            changed = True
        except Exception:
            pass
    return changed


def _set_af3_runtime_defaults():
    if xbmc is None:
        return
    commands = [
        'Skin.SetBool(Textboxes.DisableFakeBox)',
        # NOTE: the Spotlight.* strings AND the Home.Shortcut.Path are NOT seeded
        # here every boot anymore -- they're user-customisable (path/target/
        # label/limit), and re-setting them on every startup reverted the user's
        # change (arctic.fuse 3: edited menu-hub path reverted after restart).
        # They're now seeded once via _seed_af3_spotlight_once().
        # SAME treatment for the HomeSwitcher layout (Vertical/Mode) and the
        # CustomRating rows: they're user-facing skin choices, and forcing them
        # on every rebuild reset a customised AF3 home layout after each
        # quickfix (PATCH_VERSION bump -> rebuild -> layout back to Standard).
        # They're now seeded once via _seed_af3_layout_once(). Only the infra
        # settings the build NEEDS to function stay forced here.
        'Skin.Reset(TMDbHelper.DisableRatings)',
        'Skin.SetBool(TMDbHelper.EnableData)',
        'Skin.SetBool(TMDbHelper.Service)',
        'Skin.SetBool(TMDbHelper.DirectCallAuto)',
        'Skin.SetBool(TMDbHelper.UseLocalWidgetContainer)',
        # Widgets keep their fast per-row limit, but enabling "Show More"
        # makes AF3 append a "More..." tile at the end of every limited
        # widget (browse="auto" via Defs_BrowseLimitedLists). Selecting it
        # opens the FULL list of that widget's POV path (e.g. all 70 Trakt
        # collection shows) -- the quick "view all" the build was missing.
        'Skin.SetBool(Widgets.EnableShowMore)',
        'ClearProperty(InfoPanel.FullSwitch,Home)',
        'ClearProperty(SubGroup.IsVisible,Home)',
        # NOTE: the Discover grid is repointed to POV by patching
        # Custom_1105_Search.xml's onload directly (af3_discover_pov_
        # patcher) -- a deterministic file edit, not a Home-property seed.
        # The earlier SetProperty seed here was unreliable: it sat behind
        # the _is_af3_active() gate and raced the window's own onload.
    ]
    for command in commands:
        try:
            xbmc.executebuiltin(command)
        except Exception:
            pass


_LAYOUT_MARKER = AF3_NODES + '.pov_layout_seeded'
_LAYOUT_COMMANDS = [
    'Skin.SetString(CustomRating.Movies.Item01,TMDb)',
    'Skin.SetString(CustomRating.Movies.Item02,IMDb)',
    'Skin.SetString(CustomRating.Movies.Item03,RottenTomatoesUser)',
    'Skin.SetString(CustomRating.TVShows.Item01,TMDb)',
    'Skin.SetString(CustomRating.TVShows.Item02,IMDb)',
    'Skin.SetString(CustomRating.TVShows.Item03,Trakt)',
    'Skin.Reset(HomeSwitcher.Vertical)',
    'Skin.SetString(HomeSwitcher.Home.Mode,Standard)',
    'Skin.SetString(HomeSwitcher.1101.Mode,Standard)',
    'Skin.SetString(HomeSwitcher.1102.Mode,Standard)',
]


# Arctic Fuse 3 declares FIVE submenu slots in its generator data --
# homesubmenu, 1101submenu, 1102submenu, 1103submenu, 1104submenu -- but ships
# a stock node file for the first one only. Includes_Home.xml builds the
# include name from the slot at parse time, so reaching a slot whose node was
# never written leaves <include>skinvariables-1102submenu-staticitems</include>
# unresolved. Kodi leaves the unresolved element in the tree rather than
# dropping it, the directory provider then reads the literal string "include"
# as a path, and a user hit exactly that: the submenu dialog opened for the
# first time and Kodi was gone eight milliseconds later.
#
# NOT OUR BUG -- the slots, the generator data and the missing files are all
# stock AF3, and nothing here creates or deletes any of them (established by
# running this module end-to-end against a fake filesystem). But it is our
# users' crash, and a file we can write costs nothing.
#
# THE NODES ARE EMPTY ON PURPOSE. Seeding real entries would put menu items in
# a submenu the user never populated. An empty list resolves the include and
# leaves the slot looking exactly as empty as the user left it. Writing one
# does not make a slot visible either: AF3 gates that on HomeSwitcher.<id>.Toggle,
# which only its own settings screen sets and which this build never touches.
AF3_EMPTY_SUBMENUS = ('1101submenu', '1102submenu', '1103submenu',
                      '1104submenu')


def _seed_af3_empty_submenus():
    """Write an empty node for each AF3 submenu slot that has none.

    Never overwrites: a slot the user has populated through AF3's own Edit Menu
    has a node already, and that is theirs. Returns the number written.
    """
    if xbmcvfs is None:
        return 0
    written = 0
    for slot in AF3_EMPTY_SUBMENUS:
        target = AF3_NODES + 'skinvariables-shortcut-' + slot + '.json'
        try:
            if _exists(target):
                continue
            _mkdir(AF3_NODES)
            _write(target, _json([]))
            written += 1
        except Exception:
            # NO LOGGING HERE. This module has none -- it reports through the
            # status its caller logs -- and reaching for a _log() that does not
            # exist would raise NameError inside this except and take the whole
            # seeding pass down silently. That has happened here before.
            continue
    return written


def _seed_af3_layout_once():
    """Seed the home-layout / rating-row defaults ONCE, then never touch them
    again, so a user who changes the AF3 home layout (switcher mode, vertical
    menu) or the rating rows keeps that across restarts AND quickfix updates
    (every PATCH_VERSION bump used to force these back to Standard). Mirrors
    _seed_af3_spotlight_once: brand-new AF3 installs get the defaults; devices
    that were already seeded before just claim ownership without overwriting."""
    if xbmc is None:
        return
    try:
        if _exists(_LAYOUT_MARKER):
            return  # already decided once -> never re-seed (user owns it now)
        fresh = not _exists(AF3_NODES + '.pov_home_version')
        if fresh:
            for command in _LAYOUT_COMMANDS:
                try:
                    xbmc.executebuiltin(command)
                except Exception:
                    pass
        _write(_LAYOUT_MARKER, PATCH_VERSION + '\n')
    except Exception:
        pass


_SPOTLIGHT_MARKER = AF3_NODES + '.pov_spotlight_seeded'
_SPOTLIGHT_COMMANDS = [
    'Skin.SetString(HomeSwitcher.Home.Spotlight.Path,plugin://plugin.video.pov/?action=tmdb_movies_latest_releases&iconImage=dvd.png&mode=build_movie_list&name=32461)',
    'Skin.SetString(HomeSwitcher.Home.Spotlight.Target,videos)',
    'Skin.SetString(HomeSwitcher.Home.Spotlight.Label,סרטים חדשים)',
    'Skin.SetString(HomeSwitcher.Home.Spotlight.Limit,10)',
    # The main menu-hub shortcut path: seeded once here (was previously re-set
    # on every boot in _set_af3_runtime_defaults, which reverted a user's edit
    # of the hub path after each restart).
    'Skin.SetString(HomeSwitcher.Home.Shortcut.Path,ActivateWindow(1181))',
]


def _seed_af3_spotlight_once():
    """Seed the Spotlight defaults ONCE, then never touch them again, so a
    user who changes the spotlight (path, or sets it to None) keeps that across
    restarts/updates. Brand-new AF3 installs (no prior home-version marker) get
    the default spotlight; existing users keep whatever they currently have."""
    if xbmc is None:
        return
    try:
        if _exists(_SPOTLIGHT_MARKER):
            return  # already decided once -> never re-seed (user owns it now)
        # Only seed the default on a TRULY fresh AF3 setup. If AF3 was already
        # seeded before (home-version marker present), the user may have
        # customised the spotlight -> do NOT overwrite it; just claim ownership.
        fresh = not _exists(AF3_NODES + '.pov_home_version')
        if fresh:
            for command in _SPOTLIGHT_COMMANDS:
                try:
                    xbmc.executebuiltin(command)
                except Exception:
                    pass
        _write(_SPOTLIGHT_MARKER, PATCH_VERSION + '\n')
    except Exception:
        pass


def _is_af3_active():
    if xbmc is None:
        return False
    try:
        return (xbmc.getSkinDir() or '').lower() == AF3_SKIN_ID
    except Exception:
        return False


def _quick_update_notice_pending():
    """Avoid AF3 rebuild/reload while the wizard's quick-update
    changelog is waiting to be read.

    Other skins do not run our skinvariables rebuild path, so the issue
    is AF3-specific: ReloadSkin()/script.skinvariables can close or cover
    the wizard's notification immediately after an update. If the wizard
    says the quick-update notice is still not dismissed, defer this AF3
    rebuild. The marker is written only after a successful rebuild, so the
    next startup retries normally after the user closes the notice.
    """
    if xbmcaddon is None:
        return False
    try:
        wizard = xbmcaddon.Addon('plugin.program.kodipovilwizard')
        return (wizard.getSetting('quick_update_notedismiss') == 'false'
                and bool(wizard.getSetting('quick_update_noteid')))
    except Exception:
        return False


def _wait_for_quick_update_notice(max_seconds=180):
    if xbmc is None:
        return False
    if not _quick_update_notice_pending():
        return False
    monitor = xbmc.Monitor()
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        if monitor.waitForAbort(1):
            return True
        if not _quick_update_notice_pending():
            return False
    return _quick_update_notice_pending()


def _rebuild_af3_shortcuts():
    """True when the rebuild actually ran. THE RETURN VALUE IS LOAD-BEARING:
    ensure_patched() must only write the version marker when it is True, or a
    rebuild that did not happen is recorded as done and never retried."""
    if xbmc is None:
        return False
    # Arctic Fuse 3's own route to the same fault FENtastic hit: this rebuilds
    # the shortcut templates and then reloads the skin, so POV's home tiles are
    # redrawn. Doing that while pov_reload has POV disabled leaves every one of
    # them raising "Unknown addon id". Waiting costs a delayed rebuild; not
    # waiting costs the home screen.
    #
    # The wait is computed inside the try and acted on OUTSIDE it. Putting the
    # `return` inside meant any exception in here -- including one from the
    # logging call this module does not actually have -- was swallowed by the
    # except and execution fell straight through to the rebuild. A guard that
    # fails open silently is worse than no guard, because it reads as covered.
    settled = True
    try:
        from resources.lib import pov_reload
        settled = pov_reload.wait_until_settled()
    except Exception:
        settled = True          # no pov_reload here means nothing to wait for
    if not settled:
        return False
    _set_af3_runtime_defaults()
    _seed_af3_spotlight_once()
    _seed_af3_layout_once()
    stamp = '{0}-{1}'.format(PATCH_VERSION, int(time.time()))
    xbmc.executebuiltin('Skin.SetString(Shortcuts.RebuildDateTime,{0})'.format(stamp))
    xbmc.executebuiltin('RunScript(script.skinvariables,action=buildtemplate,force=True,background=true)')
    xbmc.sleep(1200)
    xbmc.executebuiltin('ReloadSkin()')
    xbmc.sleep(1800)
    xbmc.executebuiltin('SetFocus(310)')
    xbmc.executebuiltin('AlarmClock(POVAF3FocusSpotlight,SetFocus(310),00:02,silent)')
    return True


def ensure_patched():
    if xbmcvfs is None:
        return 'no_kodi'
    if not _exists('special://home/addons/' + AF3_SKIN_ID + '/addon.xml'):
        return 'no_af3'

    upgrade_requested = _request_ce_skin_upgrade()

    _enable_touch_input()

    _mkdir(AF3_NODES)
    changed = False
    mdblist_ok = _mdblist_connected()
    umbrella_ok = _umbrella_installed()
    for filename, data in FILES.items():
        # The Umbrella + search-engine rows are opt-in the same way: without
        # Umbrella the search switch has nothing to switch to and the Umbrella
        # row opens an add-on that is not there, so both are dropped from the
        # canonical. Installing Umbrella later appends them on the next boot
        # (brand-new against the baseline); removing Umbrella leaves them,
        # because the 3-way merge is add-only and a row the user has since
        # curated is theirs.
        if not umbrella_ok and filename in _UMBRELLA_MENU_FILES:
            data = [w for w in data
                    if (w.get('path') or '') not in _UMBRELLA_MENU_PATHS]
        # MDBList home widgets are opt-in: drop them from the canonical unless
        # MDBList is connected, so the merge never seeds/appends an mdblist_
        # watchlist row that would error without a key. A user who connects
        # later gets it appended on the next boot (brand-new vs the baseline);
        # the 3-way merge keeps it if they later disconnect (add-only), matching
        # the favourites tiles.
        if filename == 'skinvariables-shortcut-homewidgets.json' and not mdblist_ok:
            data = [w for w in data if 'mdblist_watchlist' not in (w.get('path') or '')]
        if filename in _MERGE_FILES:
            changed = _merge_widget_nodes(filename, data) or changed
        else:
            changed = _write_if_changed(filename, data) or changed
    changed = _patch_font_xml() or changed
    changed = _patch_hebrew_language() or changed
    changed = _patch_pov_genre_icons() or changed
    changed = _patch_touch_cleanup_xml() or changed
    changed = _patch_info_plot_autoscroll_xml() or changed
    # Inject POV search rules into search_path.xml BEFORE the rebuild, so
    # buildtemplate regenerates the search includes with our POV rows
    # resolving to real POV search paths. Must precede _rebuild_af3_
    # shortcuts (below). Best-effort; never blocks the rest.
    try:
        from resources.lib import af3_search_pov_patcher
        st = af3_search_pov_patcher.ensure_patched()
        if st == 'patched':
            changed = True
    except Exception:
        pass
    # Repoint the DISCOVER GRID (window 1105) from TMDbHelper to POV by
    # patching Custom_1105_Search.xml's onload + stripping the TMDbHelper
    # with_text_query suffix in Includes_Search.xml. Deterministic file
    # edit (no Home-property race). Also before the rebuild.
    try:
        from resources.lib import af3_discover_pov_patcher
        st2 = af3_discover_pov_patcher.ensure_patched()
        if isinstance(st2, str) and '=patched' in st2:
            changed = True
    except Exception:
        pass
    if _is_af3_active():
        _set_af3_runtime_defaults()
        _seed_af3_spotlight_once()
        _seed_af3_layout_once()
        # Every AF3 boot, not only the ones that rebuild: the crash this
        # prevents is reached by opening a submenu, which has nothing to do
        # with whether anything needed patching. It writes only files that are
        # missing, so on all boots after the first it does four existence
        # checks and stops.
        _seed_af3_empty_submenus()

    marker = AF3_NODES + '.pov_home_version'
    marker_changed = True
    try:
        marker_changed = (not _exists(marker)) or (_read(marker).strip() != PATCH_VERSION)
    except Exception:
        pass
    # NOTE: do NOT write the marker yet. Earlier code wrote it here and
    # set changed=True, but then only rebuilt when _is_af3_active() was
    # true at THIS instant. If AF3 wasn't reported active during the
    # boot-time run (skin still loading), the nodes were written but the
    # skin was never rebuilt -- and because the marker had already
    # advanced to the new PATCH_VERSION, every later boot returned
    # 'already_patched' and never rebuilt. So new tiles (networks,
    # idanplus) never surfaced. We now treat a marker bump as a reason to
    # rebuild, and only persist the marker AFTER a rebuild actually runs,
    # so a missed rebuild is retried on the next boot.
    want_rebuild = changed or marker_changed

    if want_rebuild and _is_af3_active():
        if _wait_for_quick_update_notice():
            return 'rebuild_deferred_quick_update_notice'
        # The marker is written ONLY when the rebuild really ran -- the same
        # rule the comment above states, and the one the pov_reload guard
        # inside _rebuild_af3_shortcuts broke by returning early with no way
        # for this caller to tell. Measured before this line: the rebuild was
        # skipped, the marker was written anyway, and the next boot returned
        # 'already_patched' -- so a DEFERRED rebuild became a DROPPED one,
        # permanently, while the log said 'patched_rebuilt'.
        if not _rebuild_af3_shortcuts():
            return 'rebuild_deferred_pov_cycling'
        try:
            _write(marker, PATCH_VERSION + '\n')
        except Exception:
            pass
        return 'patched_rebuilt'
    if upgrade_requested:
        return 'upgrade_requested'
    if want_rebuild:
        # Content/version changed but AF3 wasn't active to rebuild. Leave
        # the marker UNwritten so the next boot (or next AF3 activation)
        # retries the rebuild instead of being suppressed as up-to-date.
        return 'patched'
    return 'already_patched'
