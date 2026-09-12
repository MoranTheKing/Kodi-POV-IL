"""Fixes that each had the same shape: a fact stated in one place and
contradicted in another.

  * A '.google' marker aged on its OWN mtime while load_text() touched only the
    translation, so the marker could be evicted out from under a file that is
    still being served. After that _is_google_translated() answers False and the
    next cache hit backfills machine translation into the community pool.
  * The model dropdown advertised a daily quota the add-on's own table
    contradicts, so the quota panel would say "24 of 20 (120%)" on the first
    film.

Run: python3 tools/test_cache_sidecars_and_labels.py
"""
import io
import os
import re
import sys
import time
import types
import tempfile
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')

FAILED = []


def check(name, got, want):
    if got == want:
        print('  ok  - %s' % name)
    else:
        print('  FAIL- %s\n        got  %r\n        want %r' % (name, got, want))
        FAILED.append(name)


# ---- cache.prune(): a sidecar must age with the file it describes ----------
TMP = tempfile.mkdtemp(prefix='aisubs-cache-')
_ku = types.ModuleType('kodi_utils')
_ku.cache_dir = lambda: TMP
_ku.get_int = lambda k, d=0: {'cache_ttl_days': 30, 'cache_size_mb': 200}.get(k, d)
_ku.get_setting = lambda k, d='': d
_ku.log = lambda *a, **k: None
_pkg = types.ModuleType('resources'); _pkg.__path__ = []
_sub = types.ModuleType('resources.lib'); _sub.__path__ = [LIB]
sys.modules.setdefault('resources', _pkg)
sys.modules.setdefault('resources.lib', _sub)
sys.modules['resources.lib.kodi_utils'] = _ku
sys.modules['kodi_utils'] = _ku

_spec = importlib.util.spec_from_file_location(
    'resources.lib.cache', os.path.join(LIB, 'cache.py'))
cache = importlib.util.module_from_spec(_spec)
sys.modules['resources.lib.cache'] = cache
_spec.loader.exec_module(cache)

sub = os.path.join(TMP, 'translated')
os.makedirs(sub, exist_ok=True)
fresh = os.path.join(sub, 'movie.he.srt')
with io.open(fresh, 'w', encoding='utf-8') as f:
    f.write('1\n00:00:01,000 --> 00:00:02,000\nshalom\n')
marker = fresh + '.google'
open(marker, 'w').close()

# The translation is read every week; the marker never is. Age ONLY the marker
# far past the TTL -- exactly what load_text() produces in the field.
old = time.time() - 400 * 86400
os.utime(marker, (old, old))

cache.prune()
check('a translation still in use is kept', os.path.isfile(fresh), True)
check('...and its .google marker is NOT evicted out from under it',
      os.path.isfile(marker), True)

# The markers that ACTUALLY exist. '.emb2' is only a marker KEY -- pool writes
# '<path>.emb2.shared' -- so protecting '.emb2' protected nothing while
# '.shared', which governs whether a file is re-uploaded, was left exposed.
check('the real pool markers are covered',
      all(x in cache._SIDECARS for x in ('.shared', '.emb2.shared', '.google', '.release')),
      True)
check('.emb2.shared strips WHOLE (its parent is the translation, not <p>.emb2)',
      cache._sidecar_parent('/c/movie.he.srt.emb2.shared'), '/c/movie.he.srt')
check('.shared resolves to its translation',
      cache._sidecar_parent('/c/movie.he.srt.shared'), '/c/movie.he.srt')
check('an ordinary translation is not mistaken for a marker',
      cache._sidecar_parent('/c/movie.he.srt'), '')

shared = fresh + '.shared'
open(shared, 'w').close()
os.utime(shared, (old, old))
cache.prune()
check('a .shared marker is not evicted from under a file still in use',
      os.path.isfile(shared), True)

# A sidecar is sometimes written BEFORE its parent: '.release' lands when the
# reference is chosen, minutes before the translation exists. A prune() in that
# window must not delete it.
early = os.path.join(sub, 'not-yet-translated.he.srt.release')
with io.open(early, 'w', encoding='utf-8') as f:
    f.write('Some.Release.1080p')
cache.prune()
check('a fresh marker whose parent does not exist YET survives',
      os.path.isfile(early), True)

# The inverse: a marker whose parent is gone must not linger forever.
orphan = os.path.join(sub, 'vanished.he.srt.google')
open(orphan, 'w').close()
os.utime(orphan, (old, old))
cache.prune()
check('an OLD orphaned marker is collected', os.path.isfile(orphan), False)

# And a genuinely stale pair still goes.
stale = os.path.join(sub, 'old.he.srt')
with io.open(stale, 'w', encoding='utf-8') as f:
    f.write('x')
stale_marker = stale + '.google'
open(stale_marker, 'w').close()
for p in (stale, stale_marker):
    os.utime(p, (old, old))
cache.prune()
check('a translation past its TTL is still evicted', os.path.isfile(stale), False)
check('...and its marker goes with it', os.path.isfile(stale_marker), False)


# ---- the lookups stay tier-pinned, on purpose ------------------------------
# Widening them looked right and is not: resolve()'s early cache return fires
# BEFORE the first progressive_cb, so on the picker path a HIT is delivered to
# nobody and the viewer keeps the English fallback -- a miss, which falls
# through to the full path, is what actually delivers. And the pool backfill
# takes its tier from the SETTING, not from the file found, so a plain file
# found while the setting is on would upload as the ai_ar variant permanently.
_tr = io.open(os.path.join(ADDON, 'resources', 'lib', 'translate.py'),
              encoding='utf-8').read()
_df = io.open(os.path.join(ADDON, 'default.py'), encoding='utf-8').read()
_ca = io.open(os.path.join(LIB, 'cache.py'), encoding='utf-8').read()
check('no caller looks across tiers behind an unwired early return',
      'find_translated' not in _tr and 'find_translated' not in _df, True)
check('and the helper is gone rather than left for someone to wire up',
      'find_translated' not in _ca, True)
check('the early lookup is still pinned to _tier',
      'source_id=early_source_id, tier=_tier)' in _tr, True)
# '>= 1' on a string that occurs FOUR times in translate.py tested nothing:
# it passed with the [CACHE] block deleted outright. Pin the actual call.
_marker = _tr[_tr.index('for entry in ai_entries:'):]
_marker = _marker[:_marker.index('cache marker check failed')]
check('the [CACHE] marker block is still there',
      'translated = cache.translated_path(' in _marker, True)
check('...and is pinned to the same tier the download path uses',
      'tier=' not in _marker, True)
check('...and only marks an entry when the file really exists',
      'if os.path.isfile(translated):' in _marker, True)

# ---- the dropdown may not advertise a quota the table contradicts ----------
_qs = importlib.util.spec_from_file_location(
    'gq_under_test', os.path.join(LIB, 'gemini_quota.py'))
gq = importlib.util.module_from_spec(_qs)
_qs.loader.exec_module(gq)

PO = os.path.join(ADDON, 'resources', 'language',
                  'resource.language.en_gb', 'strings.po')
po = io.open(PO, encoding='utf-8').read()
labels = dict(re.findall(r'msgctxt "#(\d+)"\nmsgid "([^"]*)"', po))

# id -> the model that option selects (settings.xml order)
OPTION_MODEL = {
    '32230': 'gemini-3.5-flash-lite',
    '32231': 'gemini-3.1-flash',
    '32234': 'gemini-3.8-flash',
}
for sid, model in OPTION_MODEL.items():
    label = labels.get(sid, '')
    nums = [int(n) for n in re.findall(r'(\d+)\s*/\s*day', label)]
    limit = gq.MODEL_LIMITS.get(model)
    check('#%s names %s\'s real daily cap (%s)' % (sid, model, limit),
          nums, [limit] if limit else [])

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
