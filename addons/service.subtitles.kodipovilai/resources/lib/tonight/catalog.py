"""Kodi directory API, one explicitly requested catalog page, no scraping at startup."""
import json
from .engine import normalize,identity
from urllib.parse import parse_qs,urlparse
from . import providers

POPULAR_MOVIES='plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular'
POPULAR_TV='plugin://plugin.video.pov/?mode=build_tvshow_list&action=tmdb_tv_popular'
PERSONAL_LABELS=('MDBList','Trakt')


def personal_sources(item):
    """Normalize new multi-source state and legacy single-source caches."""
    values=item.get('personal_sources',[])
    if not isinstance(values,list):values=[]
    legacy=item.get('personal_source','')
    return [label for label in PERSONAL_LABELS
            if label in values or label==legacy]


def with_personal_sources(item, values):
    item=dict(item);values=[label for label in PERSONAL_LABELS if label in values]
    if values:
        item['personal_sources']=values;item['personal_source']=' / '.join(values)
    else:
        item.pop('personal_sources',None);item.pop('personal_source',None)
    return item


def _pagination_row(row, provider):
    try:
        route=urlparse(row.get('file',''))
        if route.scheme!='plugin' or route.netloc!='plugin.video.'+provider:return False
        values=parse_qs(route.query)
        return ('new_page' in values or 'page' in values or
                any('page=' in value for value in values.get('url',[])))
    except (AttributeError,ValueError):return False


def fetch(execute, kind='movie', anchor=None, provider='pov', query=None, personal=None,
          _status=None):
    if anchor:kind=anchor['kind']
    if (sum(x is not None for x in (query,personal))>1 or
            (query is not None and anchor) or (personal is not None and anchor)):
        raise ValueError('Catalog surfaces cannot be combined')
    path=(providers.search_route(provider,kind,query) if query is not None else
          providers.personal_route(provider,kind,personal) if personal is not None else
          providers.catalog_route(provider,kind,anchor))
    if path is None:return []
    request=dict(jsonrpc='2.0',id=1,method='Files.GetDirectory',params=dict(
        directory=path,media='video',properties=['title','originaltitle','year','premiered','genre','plot','runtime','rating','art','uniqueid','imdbnumber','playcount','director','writer','cast','tag','studio']))
    reply=json.loads(execute(json.dumps(request)))
    if not isinstance(reply,dict) or 'error' in reply:raise ValueError('Provider catalog unavailable')
    rows=reply.get('result',{}).get('files')
    if not isinstance(rows,list):raise ValueError('Invalid catalog response')
    if _status is not None:
        # Clearing old list membership is safe only when this response is the
        # whole surface. A first page can add evidence but cannot prove that a
        # previous item was removed rather than shifted to a later page.
        _status['complete']=len(rows)<100 and not any(
            _pagination_row(row,provider) for row in rows if isinstance(row,dict))
    items=[]
    for row in rows[:100]:
        if not isinstance(row,dict):continue
        item=normalize(row)
        if item and item['provider']==provider:
            if anchor:item['recommended_from']=[anchor['key']]
            if personal:
                label='MDBList' if personal=='mdblist' else 'Trakt'
                item=with_personal_sources(item,[label])
            items.append(item)
    return items


def merge(items):
    combined={}
    for item in items:
        key=item['key']
        if key not in combined:
            combined[key]=with_personal_sources(item,personal_sources(item))
        else:
            combined[key]['recommended_from']=sorted(set(combined[key].get('recommended_from',[]))|set(item.get('recommended_from',[])))
            sources=set(personal_sources(combined[key]))|set(personal_sources(item))
            combined[key]=with_personal_sources(combined[key],sources)
    return list(combined.values())


def collect(execute, planned, existing=(), cancelled=None, clock=None, progress=None):
    """Run at most four staged provider queries, retaining useful partial data.

    This is a worker function: Kodi's synchronous RPC cannot be interrupted.
    The caller must retain its 20-second UI deadline and exclusive worker lock.
    Cancellation/deadline is checked before each request and before publishing
    late results; progress snapshots let that UI retain completed earlier work.
    Extended-property failures are not retried, preserving the four-RPC cap.
    """
    import copy
    import time
    from . import discovery
    clock = clock or time.monotonic
    cancelled = cancelled or (lambda: False)
    provider = planned['provider']
    if provider not in ('pov', 'umbrella') or len(planned['queries']) > 4:
        raise ValueError('Invalid discovery plan')
    deadline = clock() + 20
    items = merge([x for x in existing if x.get('provider') == provider])[:2000]
    completed = []
    errors = 0
    def snapshot(stopped=False, timed_out=False):
        return copy.deepcopy(dict(items=items, discovery=discovery.advance(planned, completed),
                    completed=len(completed), errors=errors, cancelled=stopped,
                    timed_out=timed_out, provider=provider))
    for index, query in enumerate(planned['queries']):
        if cancelled():
            return snapshot(stopped=True)
        if clock() >= deadline:
            return snapshot(timed_out=True)
        try:
            if query.get('personal'):
                fetch_status={}
                fresh = fetch(execute, query['kind'], provider=provider,
                              personal=query['personal'],_status=fetch_status)
            else:
                fresh = fetch(execute, query['kind'], query.get('anchor'), provider)
        except Exception:
            errors += 1
            continue
        if cancelled():
            return snapshot(stopped=True)
        if clock() >= deadline:
            return snapshot(timed_out=True)
        if query.get('personal') and fetch_status.get('complete'):
            # A successfully read personal list is authoritative for its own
            # label/kind. Removed entries stay usable as ordinary catalog rows,
            # but must stop claiming they are still in the user's list.
            label='MDBList' if query['personal']=='mdblist' else 'Trakt'
            cleaned=[]
            for old in items:
                if label in personal_sources(old) and old['kind']==query['kind']:
                    old=with_personal_sources(old,
                        [source for source in personal_sources(old) if source!=label])
                cleaned.append(old)
            items=cleaned
        items = merge(fresh + items)[:2000]
        completed.append(index)
        if progress:
            progress(snapshot())
    return snapshot()
