"""The two language rules the "עברית מסונכרנת למובנה" row depends on.

Both exist to stop the same accident: handing the user a subtitle in a
language they did not ask for.

  1. subsync._oracle_candidates() excludes Hebrew BY DESIGN -- its original job
     is to be a timing oracle for correcting Hebrew, so Hebrew cannot also be
     the reference. The new caller needs the opposite, and without the flag it
     silently gets zero Hebrew candidates.
  2. _embedded_aligned_source_srt()'s cross-language fallback is correct for
     the AI path (an English source still ends up Hebrew) and WRONG for a
     caller that delivers what comes back. strict_lang turns it off.

Rule 2 is asserted on network behaviour, not on the return value: with no
Hebrew candidate the function returns (None, None) either way, so a test that
only checked the return would pass with the guard deleted. What must be true is
that it performs NO container reads for a language it could never deliver.

Run: python3 tools/test_embedded_sync_lang.py
"""
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# --- rule 1: _oracle_candidates ---------------------------------------------
def load_subsync(results):
    for name in list(sys.modules):
        if name.split('.')[0] in ('resources', 'xbmc', 'xbmcgui', 'xbmcaddon',
                                  'xbmcvfs'):
            sys.modules.pop(name, None)
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib

    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    ku.get_setting = lambda k, d='': d
    ku.set_setting = lambda k, v: None
    ku.cache_dir = lambda: '/tmp'
    ku.translate_path = lambda p: p
    ku.addon_profile_path = lambda: '/tmp'
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku

    bridge = types.ModuleType('resources.lib.subs_engine_bridge')
    bridge.enabled = lambda: True
    bridge.search = lambda info, modal_progress=False: results
    sys.modules['resources.lib.subs_engine_bridge'] = bridge
    lib.subs_engine_bridge = bridge

    spec = importlib.util.spec_from_file_location(
        'subsync_under_test', os.path.join(LIB, 'subsync.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


import json
import urllib.parse


def row(lang, kind, release):
    return {'language': lang, '_engine_kind': kind,
            'link': urllib.parse.quote(json.dumps(
                {'type': 'engine', 'filename': release, 'source': 'ktuvit'}))}


RESULTS = [row('he', 'human_he', 'Movie.2024.1080p.HEB'),
           row('he', 'mt_he', 'Movie.2024.720p.MT'),
           row('en', 'other', 'Movie.2024.1080p.ENG'),
           row('fr', 'other', 'Movie.2024.1080p.FRA')]

sub = load_subsync(RESULTS)
default = sub._oracle_candidates({})
langs = sorted(set(c.get('language') for c in default))
check('the default still excludes Hebrew', 'he' not in langs, repr(langs))
check('the default still returns the foreign oracles',
      set(langs) == {'en', 'fr'}, repr(langs))

with_he = sub._oracle_candidates({}, include_he=True)
langs2 = sorted(set(c.get('language') for c in with_he))
check('include_he returns Hebrew', 'he' in langs2, repr(langs2))
check('include_he returns BOTH Hebrew kinds (human and machine)',
      len([c for c in with_he if c.get('language') == 'he']) == 2,
      repr([c.get('release') for c in with_he]))
check('include_he keeps the foreign ones too',
      {'en', 'fr'} <= set(langs2), repr(langs2))

# The kind filter had to widen with the language filter. If it had not, Hebrew
# would be let through one line and dropped the next -- silently, back to zero.
check('Hebrew is not dropped again by the kind filter',
      [c for c in with_he if c.get('language') == 'he'], repr(with_he))


# --- rule 2: strict_lang performs no reads for an undeliverable language ----
def load_translate(oracle_rows):
    reads = []
    for name in list(sys.modules):
        if name.split('.')[0] in ('resources', 'xbmc', 'xbmcgui', 'xbmcaddon',
                                  'xbmcvfs'):
            sys.modules.pop(name, None)

    xbmc = types.ModuleType('xbmc')

    class _P(object):
        def getPlayingFile(self):
            return 'http://cdn/movie.mkv'

        def isPlayingVideo(self):
            return True
    xbmc.Player = _P
    xbmc.getCondVisibility = lambda c: False
    xbmc.getInfoLabel = lambda c: ''
    xbmc.log = lambda *a, **k: None
    xbmc.sleep = lambda *a: None
    sys.modules['xbmc'] = xbmc
    gui = types.ModuleType('xbmcgui')

    class _W(object):
        def __init__(self, *a):
            pass

        def getProperty(self, k):
            return ''

        def setProperty(self, k, v):
            pass

        def clearProperty(self, k):
            pass
    gui.Window = _W
    sys.modules['xbmcgui'] = gui

    # Load the REAL translate.py, but only far enough to call the aligner.
    spec = importlib.util.spec_from_file_location(
        'resources.lib.translate', os.path.join(LIB, 'translate.py'))
    pkg = types.ModuleType('resources')
    pkg.__path__ = [os.path.join(LIB, '..')]
    libmod = types.ModuleType('resources.lib')
    libmod.__path__ = [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = libmod
    try:
        mod = importlib.util.module_from_spec(spec)
        sys.modules['resources.lib.translate'] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        print('   (translate.py could not be imported headless: %s)' % e)
        return None, reads

    ss = types.ModuleType('resources.lib.subsync')
    ss._oracle_candidates = lambda info, include_he=False: oracle_rows
    ss.playing_release = lambda info: ''
    ss._download_oracle = lambda payload: ''
    sys.modules['resources.lib.subsync'] = ss

    ee = types.ModuleType('resources.lib.embedded_extract')

    def _cue(url, langs, **kw):
        reads.append(tuple(langs))
        return {}
    ee.cue_reference_times_multi = _cue
    sys.modules['resources.lib.embedded_extract'] = ee
    for extra in ('sync_align', 'subsync', 'release_match'):
        sys.modules.setdefault('resources.lib.' + extra,
                               types.ModuleType('resources.lib.' + extra))
    sys.modules['resources.lib.sync_align'].verify_cues = \
        lambda ref, text: {'ok': False}
    sys.modules['resources.lib.release_match'].match_pct = lambda a, b: 0
    return mod, reads


ENGLISH_ONLY = [{'release': 'Movie.2024.ENG', 'payload': {}, 'language': 'en'}]

tr, reads = load_translate(ENGLISH_ONLY)
if tr is None:
    check('translate.py imports headless', False,
          'skipped rule-2 checks -- see message above')
else:
    reads[:] = []
    out = tr._embedded_aligned_source_srt({}, 'he', strict_lang=True,
                                          include_he=True)
    check('strict_lang: a Hebrew pick with no Hebrew sub returns nothing',
          out == (None, None), repr(out))
    check('strict_lang: and performs ZERO container reads',
          not reads, 'read for %r -- it would have delivered English' % (reads,))

    reads[:] = []
    out = tr._embedded_aligned_source_srt({}, 'he', strict_lang=False)
    check('the AI path still falls back to English (unchanged)',
          reads and 'en' in reads[0], repr(reads))

# --- SABOTAGE: prove the strict_lang filter is what produces the zero -------
# Without it, a Hebrew pick on a title with only an English subtitle reads the
# container for English and aligns it -- i.e. delivers English to someone who
# asked for Hebrew. If deleting the filter does NOT break the check above, the
# check is not testing the filter.
if tr is not None:
    import tempfile
    SRC = open(os.path.join(LIB, 'translate.py'), encoding='utf-8').read()
    GUARD = ("        if strict_lang:\n"
             "            try_langs = [x for x in try_langs if x == pref]\n")
    assert GUARD in SRC, 'sabotage anchor not found'
    sab_dir = tempfile.mkdtemp()
    sab_path = os.path.join(sab_dir, 'translate.py')
    with open(sab_path, 'w', encoding='utf-8') as f:
        f.write(SRC.replace(GUARD, "        pass\n", 1))
    spec = importlib.util.spec_from_file_location(
        'resources.lib.translate', sab_path)
    sab = importlib.util.module_from_spec(spec)
    sys.modules['resources.lib.translate'] = sab
    spec.loader.exec_module(sab)
    reads[:] = []
    sab._embedded_aligned_source_srt({}, 'he', strict_lang=True,
                                     include_he=True)
    check('SABOTAGE: without the filter it reads for English on a Hebrew pick',
          bool(reads), 'no read happened -- the check above proves nothing')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
