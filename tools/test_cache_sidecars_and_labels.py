"""Three fixes that each had the same shape: a fact stated in one place and
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


# ---- find_translated: a lookup must not guess which tier was written -------
# resolve() writes tier='ar' when a gender reference was found and '' when none
# was. A lookup cannot know which happened for THIS title, so guessing one tier
# missed real translations -- which is why a second entry did not auto-load and
# the subtitle had to be picked by hand again.
tier_dir = os.path.join(TMP, 'translated')
os.makedirs(tier_dir, exist_ok=True)
ARGS = ('tt1234567', '', '', 'en')
plain = cache.translated_path(*ARGS, source_id='sid1')
tiered = cache.translated_path(*ARGS, source_id='sid1', tier='ar')
check('the two tiers really are different files', plain != tiered, True)

check('nothing cached -> empty', cache.find_translated(*ARGS, source_id='sid1'), '')

with io.open(tiered, 'w', encoding='utf-8') as f:
    f.write('shalom')
check('a gender-referenced translation IS found',
      cache.find_translated(*ARGS, source_id='sid1'), tiered)

os.remove(tiered)
with io.open(plain, 'w', encoding='utf-8') as f:
    f.write('shalom')
check('a plain translation is found too',
      cache.find_translated(*ARGS, source_id='sid1'), plain)

with io.open(tiered, 'w', encoding='utf-8') as f:
    f.write('better')
check('with both present the gender-referenced one wins',
      cache.find_translated(*ARGS, source_id='sid1'), tiered)

check('a different source_id is not confused with this one',
      cache.find_translated(*ARGS, source_id='sid2'), '')

# and the callers must actually use it
_tr = io.open(os.path.join(ADDON, 'resources', 'lib', 'translate.py'),
              encoding='utf-8').read()
_df = io.open(os.path.join(ADDON, 'default.py'), encoding='utf-8').read()
check('the [CACHE] marker asks for any tier',
      'cache.find_translated(' in _tr, True)
# The fast path stays TIER-PINNED on purpose. It hands a file to Kodi without
# any of the checks resolve() applies on a cache hit -- the _is_mostly_hebrew
# self-heal, the mtime refresh, the RTL re-apply, the pool backfill -- so
# widening it would turn a rare shortcut into the normal path and skip all
# four. resolve() does the tier-agnostic lookup instead, with the guards.
check('the fast path does NOT widen: the guards live in resolve()',
      '_cache.find_translated(' not in _df, True)
check('resolve() is the one that looks across tiers',
      'cache.find_translated(' in _tr, True)
_early = _tr[_tr.index('early_source_id = _source_id_for_ai(payload)'):]
_early = _early[:_early.index('# Only honour the cache')]
check('...and it is the EARLY cache lookup that was widened',
      'find_translated(' in _early, True)
check('the self-heal still guards whatever that lookup returns',
      '_is_mostly_hebrew(' in _tr.split('Only honour the cache')[1][:600], True)
# and neither may go back to guessing one
check('the [CACHE] marker no longer guesses the plain slot',
      'translated = cache.translated_path(' not in _tr.split('is_cached')[0][-800:], True)


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
