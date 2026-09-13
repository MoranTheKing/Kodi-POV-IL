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


def plan(state, seed_keys, provider, preferred=None):
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
    old = state.get('discovery', {}).get(provider, {})
    signature = [a['key'] for a in anchors]
    cursor = old.get('cursor', 0) if old.get('anchors') == signature else 0
    if explicit_preferred or type(cursor) is not int or cursor < 0:
        cursor = 0
    cursor = cursor % len(anchors) if anchors else 0
    popular = [k for k in old.get('popular', []) if k in ('movie', 'tvshow')]
    missing = [k for k in ('movie', 'tvshow') if k not in popular]
    queries = []
    count = min(len(anchors), 2 if missing else 4)
    for offset in range(count):
        anchor = anchors[(cursor + offset) % len(anchors)]
        queries.append(dict(kind=anchor['kind'], anchor=anchor, offset=offset))
    for kind in missing if missing else ([] if anchors else ['movie', 'tvshow']):
        queries.append(dict(kind=kind, anchor=None))
    return dict(provider=provider, queries=queries[:4], anchors=signature,
                cursor=cursor, popular=popular, initial=bool(missing))


def advance(planned, completed_indices):
    cursor = planned['cursor']
    popular = list(planned['popular'])
    for index in sorted(set(completed_indices)):
        query = planned['queries'][index]
        if query['anchor']:
            cursor = (planned['cursor'] + query['offset'] + 1) % len(planned['anchors'])
        elif query['kind'] not in popular:
            popular.append(query['kind'])
    return dict(anchors=list(planned['anchors']), cursor=cursor, popular=popular)
