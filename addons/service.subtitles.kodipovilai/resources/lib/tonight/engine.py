"""Deterministic, explainable first-stage ranking; no model or network calls."""
import copy
import math
import re
import time
from urllib.parse import urlparse, parse_qs, urlencode


def identity(kind, tmdb):
    if kind not in ('movie', 'tvshow') or not re.fullmatch(r'[1-9][0-9]{0,11}', str(tmdb)):
        raise ValueError('Invalid media identity')
    return '%s:%s' % (kind, tmdb)


def provider_route(kind, tmdb):
    identity(kind, tmdb)
    params = dict(mode='play_media', mediatype='movie', tmdb_id=str(tmdb)) if kind == 'movie' else dict(mode='build_season_list', tmdb_id=str(tmdb))
    return 'plugin://plugin.video.pov/?' + urlencode(params)


def normalize(row):
    """Only trusted provider identities; never replay an arbitrary returned URL."""
    if not isinstance(row,dict) or not isinstance(row.get('file'),str):
        return None
    try:
        url = urlparse(row.get('file', ''))
    except ValueError:
        return None
    if url.scheme != 'plugin' or url.netloc != 'plugin.video.pov':
        return None
    query = parse_qs(url.query)
    if any(len(v) != 1 for v in query.values()):
        return None
    mode = query.get('mode', [''])[0]
    kind = 'tvshow' if mode == 'build_season_list' else query.get('mediatype', [''])[0]
    if mode not in ('play_media', 'extras_menu_choice', 'build_season_list'):
        return None
    tmdb = query.get('tmdb_id', [''])[0]
    try:
        key = identity(kind, tmdb)
        runtime = int(row.get('runtime') or 0)
        year = int(row.get('year') or 0)
        rating = float(row.get('rating') or 0)
    except (ValueError, TypeError, OverflowError):
        return None
    genres = row.get('genre') or []
    if not isinstance(genres, list):
        genres = [genres] if isinstance(genres, str) else []
    title = row.get('title') or row.get('label')
    if not isinstance(title, str) or not title.strip():
        return None
    art = row.get('art') or {}
    if not isinstance(art, dict):
        art = {}
    return dict(key=key, kind=kind, tmdb=tmdb, title=title[:300], year=year,
                runtime=runtime if 0 < runtime < 24*3600 else None,
                rating=max(0, min(10, rating)) if math.isfinite(rating) else 0,
                genres=sorted(set(g.strip()[:80] for g in genres if isinstance(g, str) and g.strip()))[:100],
                plot=str(row.get('plot') or '')[:6000],
                art={k:v for k,v in art.items() if k in ('poster','fanart','thumb') and isinstance(v,str)},
                availability='unknown')


def initial_state():
    return dict(version=1, profiles={'household':dict(name='הבית', feedback={}, seen=[], saved=[])},
                viewers=['household'], session=dict(minutes=0, excluded=[], started=time.time()), catalog=[])


def feedback(state, viewer, item, action):
    """Explicit item preference is distinct from watched state and tonight-only rejection."""
    state = copy.deepcopy(state)
    profile = state['profiles'][viewer]
    key = item['key']
    if action in ('like','dislike'):
        profile['feedback'][key] = dict(value=1 if action=='like' else -1, genres=item['genres'], title=item['title'])
    elif action == 'seen':
        profile['seen'] = sorted(set(profile['seen']) | {key})
    elif action == 'save':
        profile['saved'] = sorted(set(profile['saved']) | {key})
    elif action == 'not_tonight':
        state['session']['excluded'] = sorted(set(state['session']['excluded']) | {key})
    else:
        raise ValueError('Unknown feedback')
    return state


def rank(catalog, profiles, session, watched=()):
    """Hard exclusion then conservative genre inference; group score protects least satisfied viewer.

    Genres are the available first-stage evidence, NOT an implemented fine-grained taste model.
    """
    excluded = set(session.get('excluded', [])) | set(watched)
    for p in profiles:
        excluded.update(p.get('seen', []))
        excluded.update(k for k,v in p.get('feedback',{}).items() if v['value']<0)
    minutes = session.get('minutes', 0)
    candidates = []
    used = set()
    for item in catalog:
        if item['key'] in excluded or item['key'] in used:
            continue
        used.add(item['key'])
        # A TV series duration does not establish the next episode length.
        if minutes and (item['kind'] != 'movie' or not item['runtime'] or item['runtime'] > minutes*60):
            continue
        scores, reasons = [], []
        for p in profiles:
            pos, neg = [], []
            for f in p.get('feedback', {}).values():
                common = set(item['genres']) & set(f['genres'])
                if common:
                    (pos if f['value']>0 else neg).append(f)
            score = min(3,len(pos)) - min(3,len(neg))
            anchors=[p.get('feedback',{}).get(k) for k in item.get('recommended_from',[])]
            anchors=[a for a in anchors if a and a['value']>0]
            if anchors:
                score+=2
                reasons.append('מומלץ בקטלוג בעקבות %s שסימנת באהבתי' % anchors[0]['title'])
            scores.append(score)
            if pos and score>0:
                reasons.append('קשר ז׳אנרי ל־%s שסימנת באהבתי — זו הערכה ראשונית' % pos[0]['title'])
        # No popular rating can override explicit dislike or watch/time exclusions.
        score = 2*min(scores or [0]) + sum(scores)/max(1,len(scores)) + item['rating']/10
        if not reasons:
            reasons.append('עדיין לומדים את הטעם; זו הצעה מהקטלוג, לא התאמה עמוקה')
        if minutes:
            reasons.append('משך הקטלוג מתאים לזמן שבחרת')
        candidates.append(dict(item=item, score=score, reasons=list(dict.fromkeys(reasons))))
    return sorted(candidates, key=lambda r:(-r['score'],r['item']['key']))


def choose_three(ranked):
    """Keep a stable first choice, diversify subsequent choices without breaking hard filters."""
    remaining=list(ranked);selected=[]
    while remaining and len(selected)<3:
        def value(r):
            a=set(r['item']['genres'])
            overlap=max([len(a & set(s['item']['genres']))/max(1,len(a | set(s['item']['genres']))) for s in selected] or [0])
            return r['score'] - .5*overlap
        best=max(remaining,key=value);remaining.remove(best);selected.append(best)
    return selected
