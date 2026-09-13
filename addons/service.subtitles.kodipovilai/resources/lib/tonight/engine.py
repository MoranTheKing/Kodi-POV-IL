"""Deterministic, explainable first-stage ranking; no model or network calls."""
import copy
import math
import re
import time
from . import taste
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
    if url.scheme != 'plugin' or url.netloc not in ('plugin.video.pov','plugin.video.umbrella'):
        return None
    query = parse_qs(url.query)
    if any(len(v) != 1 for v in query.values()):
        return None
    provider='umbrella' if url.netloc.endswith('.umbrella') else 'pov'
    if provider=='pov':
        mode = query.get('mode', [''])[0]
        kind = 'tvshow' if mode == 'build_season_list' else query.get('mediatype', [''])[0]
        if mode not in ('play_media', 'extras_menu_choice', 'build_season_list'):return None
        tmdb=query.get('tmdb_id',[''])[0]
    else:
        action=query.get('action',[''])[0]
        if action not in ('play_Item','seasons'):return None
        kind='movie' if action=='play_Item' else 'tvshow';tmdb=query.get('tmdb',[''])[0]
        if any(query.get(k,[''])[0] not in ('','None') for k in ('episode','season')):return None
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
    unique=row.get('uniqueid',{})
    if not isinstance(unique,dict):unique={}
    imdb=query.get('imdb',[''])[0] or unique.get('imdb') or row.get('imdbnumber') or ''
    tvdb=query.get('tvdb',[''])[0] or unique.get('tvdb') or ''
    imdb=str(imdb);tvdb=str(tvdb)
    original=query.get('title',query.get('tvshowtitle',['']))[0] or row.get('originaltitle') or title
    if not isinstance(original,str):original=title
    return dict(key=key, kind=kind, tmdb=tmdb, title=title[:300], year=year,provider=provider,traits=taste.metadata(row),
                originaltitle=original[:300],imdb=imdb if re.fullmatch(r'tt[0-9]{5,12}',imdb) else '',tvdb=tvdb if re.fullmatch(r'[1-9][0-9]{0,11}',tvdb) else '',
                watched=type(row.get('playcount')) is int and row['playcount']>0,
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
        profile['feedback'][key] = dict(value=1 if action=='like' else -1, genres=item['genres'], title=item['title'],traits=copy.deepcopy(item.get('traits',{})))
    elif action == 'seen':
        profile['seen'] = sorted(set(profile['seen']) | {key})
    elif action == 'save':
        profile['saved'] = sorted(set(profile['saved']) | {key})
    elif action == 'unsave':
        profile['saved'] = [k for k in profile['saved'] if k != key]
    elif action == 'clear_feedback':
        profile['feedback'].pop(key,None)
    elif action == 'unseen':
        profile['seen'] = [k for k in profile['seen'] if k != key]
    elif action == 'not_tonight':
        state['session']['excluded'] = sorted(set(state['session']['excluded']) | {key})
    else:
        raise ValueError('Unknown feedback')
    return state


def refine(state,item,choice):
    if choice not in ('shorter','similar','different','lighter','less_familiar'):
        raise ValueError('Unknown refinement')
    state=copy.deepcopy(state);session=state['session']
    session['excluded']=sorted(set(session.get('excluded',[]))|{item['key']})
    if choice!='shorter':
        for key in ('anchor','anchor_genres','avoid_genres','discovery_mode','avoid_creators'):
            session.pop(key,None)
    if choice=='shorter':
        if item['kind']!='movie' or not item['runtime']:raise ValueError('No verified duration')
        session['max_runtime']=max(1,item['runtime']-1)
    elif choice=='similar':
        session['anchor']=item['key'];session['anchor_genres']=item['genres']
        session.pop('avoid_genres',None)
    elif choice=='different':
        session['avoid_genres']=item['genres'];session.pop('anchor',None);session.pop('anchor_genres',None)
    elif choice=='lighter':
        session['discovery_mode']='lighter'
    elif choice=='less_familiar':
        session['discovery_mode']='less_familiar'
        session['avoid_creators']=list(item.get('traits',{}).get('directors',[]))[:12]
    return state


def history_anchors(state, seed_keys, limit=2):
    """Sample shared viewing evidence; watching is never recorded as liking."""
    if 'household' not in state['viewers'] or limit <= 0:
        return []
    disliked = {k for viewer in state['viewers']
                for k, f in state['profiles'][viewer].get('feedback', {}).items()
                if f['value'] < 0}
    groups = {'movie': [], 'tvshow': []}
    seen = set()
    for key in seed_keys:
        if not isinstance(key, str) or key in seen or key in disliked:
            continue
        try:
            kind, tmdb = key.split(':', 1)
            identity(kind, tmdb)
        except ValueError:
            continue
        seen.add(key)
        groups[kind].append(dict(key=key, kind=kind, tmdb=tmdb))
    result = []
    # One movie and one series when both exist; input order is reader recency.
    while len(result) < min(limit, 2) and any(groups.values()):
        for kind in ('movie', 'tvshow'):
            if groups[kind] and len(result) < min(limit, 2):
                result.append(groups[kind].pop(0))
    return result


def rank(catalog, profiles, session, watched=(), history_seeds=(), history_strengths=None):
    """Rank with explicit choices plus weak, repeated household evidence."""
    excluded = set(session.get('excluded', [])) | set(watched)
    disliked_evidence=set();positive_keys=set()
    for p in profiles:
        excluded.update(p.get('seen', []))
        disliked={k for k,v in p.get('feedback',{}).items() if v['value']<0}
        disliked_evidence.update(disliked);excluded.update(disliked)
        positive_keys.update(k for k,v in p.get('feedback',{}).items() if v['value']>0)
    minutes = session.get('minutes', 0)
    cap=min(minutes*60 if minutes else 86400,session.get('max_runtime',86400))
    history_seeds=list(dict.fromkeys(history_seeds))
    history_set=set(history_seeds);history_order={key:index for index,key in enumerate(history_seeds)}
    history_strengths=history_strengths if isinstance(history_strengths,dict) else {}
    automatic=taste.implicit_profile(
        [item for item in catalog if item.get('key') not in disliked_evidence],
        history_seeds,history_strengths)
    candidates = []
    used = set()
    for item in catalog:
        if session.get('kind','all') not in ('all',item['kind']):
            continue
        if item['key'] in excluded or item['key'] in used:
            continue
        used.add(item['key'])
        # A TV series duration does not establish the next episode length.
        if cap<86400 and (item['kind'] != 'movie' or not item['runtime'] or item['runtime'] > cap):
            continue
        scores, reasons = [], []
        explicit_origins=[]
        for p in profiles:
            pos, neg = [], []
            for f in p.get('feedback', {}).values():
                common = taste.genres(item['genres']) & taste.genres(f['genres'])
                if common:
                    (pos if f['value']>0 else neg).append(f)
            # One explicit title should help, but must not define every card.
            score = .65*min(2,len(pos)) - .8*min(2,len(neg))
            anchors=[p.get('feedback',{}).get(k) for k in item.get('recommended_from',[])]
            anchors=[a for a in anchors if a and a['value']>0]
            if anchors:
                score+=1.35
                explicit_origins.extend(k for k in item.get('recommended_from',[])
                                        if p.get('feedback',{}).get(k,{}).get('value')==1)
                reasons.append('מומלץ בקטלוג בעקבות %s שסימנת באהבתי' % anchors[0]['title'])
            metadata_score,metadata_reasons=taste.affinity(item,p.get('feedback',{}))
            score+=.65*metadata_score
            reasons.extend(metadata_reasons)
            # With only one positive example, genre/creator resemblance is the
            # same fragile origin as direct recommendation provenance.  Mark it
            # so shelf diversity can cap the whole influence, not just routes.
            if len(positive_keys)==1 and (pos or anchors or metadata_score>0):
                explicit_origins.extend(positive_keys)
            scores.append(score)
            if pos and score>0:
                reasons.append('קשר ז׳אנרי ל־%s שסימנת באהבתי — זו הערכה ראשונית' % pos[0]['title'])
        # No popular rating can override explicit dislike or watch/time exclusions.
        score = 1.25*min(scores or [0]) + sum(scores)/max(1,len(scores)) + item['rating']/10
        history_origins=[key for key in item.get('recommended_from',[]) if key in history_set]
        if history_origins:
            # Several independent watched anchors are stronger than one, while
            # every single view remains much weaker than an explicit like.
            ordered=sorted(set(history_origins),key=lambda key:history_order[key])
            recency=sum(1.0/(1.0+history_order[key]/8.0) for key in ordered)/len(ordered)
            repeat_support=sum(min(5,taste.repeat_strength(history_strengths.get(key)))-1
                               for key in ordered)
            score+=min(1.25,.45+.18*(len(ordered)-1)+.15*recency+.04*repeat_support)
            reasons.append('כמה כותרים מהיסטוריית הצפייה הובילו לכיוון הזה' if len(ordered)>1
                           else 'בהשראת כותר מהיסטוריית הצפייה בבית')
        implicit_score,implicit_reasons=taste.implicit_affinity(item,automatic)
        score+=implicit_score;reasons.extend(implicit_reasons)
        if session.get('anchor') in item.get('recommended_from',[]):
            score+=2;reasons.append('המלצת קטלוג בעקבות הכותר שבחרת לדייק ממנו הערב')
        elif taste.genres(item['genres']) & taste.genres(session.get('anchor_genres',[])):
            score+=.5;reasons.append('קשר ז׳אנרי לכותר שבחרת לדייק ממנו הערב')
        if taste.genres(item['genres']) & taste.genres(session.get('avoid_genres',[])):
            score-=2
        mood_score,mood_reasons=taste.refinement(item,session)
        score+=mood_score;reasons.extend(mood_reasons)
        mode_fit=taste.vibe_fit(item,session.get('vibe',''))
        if session.get('vibe')=='surprise':
            novelty=[taste.surprise(item,p.get('feedback',{}),automatic) for p in profiles]
            if novelty:
                score+=sum(x[0] for x in novelty)/len(novelty)
                reasons.extend(r for x in novelty for r in x[1])
                mode_fit=1 if any(x[0]>0 for x in novelty) else (-1 if any(x[0]<0 for x in novelty) else 0)
        if not reasons:
            reasons.append('עדיין לומדים את הטעם; זו הצעה מהקטלוג, לא התאמה עמוקה')
        if cap<86400:
            reasons.append('משך הקטלוג מתאים לזמן שבחרת')
        personal_label=(item.get('personal_source') or
                        ' / '.join(item.get('personal_sources',[])))
        personal=bool(personal_label)
        if personal:
            score+=.75
            reasons.append('ברשימת הצפייה האישית שלך ב־%s' % personal_label)
        candidates.append(dict(item=item, score=score, reasons=list(dict.fromkeys(reasons)),
            saved=personal or any(item['key'] in p.get('saved',[]) for p in profiles),
            explicit_origins=list(dict.fromkeys(explicit_origins)),
            history_origins=list(dict.fromkeys(history_origins)),mode_fit=mode_fit))
    vibe=session.get('vibe','')
    return sorted(candidates,key=lambda r:(-(r['mode_fit'] if vibe else 0),-r['score'],r['item']['key']))


def choose_shelf(ranked, limit=9):
    """Build a TV shelf with relevance, mode fit and origin diversity."""
    if not ranked or limit<=0:return []
    remaining=list(ranked);selected=[];origin_counts={}

    def overlap(a,b,field='genres'):
        left=taste.genres(a['item'].get(field,[]));right=taste.genres(b['item'].get(field,[]))
        return len(left&right)/max(1,len(left|right))

    def add(row,lane):
        remaining.remove(row)
        result=dict(row);result['lane']=lane
        result['reasons']=[lane]+list(row['reasons'])
        selected.append(result)
        for key in row.get('explicit_origins',[]):origin_counts[key]=origin_counts.get(key,0)+1

    def candidates_for_slot():
        pool=list(remaining)
        if not pool:return []
        cap=1 if len(selected)<3 else 2
        under_cap=[r for r in pool if all(origin_counts.get(key,0)<cap
                   for key in r.get('explicit_origins',[]))]
        if not under_cap and len(selected)==1:
            # A sparse brand-new catalog may contain only one like's route.
            # Keep a second useful option, then wait for automatic discovery
            # instead of presenting an entire shelf as learned taste.
            under_cap=[r for r in pool if all(origin_counts.get(key,0)<2
                       for key in r.get('explicit_origins',[]))]
        if not under_cap:return []
        # Among origins that are still allowed, exhaust real mode matches
        # before neutral fallbacks and keep known contradictions for last.
        best_fit=max(r.get('mode_fit',0) for r in under_cap)
        if best_fit>=0:
            under_cap=[r for r in under_cap if r.get('mode_fit',0)==best_fit]
        return under_cap

    def value(row):
        if not selected:return row['score']
        genre=max(overlap(row,old) for old in selected)
        provenance=max((bool(set(row.get('explicit_origins',[]))&set(old.get('explicit_origins',[])))
                        for old in selected),default=False)
        history=max((bool(set(row.get('history_origins',[]))&set(old.get('history_origins',[])))
                     for old in selected),default=False)
        return row['score']-.9*genre-1.25*provenance-.35*history

    first=remaining[0]
    learned=any(('אהבת' in reason or 'היסטוריית' in reason or 'דפוס שחוזר' in reason)
                for reason in first['reasons'])
    add(first,'קרוב לטעם שלך' if learned else 'בחירה מהקטלוג')

    if remaining and len(selected)<limit:
        pool=candidates_for_slot()
        if pool:
            pick=max(pool,key=lambda r:(value(r),-ranked.index(r)))
            different=(taste.genres(pick['item']['genres'])!=taste.genres(selected[0]['item']['genres']) or
                       pick['item'].get('traits',{}).get('directors',[])!=selected[0]['item'].get('traits',{}).get('directors',[]))
            add(pick,'כיוון קצת אחר' if different else 'עוד התאמה אפשרית')

    if remaining and len(selected)<limit:
        pool=candidates_for_slot()
        if pool:
            saved=[row for row in pool if row.get('saved')]
            pick=max(saved or pool,key=lambda r:(value(r),-ranked.index(r)))
            add(pick,'מהשמורים שלך' if pick.get('saved') else 'עוד אפשרות לערב')

    while remaining and len(selected)<limit:
        pool=candidates_for_slot()
        if not pool:break
        pick=max(pool,key=lambda r:(value(r),-ranked.index(r)))
        if pick.get('saved'):lane='מהשמורים שלך'
        elif pick.get('history_origins') or pick.get('explicit_origins'):lane='עוד התאמה בשבילך'
        else:lane='עוד כיוון לגלות'
        add(pick,lane)
    return selected


def choose_three(ranked):
    """Compatibility wrapper for the compact/legacy interface."""
    return choose_shelf(ranked,3)


def quick_pair(state,viewer,history_seeds=()):
    """Optional two-title feedback; only known viewing evidence, never forced ratings."""
    profile=state['profiles'][viewer]
    known=set(profile.get('seen',[]))
    if viewer=='household':known.update(history_seeds)
    chosen=[];seen=set()
    for item in state['catalog']:
        key=item['key']
        if key in seen or key not in known or key in profile.get('feedback',{}):continue
        seen.add(key);chosen.append(item)
        if len(chosen)==2:break
    return chosen


def checkpoint(state):
    """Undo user decisions only; never roll back the provider catalog/cache."""
    return copy.deepcopy({k:state[k] for k in ('profiles','viewers','session')})


def restore_checkpoint(state,snapshot):
    result=dict(state)
    result.update(copy.deepcopy(snapshot))
    return result
