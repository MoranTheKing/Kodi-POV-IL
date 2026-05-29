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

try:
    import xbmc
    import xbmcvfs
except ImportError:
    xbmc = None
    xbmcvfs = None


AF3_SKIN_ID = 'skin.arctic.fuse.3'
PATCH_VERSION = '2026-05-29-pov-home-v1'

BASE_NODES = 'special://profile/addon_data/script.skinvariables/nodes/'
AF3_NODES = BASE_NODES + AF3_SKIN_ID + '/'


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


HOME_WIDGETS = [
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
        'label': 'הסרטים שלי',
        'icon': 'special://home/media/build_icons/Twilight/Movies/My_Movies_TMDB.png',
        'path': _pov('tmdb_favorites', 'build_movie_list', 'Movie%20Favorites',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '20',
    },
    {
        'label': 'הסדרות שלי',
        'icon': 'special://home/media/build_icons/Twilight/Shows/My_Shows_TMDB.png',
        'path': _pov('tmdb_favorites', 'build_tvshow_list', 'TV%20Show%20Favorites',
                     'special%3a%2f%2fhome%2faddons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2fmedia%2ftmdb.png'),
        'target': 'videos',
        'widget_style': 'Poster',
        'widget_limit': '20',
    },
    {
        'label': 'סרטים לפי זאנר',
        'icon': 'special://home/media/build_icons/Twilight/Movies/Movies_Genres.png',
        'path': _pov('', 'navigator.genres', '32470', 'genres.png', 'menu_type=movie'),
        'target': 'videos',
        'widget_style': 'Landscape',
        'widget_limit': '20',
    },
    {
        'label': 'סדרות לפי זאנר',
        'icon': 'special://home/media/build_icons/Twilight/Shows/Shows_Genres.png',
        'path': _pov('', 'navigator.genres', '32470', 'genres.png', 'menu_type=tvshow'),
        'target': 'videos',
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
    stamp = '{0}-{1}'.format(PATCH_VERSION, int(time.time()))
    xbmc.executebuiltin('Skin.SetString(Shortcuts.RebuildDateTime,{0})'.format(stamp))
    xbmc.executebuiltin('RunScript(script.skinvariables,action=buildtemplate,force=True,background=true)')
    xbmc.sleep(1200)
    xbmc.executebuiltin('ReloadSkin()')


def ensure_patched():
    if xbmcvfs is None:
        return 'no_kodi'
    if not _exists('special://home/addons/' + AF3_SKIN_ID + '/addon.xml'):
        return 'no_af3'

    _mkdir(AF3_NODES)
    changed = False
    for filename, data in FILES.items():
        changed = _write_if_changed(filename, data) or changed

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
    if changed:
        return 'patched'
    return 'already_patched'
