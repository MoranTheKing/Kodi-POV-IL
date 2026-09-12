"""Kodi directory API, one explicitly requested catalog page, no scraping at startup."""
import json
from .engine import normalize,identity
from urllib.parse import urlencode

POPULAR_MOVIES='plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular'
POPULAR_TV='plugin://plugin.video.pov/?mode=build_tvshow_list&action=tmdb_tv_popular'


def fetch(execute, kind='movie', anchor=None):
    path=POPULAR_MOVIES if kind=='movie' else POPULAR_TV
    if anchor:
        identity(anchor['kind'],anchor['tmdb'])
        path='plugin://plugin.video.pov/?'+urlencode(dict(
            mode='build_movie_list' if anchor['kind']=='movie' else 'build_tvshow_list',
            action='tmdb_movies_recommendations' if anchor['kind']=='movie' else 'tmdb_tv_recommendations',
            tmdb_id=anchor['tmdb']))
    request=dict(jsonrpc='2.0',id=1,method='Files.GetDirectory',params=dict(
        directory=path,media='video',properties=['title','year','genre','plot','runtime','rating','art']))
    reply=json.loads(execute(json.dumps(request)))
    if 'error' in reply:raise ValueError('POV catalog unavailable')
    rows=reply.get('result',{}).get('files')
    if not isinstance(rows,list):raise ValueError('Invalid catalog response')
    items=[]
    for row in rows[:100]:
        if not isinstance(row,dict):continue
        item=normalize(row)
        if item:
            if anchor:item['recommended_from']=[anchor['key']]
            items.append(item)
    return items


def merge(items):
    combined={}
    for item in items:
        key=item['key']
        if key not in combined:combined[key]=dict(item)
        else:combined[key]['recommended_from']=sorted(set(combined[key].get('recommended_from',[]))|set(item.get('recommended_from',[])))
    return list(combined.values())
