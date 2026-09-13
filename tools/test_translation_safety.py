"""Execute the production safety gates with offline IO doubles, never credentials."""
import ast
import importlib.util
import itertools
import os
from pathlib import Path
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'addons/service.subtitles.kodipovilai'
LIB = ADDON / 'resources/lib'


def selected(path, names, namespace):
    nodes = [n for n in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == len(names), names
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)


def register(name, **values):
    m = types.ModuleType('resources.lib.' + name)
    m.__dict__.update(values)
    sys.modules[m.__name__] = m
    setattr(sys.modules['resources.lib'], name, m)
    return m


for name in ('resources', 'resources.lib'):
    m = types.ModuleType(name)
    m.__path__ = [str(LIB)]
    sys.modules[name] = m
sys.modules['resources'].lib = sys.modules['resources.lib']

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp) / 'translated'
    base.mkdir()
    text = '1\n00:00:01,000 --> 00:00:05,000\n' + 'שלום לכם זהו תרגום לעברית. ' * 12
    for number, tier, google in ((1, '', True), (2, '.ar', True), (3, '.ar', False)):
        p = base / ('tt000000%d_S0E0_en_aabbccdd11223344%s.he.srt' % (number, tier))
        p.write_text(text, encoding='utf-8')
        if google:
            Path(str(p) + '.google').touch()
    register('cache', load_text=lambda p: Path(p).read_text(encoding='utf-8'))
    register('tmdb_helper', resolve_imdb_to_tmdb=lambda *a: '1',
             title_and_year=lambda **k: ('Fixture', '2000'))
    sm = register('srt', os=os)
    selected(LIB / 'srt.py', {'looks_hebrew', 'is_google_translated'}, sm.__dict__)
    posts = []
    ns = dict(__package__='resources.lib', os=os, _CACHE_NAME_RE=None,
              _urlreq=object(), share_enabled=lambda: True,
              kodi_utils=types.SimpleNamespace(cache_dir=lambda: tmp),
              _BULK_THROTTLE_SEC=0,
              _post=lambda body, marker_path=None: posts.append((body['kind'], marker_path)),
              _is_token_like=lambda _: False, _release_from=lambda _: 'Fixture',
              _has_id=lambda _: True,
              _params=lambda i: dict(tmdb='1', imdb=i['imdb_id'], type='movie',
                                     season='0', episode='0'))
    selected(LIB / 'pool.py', {'share_cache', '_build_body', 'was_contributed', '_marker_path'}, ns)
    ns['share_cache']()
    assert len(posts) == 1 and posts[0][0] == 'ai_ar', posts
    assert 'tt0000003' in posts[0][1], posts
    # Failure of the gate must not authorize a POST.
    posts.clear()
    sm.is_google_translated = lambda _: (_ for _ in ()).throw(OSError('fixture'))
    ns['share_cache']()
    assert posts == [], posts
print('PASS: Google provenance and unavailable gate block bulk sharing')

# Every filesystem enumeration order: cap eviction may not orphan provenance.
for order in itertools.permutations(range(3)):
    with tempfile.TemporaryDirectory() as tmp:
        parent = Path(tmp) / 'fixture.he.srt'
        marker = Path(str(parent) + '.google')
        filler = Path(tmp) / 'unrelated.bin'
        parent.write_bytes(b'x' * 1024)
        marker.touch()
        filler.write_bytes(b'x' * (11 * 1024 * 1024))
        for p in (parent, marker, filler):
            os.utime(p, (time.time(), time.time()))
        register('kodi_utils', cache_dir=lambda: tmp,
                 get_int=lambda key, default: 10 if key == 'cache_size_mb' else 180)
        ns = dict(__package__='resources.lib', __name__='resources.lib.cache')
        exec(compile((LIB / 'cache.py').read_text(encoding='utf-8'), 'cache', 'exec'), ns)
        paths = [parent, marker, filler]
        ns['_walk_cache_files'] = lambda: iter(
            [(str(paths[i]), time.time(), paths[i].stat().st_size) for i in order])
        ns['prune']()
        assert not parent.exists() or marker.exists(), order
print('PASS: cap eviction preserves provenance in all six enumeration orders')

# Execute BOTH callbacks, including stale success/failure and inactive jobs.
tree = ast.parse((ADDON / 'default.py').read_text(encoding='utf-8'))
callbacks = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
             and n.name == 'on_phase' and any(
                 isinstance(c, ast.Name) and c.id == '_job_token' for c in ast.walk(n))]
assert len(callbacks) == 2
for callback in callbacks:
    for active, source, token in (('1', 'NEW', 'new-token'), ('0', 'OLD', 'old-token'),
                                  ('1', 'NEW', 'old-token'), ('', '', 'old-token')):
        props = {'ai_subs.live_translate_active': active,
                 'ai_subs.live_translate_source': source,
                 'ai_subs.live_translate_job': token}
        initial = dict(props)
        window = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
            setProperty=lambda k, v: props.update({k: v}),
            clearProperty=lambda k: props.pop(k, None))
        ns = dict(xbmcgui=types.SimpleNamespace(Window=lambda _: window),
                  _job_token='old-token', _completion={'seen': False},
                  _safe_log=lambda *a, **k: None)
        selected(ADDON / 'default.py',
                 {'_owns_translation_job', '_clear_translation_job'}, ns)
        # Any stale handler reaching IO fails rather than disappearing in its catch.
        errors = []
        ns['_safe_log'] = lambda *a, **k: errors.append(a)
        exec(compile(ast.Module(body=[callback], type_ignores=[]), 'on_phase', 'exec'), ns)
        for success in (False, True):
            ns['on_phase']('done', dict(source_id='OLD', success=success, path='unused'))
            assert props == initial and not errors, (props, errors)
        if token != 'old-token':
            ns['_clear_translation_job']('old-token')
            assert props == initial
print('PASS: both stale done handlers and stale finally cleanup leave new jobs alone')

# A newer job may arrive while first_ready waits for video playback to start.
handler = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name == '_handle_translate_file')
callback = next(n for n in handler.body if isinstance(n, ast.FunctionDef)
                and n.name == 'on_phase')
with tempfile.TemporaryDirectory() as tmp:
    props = {'ai_subs.live_translate_job': 'OLD'}
    state = {'playing': False}
    events = []
    player = types.SimpleNamespace(isPlayingVideo=lambda: state['playing'],
        setSubtitles=lambda p: events.append(p), showSubtitles=lambda _: None)
    def next_job(_):
        props.update({'ai_subs.live_translate_job': 'NEW',
                      'ai_subs.live_translate_active': '1',
                      'ai_subs.live_translate_source': 'NEW'})
        state['playing'] = True
    window = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
                                  setProperty=lambda k, v: props.update({k: v}))
    ns = dict(os=os, xbmc=types.SimpleNamespace(Player=lambda: player, sleep=next_job),
              xbmcgui=types.SimpleNamespace(Window=lambda _: window),
              _job_token='OLD', out_path=str(Path(tmp) / 'old.he.srt'),
              _safe_log=lambda *a, **k: None)
    selected(ADDON / 'default.py', {'_owns_translation_job'}, ns)
    exec(compile(ast.Module(body=[callback], type_ignores=[]), 'first-ready', 'exec'), ns)
    ns['on_phase']('first_ready', dict(source_id='OLD', fallback_text='old fallback'))
    assert events == [] and props['ai_subs.live_translate_source'] == 'NEW'
print('PASS: first-ready wait cannot load a superseded subtitle')
