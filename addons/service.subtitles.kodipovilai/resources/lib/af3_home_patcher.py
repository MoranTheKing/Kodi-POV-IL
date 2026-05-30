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
    import xbmcvfs
except ImportError:
    xbmc = None
    xbmcvfs = None


AF3_SKIN_ID = 'skin.arctic.fuse.3'
PATCH_VERSION = '2026-05-31-pov-home-v10'
AF3_CE_VERSION = '6.3.2.9'
# AF3's bundled TMDbHelper 6.15.6 imports jurialmunkey.ftools, which only
# exists from script.module.jurialmunkey 0.2.35. Users who switched to AF3
# while an older jurialmunkey (e.g. 0.2.28) was on disk get a TMDbHelper that
# crash-loops its service on every startup -> AF3 widgets/ratings break. If we
# detect an older jurialmunkey we re-trigger the deps-pack install (which now
# has a version gate and overwrites the stale copy).
JURIALMUNKEY_MIN_VERSION = '0.2.35'

BASE_NODES = 'special://profile/addon_data/script.skinvariables/nodes/'
AF3_NODES = BASE_NODES + AF3_SKIN_ID + '/'
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
        'widget_limit': '20',
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
        'widget_limit': '20',
    },
    {
        'label': 'סרטים חדשים',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_Popular.png',
        'path': _pov('tmdb_movies_latest_releases', 'build_movie_list', '32461', 'dvd.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '20',
    },
    {
        'label': 'סדרות פופולריות',
        'icon': 'special://home/media/build_icons/Twilight/Shows/Shows_Popular.png',
        'path': _pov('trakt_tv_trending', 'build_tvshow_list', '32458', 'trending.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '20',
    },
    {
        'label': 'פרקים להמשך צפייה',
        'icon': 'special://home/media/build_icons/Twilight/Shows/Episodes_In_Progress.png',
        'path': _pov('', 'build_next_episode', '32483', 'next_episodes.png'),
        'target': 'videos',
        'widget_style': 'Landscape',
        'widget_limit': '20',
    },
    {
        'label': 'סרטים להמשך צפייה',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_In_Progress.png',
        'path': _pov('in_progress_movies', 'build_movie_list', '32476', 'player.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '20',
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
        'widget_limit': '20',
    },
    {
        # TMDB.org account favorites (the online list, synced across
        # devices). Kept alongside the local one so the user has both.
        'label': 'הסרטים שלי (TMDB)',
        'icon': 'special://home/media/build_icons/Twilight/Movies/My_Movies_TMDB.png',
        'path': _pov('tmdb_favorites', 'build_movie_list', 'Movie%20Favorites%20(TMDB)',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '20',
    },
    {
        # POV-LOCAL show favorites (watched.db -> favorites).
        'label': 'הסדרות שלי',
        'icon': 'special://home/media/build_icons/Twilight/Shows/My_Shows_TMDB.png',
        'path': _pov('favorites_tvshows', 'build_tvshow_list', 'TV%20Show%20Favorites',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '20',
    },
    {
        # TMDB.org account show favorites (online list).
        'label': 'הסדרות שלי (TMDB)',
        'icon': 'special://home/media/build_icons/Twilight/Shows/My_Shows_TMDB.png',
        'path': _pov('tmdb_favorites', 'build_tvshow_list', 'TV%20Show%20Favorites%20(TMDB)',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '20',
    },
    {
        'label': 'סרטים לפי ז׳אנר',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_Genres.png',
        'path': _shortcut_folder('FENtastic - סרטים - זאנרים',
                                 'special://home/media/build_icons/Twilight/Movies/Movies_Genres.png'),
        'target': 'videos',
        'widget_style': 'Landscape',
        'widget_limit': '20',
    },
    {
        'label': 'סדרות לפי ז׳אנר',
        'icon': 'special://home/media/build_icons/Twilight/Shows/Shows_Genres.png',
        'path': _shortcut_folder('FENtastic - סדרות - זאנרים',
                                 'special://home/media/build_icons/Twilight/Shows/Shows_Genres.png'),
        'target': 'videos',
        'widget_style': 'Landscape',
        'widget_limit': '20',
    },
] + STREAMING_NETWORK_WIDGETS + [
    {
        # עידן פלוס -- launches the idanplus addon directly. It's not a
        # TMDB list, so the tile just runs the addon (FENtastic does the
        # same via a favourites.xml RunAddon entry).
        'label': 'עידן פלוס',
        'icon': 'special://home/media/build_icons/Idan_Plus/idan_plus.png',
        'path': 'RunAddon("plugin.video.idanplus")',
        'target': '',
        'widget_style': 'Landscape',
        'widget_limit': '20',
    },
]


HOME_SUBMENU = [
    {
        'label': 'POV',
        'icon': 'special://home/media/build_icons/POV/Logo_POV.png',
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
        'label': 'תרגום AI',
        'icon': 'special://home/addons/service.subtitles.kodipovilai/icon.png',
        'path': 'Addon.OpenSettings(service.subtitles.kodipovilai)',
        'target': '',
    },
    {
        'label': 'החלף סקין',
        'icon': 'special://home/media/build_icons/Wizard/wizard.png',
        'path': 'RunPlugin("plugin://plugin.program.kodipovilwizard/?mode=install&action=build_switch_skin")',
        'target': '',
    },
]


POWER_MENU = [
    {
        'label': 'POV',
        'icon': 'special://home/media/build_icons/POV/Logo_POV.png',
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
        'icon': 'special://home/media/build_icons/Wizard/wizard.png',
        'path': 'RunPlugin("plugin://plugin.program.kodipovilwizard/?mode=install&action=build_switch_skin")',
        'target': '',
    },
    {
        'label': 'עדכון מהיר',
        'icon': 'special://home/media/build_icons/Wizard/fast_update.png',
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


FILES = {
    'skinvariables-shortcut-homewidgets.json': HOME_WIDGETS,
    'skinvariables-shortcut-homesubmenu.json': HOME_SUBMENU,
    'skinvariables-shortcut-powermenu.json': POWER_MENU,
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
    if _read_af3_version() == AF3_CE_VERSION and not _jurialmunkey_too_old():
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
GENRE_ICON_BASE = 'special://home/media/build_icons/Genres/'

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


def _genre_icon_for(item):
    """Return the stable build_icons/Genres icon path for a genre row
    item, or '' if we can't map it. Tries the original 'genres/<file>'
    suffix first, then the Hebrew label."""
    icon = item.get('iconImage', '') or ''
    if icon.startswith('genres/'):
        return GENRE_ICON_BASE + icon[len('genres/'):]
    # Fall back to the Hebrew name (strip [B]..[/B] and whitespace).
    name = (item.get('name', '') or '')
    name = name.replace('[B]', '').replace('[/B]', '').strip()
    fn = GENRE_NAME_TO_ICON.get(name)
    if fn:
        return GENRE_ICON_BASE + fn
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
                new_icon = _genre_icon_for(item)
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
    if not _exists(AF3_INFO_XML):
        return False
    try:
        text = _read(AF3_INFO_XML)
    except Exception:
        return False
    if 'POV_AF3_PLOT_AUTOSCROLL_v1' in text:
        return False
    needle = (
        '                <height>$PARAM[height]</height>\n'
        '                <left>40</left>\n'
        '                <font>font_main_plot</font>\n'
        '                <nested />')
    repl = (
        '                <height>$PARAM[height]</height>\n'
        '                <left>40</left>\n'
        '                <font>font_main_plot</font>\n'
        '                <!-- POV_AF3_PLOT_AUTOSCROLL_v1 -->\n'
        '                <autoscroll delay="3000" time="26000" repeat="10000">true</autoscroll>\n'
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
        'Skin.SetBool(Textboxes.DisableFakeBox)',
        'Skin.SetString(HomeSwitcher.Home.Spotlight.Path,plugin://plugin.video.pov/?action=tmdb_movies_latest_releases&iconImage=dvd.png&mode=build_movie_list&name=32461)',
        'Skin.SetString(HomeSwitcher.Home.Spotlight.Target,videos)',
        'Skin.SetString(HomeSwitcher.Home.Spotlight.Label,סרטים חדשים)',
        'Skin.SetString(HomeSwitcher.Home.Spotlight.Limit,10)',
        'Skin.SetString(HomeSwitcher.Home.Shortcut.Path,ActivateWindow(1181))',
        'Skin.Reset(TMDbHelper.DisableRatings)',
        'Skin.SetBool(TMDbHelper.EnableData)',
        'Skin.SetBool(TMDbHelper.Service)',
        'Skin.SetBool(TMDbHelper.DirectCallAuto)',
        'Skin.SetBool(TMDbHelper.UseLocalWidgetContainer)',
        'ClearProperty(InfoPanel.FullSwitch,Home)',
        'ClearProperty(SubGroup.IsVisible,Home)',
    ]
    for command in commands:
        try:
            xbmc.executebuiltin(command)
        except Exception:
            pass


def _is_af3_active():
    if xbmc is None:
        return False
    try:
        return (xbmc.getSkinDir() or '').lower() == AF3_SKIN_ID
    except Exception:
        return False


def _rebuild_af3_shortcuts():
    if xbmc is None:
        return
    _set_af3_runtime_defaults()
    stamp = '{0}-{1}'.format(PATCH_VERSION, int(time.time()))
    xbmc.executebuiltin('Skin.SetString(Shortcuts.RebuildDateTime,{0})'.format(stamp))
    xbmc.executebuiltin('RunScript(script.skinvariables,action=buildtemplate,force=True,background=true)')
    xbmc.sleep(1200)
    xbmc.executebuiltin('ReloadSkin()')
    xbmc.sleep(1800)
    xbmc.executebuiltin('SetFocus(310)')
    xbmc.executebuiltin('AlarmClock(POVAF3FocusSpotlight,SetFocus(310),00:02,silent)')


def ensure_patched():
    if xbmcvfs is None:
        return 'no_kodi'
    if not _exists('special://home/addons/' + AF3_SKIN_ID + '/addon.xml'):
        return 'no_af3'

    upgrade_requested = _request_ce_skin_upgrade()

    _enable_touch_input()

    _mkdir(AF3_NODES)
    changed = False
    for filename, data in FILES.items():
        changed = _write_if_changed(filename, data) or changed
    changed = _patch_font_xml() or changed
    changed = _patch_hebrew_language() or changed
    changed = _patch_pov_genre_icons() or changed
    changed = _patch_touch_cleanup_xml() or changed
    changed = _patch_info_plot_autoscroll_xml() or changed
    if _is_af3_active():
        _set_af3_runtime_defaults()

    marker = AF3_NODES + '.pov_home_version'
    marker_changed = True
    try:
        marker_changed = (not _exists(marker)) or (_read(marker).strip() != PATCH_VERSION)
    except Exception:
        pass
    if marker_changed:
        _write(marker, PATCH_VERSION + '\n')
        changed = True

    if changed and _is_af3_active():
        _rebuild_af3_shortcuts()
        return 'patched_rebuilt'
    if upgrade_requested:
        return 'upgrade_requested'
    if changed:
        return 'patched'
    return 'already_patched'
