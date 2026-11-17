"""The skins' player buttons: settings, change source, episode lists."""
import json
import re
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui

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


SUBS_STEP, SUBS_MAX = 2.0, 30.0


def _setting(name, value=None):
    request = {'jsonrpc': '2.0', 'id': 1,
               'method': 'Settings.GetSettingValue' if value is None else 'Settings.SetSettingValue',
               'params': {'setting': name} if value is None else {'setting': name, 'value': value}}
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(request))).get('result')
    return reply.get('value') if value is None and isinstance(reply, dict) else reply


def subtitles_position(step):
    """One step up or down for the subtitles, from the player's buttons.

    Kodi places subtitles by Settings > Player > Subtitles: a position (bottom
    or top, of the screen or of the picture) and a vertical margin in percent.
    A wide film on a 16:9 screen has black bars, and with "bottom of the
    screen" two lines fall half on the picture and half on the bar. A step
    changes the margin by two percent -- away from the edge the position is
    tied to, or back toward it -- so "up" always moves the text up the
    screen; with the Manual position it is Kodi's own shift instead. Kodi
    applies it at once and keeps it for every video. Returns the new margin,
    or None when nothing was changed."""
    if step not in ('up', 'down'):
        return None
    try:
        align = int(_setting('subtitles.align'))
        if align == 0:
            for _ in range(4):
                xbmc.executebuiltin('Action(SubtitleShift%s)' % ('Up' if step == 'up' else 'Down'))
            return None
        margin = float(_setting('subtitles.marginvertical') or 0)
        away = (step == 'up') != (align in (3, 4))        # top positions grow downward
        target = round(min(SUBS_MAX, max(0.0, margin + (SUBS_STEP if away else -SUBS_STEP))), 1)
        if target == margin or _setting('subtitles.marginvertical', target) is not True:
            return None
        return target
    except Exception as exc:
        xbmc.log('[POV IL player] subtitles position: {0!r}'.format(exc), xbmc.LOGWARNING)
        return None


def episodes():
    provider = xbmcaddon.Addon('service.subtitles.kodipovilai').getSetting('search_provider')
    if provider == 'umbrella' and xbmc.getCondVisibility('System.HasAddon(plugin.video.umbrella)'):
        path = 'plugin://plugin.video.umbrella/?action=shows_progress'
    else:
        path = 'plugin://plugin.video.pov/?mode=build_next_episode&name=32483&iconImage=next_episodes'
    xbmc.executebuiltin('ActivateWindow(videos,{0},return)'.format(path))


_IDANPLUS = 'plugin.video.idanplus'


def _idanplus_watch_store():
    """Idan Plus's own watch_store (pure Python, no Kodi imports): its saved
    seasons and the plugin url that plays a saved episode -- the same url its
    Continue watching and next-episode card play."""
    import importlib.util
    import xbmcvfs
    path = xbmcvfs.translatePath(
        'special://home/addons/{0}/resources/lib/watch_store.py'.format(_IDANPLUS))
    spec = importlib.util.spec_from_file_location('povil_idanplus_watch_store', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _season_label(entry, current):
    number = entry.get('number')
    label = '{0}. {1}'.format(number, entry.get('name', '')) if number not in (None, '') else entry.get('name', '')
    return '[B]{0}[/B]'.format(label) if current else label


def season_episodes(handle):
    """The skins' 'פרקי העונה' list for an Idan Plus episode on screen: its
    season as Idan Plus saved it when the season was listed (seasons.json), so
    no request. Israeli VOD has no TMDb id, and POV -- the list's source for
    every other episode -- failed on it. Empty when nothing from Idan Plus is
    playing or its season was never listed."""
    import xbmcplugin
    items = []
    try:
        key = xbmc.Player().getPlayingItem().getProperty('idanplus_key')
    except Exception:
        key = ''
    if key:
        try:
            import xbmcvfs
            store = _idanplus_watch_store()
            folder = xbmcvfs.translatePath(
                'special://profile/addon_data/{0}/watch'.format(_IDANPLUS))
            seasons = store.SeasonIndex(folder).load()
            here = store.episode_entry(seasons, key)
            if here:
                module = key.split(':')[0]
                # what Idan Plus's own player service passes: the channel's
                # quality, 'best' when unset (common.GetAddonSetting) -- Kan and
                # Reshet fail on an empty one
                quality = xbmcaddon.Addon(_IDANPLUS).getSetting('{0}_res'.format(module)) or 'best'
                meta = getattr(store, 'EpisodeMeta', None)
                facts = meta(folder).load() if meta else {}
                season = seasons[here['season_url']]
                # the season number the player shows (the saved season's title
                # often has none)
                season_no = xbmc.getInfoLabel('VideoPlayer.Season')
                for k in season.get('order', []):
                    entry = store.episode_entry(seasons, k)
                    if not entry:
                        continue
                    item = xbmcgui.ListItem(_season_label(entry, k == key), offscreen=True)
                    icon = entry.get('icon', '')
                    item.setArt({'thumb': icon, 'icon': icon, 'fanart': icon, 'landscape': icon})
                    tag = item.getVideoInfoTag()
                    tag.setMediaType('episode')
                    tag.setTitle(entry.get('name', ''))
                    tag.setTvShowTitle(entry.get('series_title', ''))
                    if str(entry.get('number', '')).isdigit():
                        tag.setEpisode(int(entry['number']))
                    if season_no.isdigit():
                        tag.setSeason(int(season_no))
                    fact = facts.get(k) or {}
                    if fact.get('plot'):
                        tag.setPlot(fact['plot'])
                    aired = fact.get('aired') or entry.get('aired', '')
                    if aired:
                        tag.setFirstAired(aired)
                    # Idan Plus keeps its own resume point (noResume): no Kodi
                    # "resume from" menu over it
                    tag.setResumePoint(0.0, 1.0)
                    item.setProperty('IsPlayable', 'true')
                    items.append((store.play_url(_IDANPLUS, entry, quality), item, False))
        except Exception as e:
            xbmc.log('[player_styles] season_episodes: {0}'.format(e), xbmc.LOGWARNING)
            items = []
    if handle >= 0:
        xbmcplugin.setContent(handle, 'episodes')
        if items:
            xbmcplugin.addDirectoryItems(handle, items, len(items))
        xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
