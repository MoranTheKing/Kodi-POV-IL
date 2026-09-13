"""Follow the existing home-tile choice; never reuse another provider's URL."""
import json
import re
from urllib.parse import urlencode, quote_plus

NAMES={'pov':'POV','umbrella':'Umbrella'}


def search_route(provider,kind,query):
    from resources.lib import search_provider
    if provider not in NAMES or kind not in ('movie','tvshow'):
        raise ValueError('Invalid search target')
    if not isinstance(query,str) or not query.strip() or len(query)>200:
        raise ValueError('Invalid search query')
    prefix=search_provider.AF3_PREFIXES[provider]['Movies' if kind=='movie' else 'Tv']
    return prefix.replace('&amp;amp;','&')+quote_plus(query.strip())


def current():
    from resources.lib import search_provider
    return search_provider.current()


def fallback_notice():
    from resources.lib import search_provider
    if search_provider.stored()=='umbrella' and current()!='umbrella':
        return 'Umbrella אינו זמין; משתמשים כרגע ב־POV, בהתאם לבחירת הבילד.'
    return ''


def catalog_route(provider,kind,anchor=None):
    if provider not in NAMES or kind not in ('movie','tvshow'):raise ValueError('Unknown provider/media')
    if provider=='umbrella':
        params=dict(action='movies' if kind=='movie' else 'tvshows',url='tmdb_popular')
        if anchor:
            from .engine import identity
            identity(kind,anchor['tmdb'])
            # Umbrella substitutes its own key internally; this is only a template.
            media='movie' if kind=='movie' else 'tv'
            params['url']='https://api.themoviedb.org/3/%s/%s/recommendations?api_key=%%s&language=en-US&page=1' % (media,anchor['tmdb'])
    else:
        params=dict(mode='build_movie_list' if kind=='movie' else 'build_tvshow_list',action='tmdb_movies_popular' if kind=='movie' else 'tmdb_tv_popular')
        if anchor:
            from .engine import identity
            identity(anchor['kind'],anchor['tmdb'])
            params['action']='tmdb_movies_recommendations' if kind=='movie' else 'tmdb_tv_recommendations'
            params['tmdb_id']=anchor['tmdb']
    return 'plugin://plugin.video.'+provider+'/?'+urlencode(params)


def personal_route(provider,kind,source):
    """Read-only directory routes owned by the active provider."""
    if provider not in NAMES or kind not in ('movie','tvshow') or source not in ('mdblist','trakt'):
        raise ValueError('Unknown personal catalog')
    if provider=='pov':
        params=dict(mode='build_movie_list' if kind=='movie' else 'build_tvshow_list',
                    action='mdblist_watchlist' if source=='mdblist' else 'trakt_watchlist',
                    name=('MDBList Watchlist' if source=='mdblist' else 'Trakt Watchlist'))
    elif source=='mdblist':
        params=dict(action='mdbUserWatchListMovies' if kind=='movie' else 'mdbUserWatchListTVShows')
    else:
        params=dict(action='movies' if kind=='movie' else 'tvshows',url='traktwatchlist')
    return 'plugin://plugin.video.'+provider+'/?'+urlencode(params)


def playback_route(provider,item):
    from .engine import identity
    identity(item['kind'],item['tmdb'])
    if provider=='pov':
        params=dict(mode='play_media',mediatype='movie',tmdb_id=item['tmdb']) if item['kind']=='movie' else dict(mode='build_season_list',tmdb_id=item['tmdb'])
    elif provider=='umbrella':
        title=item.get('originaltitle') or item['title']
        imdb=item.get('imdb','');tvdb=item.get('tvdb','')
        if imdb and not re.fullmatch(r'tt[0-9]{5,12}',imdb):raise ValueError('Invalid IMDb ID')
        if tvdb and not re.fullmatch(r'[1-9][0-9]{0,11}',tvdb):raise ValueError('Invalid TVDB ID')
        params=dict(year=item['year'],imdb=imdb,tmdb=item['tmdb'])
        if item['kind']=='movie':
            meta=dict(title=title,originaltitle=title,year=item['year'],imdb=imdb,tmdb=item['tmdb'],mediatype='movie',duration=(item.get('runtime') or 0)//60)
            params.update(action='play_Item',title=title,meta=json.dumps(meta,ensure_ascii=False))
        else:
            # Umbrella Seasons.tmdb_list indexes these keys whenever art is
            # truthy; passing only Kodi's poster/fanart/thumb drops every season.
            supplied=item.get('art') or {}
            poster=supplied.get('poster','')
            art=dict(poster=poster,fanart=supplied.get('fanart',''),
                     thumb=supplied.get('thumb') or poster,icon=poster,
                     banner='',clearlogo='',clearart='')
            art['tvshow.poster']=poster
            params.update(action='seasons',tvshowtitle=title,tvdb=tvdb,art=json.dumps(art,ensure_ascii=False))
    else:raise ValueError('Unknown provider')
    return 'plugin://plugin.video.'+provider+'/?'+urlencode(params)


def trailer_route(provider,item):
    from .engine import identity
    identity(item['kind'],item['tmdb'])
    if provider=='umbrella':
        params=dict(action='play_Trailer_Select',type='movie' if item['kind']=='movie' else 'show',name=item.get('originaltitle') or item['title'],year=item['year'],windowedtrailer=0)
    elif provider=='pov':
        # POV owns trailer selection in its Extras dialog; no invented YouTube URLs.
        params=dict(mode='extras_menu_choice',mediatype=item['kind'],tmdb_id=item['tmdb'],is_widget='false')
    else:raise ValueError('Unknown provider')
    return 'plugin://plugin.video.'+provider+'/?'+urlencode(params)
