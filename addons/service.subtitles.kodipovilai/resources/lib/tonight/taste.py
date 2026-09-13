"""Evidence-based metadata taste signals; unknown attributes stay unknown."""
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
    return score,reasons
