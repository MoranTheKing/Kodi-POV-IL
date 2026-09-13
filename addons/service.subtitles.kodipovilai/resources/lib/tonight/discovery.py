"""Pure, bounded discovery planning. Viewing is a weak signal, not a like."""
from .engine import identity


def _anchor(key):
    try:
        kind, tmdb = key.split(':', 1)
        return dict(key=identity(kind, tmdb), kind=kind, tmdb=tmdb)
    except (AttributeError, ValueError):
        return None


def _diverse(keys):
    groups = {'movie': [], 'tvshow': []}
    for key in dict.fromkeys(keys):
        anchor = _anchor(key)
        if anchor:
            groups[anchor['kind']].append(anchor)
    result = []
    while any(groups.values()):
        for kind in ('movie', 'tvshow'):
            if groups[kind]:
                result.append(groups[kind].pop(0))
    return result


def plan(state, seed_keys, provider, preferred=None, personal_sources=(), refresh_personal=False):
    if provider not in ('pov', 'umbrella'):
        raise ValueError('Unsupported provider')
    profiles = [state['profiles'][v] for v in state['viewers']]
    disliked = {k for p in profiles for k, f in p.get('feedback', {}).items()
                if f.get('value', 0) < 0}
    liked = [k for p in profiles for k, f in p.get('feedback', {}).items()
             if f.get('value', 0) > 0 and k not in disliked]
    explicit_preferred = preferred
    preferred = preferred or state.get('session', {}).get('anchor')
    if preferred and preferred not in disliked and _anchor(preferred):
        liked = [preferred] + [k for k in liked if k != preferred]
    likes = _diverse(liked)
    if preferred:
        likes.sort(key=lambda a: a['key'] != preferred)
    history = _diverse([k for k in seed_keys if k not in disliked and k not in liked]
                       if 'household' in state['viewers'] else [])
    # Preserve explicit preferences while reserving breadth for viewing history.
    anchors = likes[:4] + history[:4]
    used = {a['key'] for a in anchors}
    anchors += [a for a in likes[4:] + history[4:] if a['key'] not in used][:8-len(anchors)]
    anchors = anchors[:8]
    sources=[x for x in dict.fromkeys(personal_sources) if x in ('mdblist','trakt')]
    old = state.get('discovery', {}).get(provider, {})
    signature = [a['key'] for a in anchors]
    cursor = old.get('cursor', 0) if old.get('anchors') == signature else 0
    if explicit_preferred or type(cursor) is not int or cursor < 0:
        cursor = 0
    cursor = cursor % len(anchors) if anchors else 0
    popular = [k for k in old.get('popular', []) if k in ('movie', 'tvshow')]
    same_sources=old.get('sources',[])==sources
    personal_done=[x for x in old.get('personal',[]) if x in
                   {source+':'+kind for source in sources for kind in ('movie','tvshow')}]
    if not same_sources:personal_done=[]
    personal_cursor=old.get('personal_cursor',0) if same_sources else 0
    if type(personal_cursor) is not int or personal_cursor<0:personal_cursor=0
    personal_cursor=personal_cursor%len(sources) if sources else 0
    refresh_source=sources[personal_cursor] if refresh_personal and sources else ''
    if refresh_source:
        personal_missing=[(refresh_source,kind) for kind in ('movie','tvshow')]
    else:
        personal_missing=[(source,kind) for source in sources for kind in ('movie','tvshow')
                          if source+':'+kind not in personal_done]
    missing = [k for k in ('movie', 'tvshow') if k not in popular]
    has_catalog=any(item.get('provider','pov')==provider for item in state.get('catalog',[]))
    # Existing users already have fallback candidates, so their first upgraded
    # visit can read both connected services in one bounded four-query pass.
    # A truly empty catalog still reserves two queries for popular fallbacks.
    personal_limit=4 if has_catalog and not refresh_personal else 2
    queries = [dict(kind=kind,anchor=None,personal=source)
               for source,kind in personal_missing[:personal_limit]]
    count = min(len(anchors), max(0,(2 if missing else 4)-len(queries)))
    for offset in range(count):
        anchor = anchors[(cursor + offset) % len(anchors)]
        queries.append(dict(kind=anchor['kind'], anchor=anchor, offset=offset))
    for kind in missing if missing else ([] if anchors else ['movie', 'tvshow']):
        if len(queries)<4:queries.append(dict(kind=kind, anchor=None))
    return dict(provider=provider, queries=queries[:4], anchors=signature,
                cursor=cursor, popular=popular, personal=personal_done,
                sources=sources,personal_cursor=personal_cursor,
                refresh_source=refresh_source,
                initial=bool(missing or personal_missing))


def advance(planned, completed_indices):
    cursor = planned['cursor']
    popular = list(planned['popular'])
    personal=list(planned.get('personal',[]))
    sources=list(planned.get('sources',[]))
    for index in sorted(set(completed_indices)):
        query = planned['queries'][index]
        if query.get('personal'):
            key=query['personal']+':'+query['kind']
            if key not in personal:personal.append(key)
        elif query['anchor']:
            cursor = (planned['cursor'] + query['offset'] + 1) % len(planned['anchors'])
        elif query['kind'] not in popular:
            popular.append(query['kind'])
    personal_cursor=planned.get('personal_cursor',0)
    if planned.get('refresh_source') and sources:
        personal_cursor=(personal_cursor+1)%len(sources)
    return dict(anchors=list(planned['anchors']), cursor=cursor, popular=popular,
                personal=personal,sources=sources,personal_cursor=personal_cursor)
