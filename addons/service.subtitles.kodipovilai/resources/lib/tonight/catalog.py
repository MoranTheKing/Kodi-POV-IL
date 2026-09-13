"""Kodi directory API, one explicitly requested catalog page, no scraping at startup."""
import json
from .engine import normalize,identity
from urllib.parse import urlencode
from . import providers

POPULAR_MOVIES='plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular'
POPULAR_TV='plugin://plugin.video.pov/?mode=build_tvshow_list&action=tmdb_tv_popular'


def fetch(execute, kind='movie', anchor=None, provider='pov', query=None):
    if anchor:kind=anchor['kind']
    if query is not None and anchor:raise ValueError('Search cannot claim recommendation provenance')
    path=providers.search_route(provider,kind,query) if query is not None else providers.catalog_route(provider,kind,anchor)
    if path is None:return []
    request=dict(jsonrpc='2.0',id=1,method='Files.GetDirectory',params=dict(
        directory=path,media='video',properties=['title','originaltitle','year','genre','plot','runtime','rating','art','uniqueid','imdbnumber','playcount']))
    reply=json.loads(execute(json.dumps(request)))
    if not isinstance(reply,dict) or 'error' in reply:raise ValueError('Provider catalog unavailable')
    rows=reply.get('result',{}).get('files')
    if not isinstance(rows,list):raise ValueError('Invalid catalog response')
    items=[]
    for row in rows[:100]:
        if not isinstance(row,dict):continue
        item=normalize(row)
        if item and item['provider']==provider:
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
