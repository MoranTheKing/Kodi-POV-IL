"""Evidence-based metadata taste signals; unknown attributes stay unknown."""
from collections import defaultdict
import re

def genres(values):
    """Kodi providers may return slash-joined genres, including in old caches."""
    if isinstance(values,str):values=[values]
    return {part.strip().casefold() for value in values if isinstance(value,str)
            for part in value.split('/') if part.strip()}

def names(value, limit=12):
    if isinstance(value, str):value=[value]
    if not isinstance(value,list):return []
    result=[]
    for x in value:
        if isinstance(x,dict):x=x.get('name','')
        if isinstance(x,str) and x.strip() and x.strip().casefold() not in {v.casefold() for v in result}:
            result.append(x.strip()[:120])
        if len(result)>=limit:break
    return result

def metadata(row):
    return {'directors':names(row.get('director')), 'writers':names(row.get('writer')),
            'cast':names(row.get('cast'),5), 'tags':names(row.get('tag'),20),
            'studios':names(row.get('studio'))}


def implicit_profile(catalog, history_seeds=(), history_strengths=None):
    """Learn repeated household patterns without turning one view into a like.

    A watched title is weak evidence and an item deliberately kept in a connected
    list is somewhat stronger.  A genre or creator only becomes a useful signal
    after it repeats across distinct titles, so one title can never define the
    automatic profile by itself.
    """
    order={key:index for index,key in enumerate(dict.fromkeys(history_seeds))
           if isinstance(key,str)}
    history_strengths=history_strengths or {}
    genre_weight=defaultdict(float);genre_titles=defaultdict(set)
    trait_weight={field:defaultdict(float) for field in
                  ('directors','writers','cast','tags','studios')}
    trait_titles={field:defaultdict(set) for field in trait_weight}
    evidence=set();processed=set();history_count=0;personal_count=0
    for item in catalog:
        key=item.get('key');weight=0.0
        if key in processed:continue
        processed.add(key)
        if key in order:
            # Input order is recency.  Older viewing remains useful, but less so.
            repeats=max(1,history_strengths.get(key,1))
            repeat_factor=1+min(.35,.08*max(0,repeats-1))
            weight=max(.28,.72-.018*min(order[key],24))*repeat_factor;history_count+=1
        elif item.get('watched'):
            weight=.38;history_count+=1
        if item.get('personal_source') or item.get('personal_sources'):
            weight+=.58;personal_count+=1
        if weight<=0 or not isinstance(key,str):continue
        evidence.add(key)
        for label in genres(item.get('genres',[])):
            genre_weight[label]+=weight;genre_titles[label].add(key)
        facts=item.get('traits',{})
        for field in trait_weight:
            for value in facts.get(field,[]):
                if isinstance(value,str) and value.strip():
                    folded=value.strip().casefold()
                    trait_weight[field][folded]+=weight
                    trait_titles[field][folded].add(key)
    # Repetition is the guardrail against a single watched or saved title taking
    # over the whole shelf.  Confidence stays bounded even for a large history.
    learned_genres={key:min(1.0,value/2.2) for key,value in genre_weight.items()
                    if len(genre_titles[key])>=2}
    learned_traits={}
    for field,values in trait_weight.items():
        learned_traits[field]={key:min(1.0,value/1.8) for key,value in values.items()
                               if len(trait_titles[field][key])>=2}
    return dict(genres=learned_genres,traits=learned_traits,
                evidence=len(evidence),history=history_count,personal=personal_count)


def implicit_affinity(item, profile):
    """Score only patterns supported by more than one household title."""
    if not profile or profile.get('evidence',0)<2:return 0,[]
    genre_scores=sorted((profile.get('genres',{}).get(label,0)
                         for label in genres(item.get('genres',[]))),reverse=True)
    score=sum(genre_scores[:2])*.55
    facts=item.get('traits',{});creator_score=0
    weights={'directors':.55,'writers':.4,'cast':.18,'tags':.28,'studios':.2}
    for field,weight in weights.items():
        known=profile.get('traits',{}).get(field,{})
        matches=sorted((known.get(value.casefold(),0) for value in facts.get(field,[])
                        if isinstance(value,str)),reverse=True)
        if matches:creator_score+=weight*matches[0]
    score=min(1.65,score+creator_score)
    reasons=[]
    if score>=.35:
        sources=[]
        if profile.get('history'):sources.append('בצפייה')
        if profile.get('personal'):sources.append('ברשימות שלך')
        reasons.append('מתאים לדפוס שחוזר %s' % (' וגם '.join(sources) or 'בהעדפות הבית'))
    return score,reasons

def affinity(item, feedback):
    """Return a bounded score and factual explanation, not a claim of shared mood."""
    facts=item.get('traits',{});score=0;reasons=[]
    for f in feedback.values():
        old=f.get('traits',{});sign=f['value']
        for field,weight,label in [('directors',1.3,'אותו במאי'),('writers',0.8,'יוצר משותף בתסריט'),('cast',0.35,'שחקן משותף'),('tags',0.55,'נושא משותף בקטלוג')]:
            previous={x.casefold() for x in old.get(field,[])}
            common=[x for x in facts.get(field,[]) if x.casefold() in previous]
            if common:
                score+=sign*weight
                if sign>0:reasons.append('%s: %s, כמו ב־%s שאהבת' % (label,common[0],f['title']))
    return max(-3,min(3,score)),list(dict.fromkeys(reasons))[:2]

def refinement(item,session):
    """Session preferences are reversible ranking nudges, never content assurances."""
    score=0;reasons=[]
    if session.get('discovery_mode')=='less_familiar':
        # Catalog recommendation provenance signals relevance, not popularity.
        # Prefer candidates without the same creators as the last rejected item.
        old=session.get('avoid_creators',[])
        shared=set(item.get('traits',{}).get('directors',[])) & set(old)
        if shared:score-=1
    if session.get('discovery_mode')=='lighter':
        labels=genres(item.get('genres',[]))
        if labels & {'comedy','קומדיה'}:
            score+=1;reasons.append('כיוון קומי יותר לפי סיווג הקטלוג')
        if labels & {'horror','אימה'}:score-=1.5
    vibe=session.get('vibe','')
    labels=genres(item.get('genres',[]))
    wanted={
        'light':{'comedy','family','music','קומדיה','משפחה','מוזיקה'},
        'tense':{'thriller','crime','mystery','action','war','מתח','פשע','מסתורין','אקשן','מלחמה'},
        'moving':{'drama','romance','music','history','דרמה','רומנטיקה','מוזיקה','היסטוריה'},
    }.get(vibe,set())
    avoided={
        'light':{'horror','thriller','war','אימה','מתח','מלחמה'},
        'tense':{'family','kids','משפחה','ילדים'},
        'moving':{'horror','אימה'},
    }.get(vibe,set())
    if labels & wanted:
        score+=1.6
        reasons.append({'light':'כיוון קומי או משפחתי יותר לפי סיווג הקטלוג',
                        'tense':'כיוון מותח לפי סיווג הקטלוג',
                        'moving':'כיוון רגשי לפי סיווג הקטלוג'}[vibe])
    if labels & avoided:score-=1.2
    return score,reasons


def surprise(item,feedback,implicit=None):
    """A bounded novelty nudge. It never overrides explicit dislike or hard filters."""
    liked=[f for f in feedback.values() if f.get('value',0)>0]
    known_genres=set().union(*(genres(f.get('genres',[])) for f in liked))
    known_directors={name.casefold() for f in liked for name in f.get('traits',{}).get('directors',[])}
    implicit=implicit or {}
    known_genres.update(key for key,value in implicit.get('genres',{}).items() if value>=.45)
    known_directors.update(key for key,value in implicit.get('traits',{}).get('directors',{}).items() if value>=.45)
    if not known_genres and not known_directors:return 0,[]
    item_genres=genres(item.get('genres',[]))
    directors={name.casefold() for name in item.get('traits',{}).get('directors',[])}
    if item_genres and not item_genres & known_genres and not directors & known_directors:
        return .9,['בחירה פחות צפויה ביחס לטעם שנלמד מהצפייה ומהרשימות']
    return -.25,[]


def vibe_fit(item, vibe):
    """Classify a known catalog genre for a mode; zero means unknown/ambiguous."""
    labels=genres(item.get('genres',[]))
    wanted={
        'light':{'comedy','family','music','animation','קומדיה','משפחה','מוזיקה','אנימציה'},
        'tense':{'thriller','crime','mystery','action','war','מתח','פשע','מסתורין','אקשן','מלחמה'},
        'moving':{'drama','romance','music','history','דרמה','רומנטיקה','מוזיקה','היסטוריה'},
    }.get(vibe,set())
    avoided={
        'light':{'horror','thriller','war','אימה','מתח','מלחמה'},
        'tense':{'family','kids','animation','משפחה','ילדים','אנימציה'},
        'moving':{'horror','אימה'},
    }.get(vibe,set())
    has_wanted=bool(labels&wanted);has_avoided=bool(labels&avoided)
    if has_wanted and not has_avoided:return 1
    if has_avoided and not has_wanted:return -1
    return 0
