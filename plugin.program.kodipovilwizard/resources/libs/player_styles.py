"""Nox player controls: local style selection, no skin reload during playback."""
import json
import re
import time
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui

STYLES = (
    ('__noxplayer', 'Nox המקורי'),
    ('__advancedplayer', 'מתקדם — מידע ושליטה מורחבת'),
    ('__netflixplayer', 'קולנועי — נקי ונוח'),
    ('__simpleplayer', 'פשוט — כפתורים גדולים'),
    ('__prettyplayer', 'מעוצב — שליטה קומפקטית'),
)


_STYLE_BUSY = 'POVIL.PlayerStyleBusy'


def _wait_closed(name, monitor):
    # Builtins are queued on Kodi's GUI thread. Returning from Dialog.Close
    # does not prove that its controls/close animation have finished.
    deadline = time.monotonic() + 2.0
    condition = 'Window.IsVisible({0}) | Window.IsActive({0})'.format(name)
    while xbmc.getCondVisibility(condition):
        if time.monotonic() >= deadline or monitor.waitForAbort(0.05):
            return False
    return not monitor.waitForAbort(0.15)


def choose():
    home = xbmcgui.Window(10000)
    if home.getProperty(_STYLE_BUSY):
        return
    home.setProperty(_STYLE_BUSY, 'true')
    try:
        monitor = xbmc.Monitor()
        current = xbmc.getInfoLabel('Skin.String(__chooseplayer)')
        selected = next((i for i, (key, _) in enumerate(STYLES) if key == current), 0)
        if xbmc.getCondVisibility('Window.IsVisible(videoosd)'):
            # Let Kodi finish the close animation and release GUI controls on
            # its render thread. Forced teardown can race an OSD button click.
            xbmc.executebuiltin('Dialog.Close(videoosd)')
            if not _wait_closed('videoosd', monitor):
                return
        choice = xbmcgui.Dialog().select('בחר את עיצוב הנגן',
                                         [label for _, label in STYLES], preselect=selected)
        if (not _wait_closed('selectdialog', monitor) or
                choice < 0 or choice >= len(STYLES) or choice == selected):
            return
        xbmc.executebuiltin('Skin.SetString(__chooseplayer,{0})'.format(STYLES[choice][0]))
        # Leave the OSD closed. A fresh user activation creates the new
        # control set; never reopen it during the selector's native teardown.
        xbmcgui.Dialog().notification('עיצוב הנגן', STYLES[choice][1])
    finally:
        home.clearProperty(_STYLE_BUSY)


def settings():
    xbmc.executebuiltin('SetProperty(settingslist_content,osd,home)')
    xbmc.executebuiltin('SetProperty(settingslist_header,{0},home)'.format(xbmc.getLocalizedString(5)))
    xbmc.executebuiltin('ActivateWindow(1101)')


def change_source():
    """Route through the selected provider with current playing-item IDs."""
    episode = xbmc.getCondVisibility('VideoPlayer.Content(episodes)')
    tmdb = xbmc.getInfoLabel('VideoPlayer.UniqueID(tmdb)')
    if not re.fullmatch(r'[1-9][0-9]*', tmdb):
        xbmcgui.Dialog().notification('החלפת מקור', 'אין מזהה תוכן מתאים להחלפת מקור')
        return
    provider = xbmcaddon.Addon('service.subtitles.kodipovilai').getSetting('search_provider')
    provider = 'umbrella' if provider == 'umbrella' and xbmc.getCondVisibility(
        'System.HasAddon(plugin.video.umbrella)') else 'pov'
    if provider == 'pov':
        params = dict(mode='play_media', mediatype='episode' if episode else 'movie',
                      tmdb_id=tmdb, autoplay='false')
    else:
        title = xbmc.getInfoLabel('VideoPlayer.OriginalTitle') or xbmc.getInfoLabel('VideoPlayer.Title')
        meta = dict(title=title, originaltitle=title, tmdb=tmdb,
                    imdb=xbmc.getInfoLabel('VideoPlayer.IMDBNumber'),
                    year=xbmc.getInfoLabel('VideoPlayer.Year'),
                    mediatype='episode' if episode else 'movie')
        try:
            reply = json.loads(xbmc.executeJSONRPC(json.dumps(dict(jsonrpc='2.0', id=1,
                method='Player.GetProperties', params=dict(playerid=1, properties=['totaltime'])))))
            total = reply.get('result', {}).get('totaltime', {})
            meta['duration'] = int(total.get('hours', 0)) * 3600 + int(total.get('minutes', 0)) * 60 + int(total.get('seconds', 0))
        except (AttributeError, ValueError, TypeError):
            pass
        if episode:
            meta.update(season=xbmc.getInfoLabel('VideoPlayer.Season'),
                        episode=xbmc.getInfoLabel('VideoPlayer.Episode'),
                        tvshowtitle=xbmc.getInfoLabel('VideoPlayer.TVShowTitle'))
        params = dict(action='play_Item', title=title, tmdb=tmdb,
                      imdb=meta['imdb'], year=meta['year'], select='0',
                      meta=json.dumps(meta, ensure_ascii=False))
    if episode:
        params.update(season=xbmc.getInfoLabel('VideoPlayer.Season'),
                      episode=xbmc.getInfoLabel('VideoPlayer.Episode'))
        if provider == 'umbrella':
            params['tvshowtitle'] = xbmc.getInfoLabel('VideoPlayer.TVShowTitle')
    if xbmc.getCondVisibility('Player.Playing'):
        xbmc.executebuiltin('PlayerControl(Play)')
    # Umbrella resolves a plugin media handle; RunPlugin supplies handle -1.
    action = 'PlayMedia' if provider == 'umbrella' else 'RunPlugin'
    xbmc.executebuiltin('{0}(plugin://plugin.video.{1}/?{2})'.format(action, provider, urlencode(params)))


def episodes():
    provider = xbmcaddon.Addon('service.subtitles.kodipovilai').getSetting('search_provider')
    if provider == 'umbrella' and xbmc.getCondVisibility('System.HasAddon(plugin.video.umbrella)'):
        path = 'plugin://plugin.video.umbrella/?action=shows_progress'
    else:
        path = 'plugin://plugin.video.pov/?mode=build_next_episode&name=32483&iconImage=next_episodes'
    xbmc.executebuiltin('ActivateWindow(videos,{0},return)'.format(path))
