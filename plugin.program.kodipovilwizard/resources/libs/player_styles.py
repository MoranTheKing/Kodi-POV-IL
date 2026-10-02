"""Nox player controls: local style selection, no skin reload during playback."""
import json
import re
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


def choose():
    current = xbmc.getInfoLabel('Skin.String(__chooseplayer)')
    selected = next((i for i, (key, _) in enumerate(STYLES) if key == current), 0)
    osd = xbmc.getCondVisibility('Window.IsVisible(videoosd)')
    if osd:
        xbmc.executebuiltin('Dialog.Close(videoosd,true)')
    choice = xbmcgui.Dialog().select('בחר את עיצוב הנגן',
                                     [label for _, label in STYLES], preselect=selected)
    if choice >= 0:
        xbmc.executebuiltin('Skin.SetString(__chooseplayer,{0})'.format(STYLES[choice][0]))
    if osd and xbmc.getCondVisibility('Player.HasVideo'):
        # Reopening only this dialog reevaluates its conditional includes.
        xbmc.executebuiltin('ActivateWindow(videoosd)')


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
