"""Own profile persistence only. Existing corrupt data is not silently overwritten."""
import json
import os
import tempfile
import math
import re
from .engine import initial_state


class StateError(Exception):
    pass


def validate(value):
    def require(condition):
        if not condition:raise StateError('Preference schema invalid; original preserved')
    def text(x,limit=300):return isinstance(x,str) and 0<len(x)<=limit
    def key(x):return isinstance(x,str) and re.fullmatch(r'(movie|tvshow):[1-9][0-9]{0,11}',x)
    def keys(x):return isinstance(x,list) and len(x)<=20000 and all(key(k) for k in x)
    def genres(x):return isinstance(x,list) and len(x)<=100 and all(text(g,80) for g in x)
    try:
        require(isinstance(value,dict) and value['version']==1)
        require(isinstance(value['profiles'],dict) and 1<=len(value['profiles'])<=8)
        require(isinstance(value['viewers'],list) and 1<=len(value['viewers'])<=8)
        require(len(set(value['viewers']))==len(value['viewers']))
        require(all(k in value['profiles'] for k in value['viewers']))
        for p in value['profiles'].values():
            require(text(p['name'],40) and isinstance(p['feedback'],dict) and len(p['feedback'])<=20000)
            require(keys(p['seen']) and keys(p['saved']))
            for k,f in p['feedback'].items():
                require(key(k) and type(f['value']) is int and f['value'] in (-1,1))
                require(text(f['title']) and genres(f['genres']))
        require(isinstance(value['catalog'],list) and len(value['catalog'])<=20000)
        for c in value['catalog']:
            require(key(c['key']) and c['key']==c['kind']+':'+c['tmdb'])
            require(keys(c.get('recommended_from',[])))
            require(c.get('provider','pov') in ('pov','umbrella'))
            require(type(c.get('watched',False)) is bool)
            require(text(c.get('originaltitle',c['title'])))
            require(isinstance(c.get('imdb',''),str) and (not c.get('imdb') or re.fullmatch(r'tt[0-9]{5,12}',c['imdb'])))
            require(isinstance(c.get('tvdb',''),str) and (not c.get('tvdb') or re.fullmatch(r'[1-9][0-9]{0,11}',c['tvdb'])))
            require(text(c['title']) and genres(c['genres']) and isinstance(c['plot'],str))
            require(type(c['year']) is int and isinstance(c['art'],dict))
            require(all(isinstance(k,str) and isinstance(v,str) for k,v in c['art'].items()))
            require(c['runtime'] is None or type(c['runtime']) is int and 0<c['runtime']<86400)
            require(type(c['rating']) in (float,int) and math.isfinite(c['rating']) and 0<=c['rating']<=10)
        session=value['session']
        require(type(session['started']) in (int,float) and math.isfinite(session['started']) and session['started']>0)
        require(type(session['minutes']) is int and session['minutes'] in (0,45,60,90,120,150,180))
        require(keys(session['excluded']))
        require(type(session.get('max_runtime',86400)) is int and 0<session.get('max_runtime',86400)<=86400)
        require('anchor' not in session or key(session['anchor']))
        require(genres(session.get('anchor_genres',[])) and genres(session.get('avoid_genres',[])))
    except (AssertionError,ValueError,TypeError,KeyError,OverflowError) as e:
        raise StateError('Preference schema invalid; original preserved') from e
    return value


def load(path):
    if not os.path.exists(path):
        return initial_state()
    try:
        with open(path,encoding='utf-8') as f: value=json.load(f)
        return validate(value)
    except (ValueError,KeyError,TypeError,OSError) as e:
        raise StateError('Preference file unreadable; preserved for recovery') from e


def save(path, state):
    validate(state)
    folder=os.path.dirname(path);os.makedirs(folder,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.tonight-',suffix='.tmp',dir=folder)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(state,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
