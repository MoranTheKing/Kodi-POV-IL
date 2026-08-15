#!/usr/bin/env python3
"""Prove the guards in embedded_rtl.repair() are what makes the suite green.

Every refusal case in test_embedded_rtl.py would pass just as happily if the
guard it names were missing and something EARLIER refused for its own reasons.
So: delete one guard at a time from the source, re-exec the module, and re-run
the scenario that guard exists for. If the scenario still passes, the guard was
never what stopped it and the case proves nothing.

Reuses the World harness from the main test rather than a second copy of it --
a divergent copy is how a sabotage pass ends up sabotaging something the real
test never exercised.

Run: python3 tools/test_embedded_rtl_sabotage.py
"""

import importlib.util
import sys
import tempfile
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0]]

# Import the harness without running its own suite: load the source, keep only
# the World class and the constants.
HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'test_embedded_rtl.py')
src = open(HARNESS, encoding='utf-8').read()
cut = src.index("EMB_LINK = ")
# __file__ too: the harness resolves the add-on path from it, and an
# exec'd namespace has no __file__ of its own.
harness_ns = {'__name__': 'harness', '__file__': HARNESS}
exec(compile(src[:cut], HARNESS, 'exec'), harness_ns)
World = harness_ns['World']
EMB_LINK = '%7B%22type%22%3A%22engine%22%2C%22embedded%22%3Atrue%7D'

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')
ORIGINAL = open(os.path.join(LIB, 'embedded_rtl.py'), encoding='utf-8').read()

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def load_sabotaged(old, new, world):
    """Install `world`, then load embedded_rtl with `old` replaced by `new`.

    `old`/`new` may be lists, for a guard that is spread over more than one
    place. Removing only half of such a guard leaves the other half doing its
    job, the defect does not come back, and the case then reports the guard as
    unproven when the truth is that the sabotage was incomplete.
    """
    olds = old if isinstance(old, list) else [old]
    news = new if isinstance(new, list) else [new]
    text = ORIGINAL
    for o, n in zip(olds, news):
        if o not in text:
            raise AssertionError('sabotage anchor not found:\n' + o)
        text = text.replace(o, n, 1)
    world.install()          # stubs + a pristine module registered
    path = os.path.join(tempfile.mkdtemp(), 'embedded_rtl.py')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    spec = importlib.util.spec_from_file_location(
        'resources.lib.embedded_rtl', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['resources.lib.embedded_rtl'] = mod
    spec.loader.exec_module(mod)
    return mod


# --- 1. the lock: the guard that stands between this and a closed movie -----
w = World(current_sub=EMB_LINK)
mod = load_sabotaged("    claim = _claim(url)\n"
                     "    if claim != 'ok':",
                     "    claim = 'ok'\n"
                     "    if False:", w)
lock = os.path.join(w.home, 'embedded_rtl.lock')
with open(lock, 'w', encoding='utf-8') as f:
    f.write('busy\n%r\n%s\n' % (__import__('time').time(), w.playing))
st = mod.repair()
check('SABOTAGE: without the lock, a second process extracts in parallel',
      st == 'delivered' and w.extract_args is not None,
      'status=%s extracted=%s' % (st, w.extract_args is not None))

# --- 2. the "playback moved on" guard ---------------------------------------
w = World(current_sub=EMB_LINK, playing_after='http://cdn/next_episode.mkv')
mod = load_sabotaged(
    "    if _playing_file() != url:\n"
    "        _log('playing file changed during extraction -- not delivering',\n"
    "             level='INFO')\n"
    "        return 'moved_on'\n",
    "    pass\n", w)
st = mod.repair()
check("SABOTAGE: without the guard, the next episode gets this file's subs",
      st == 'delivered' and len(w.subtitles_set) == 1,
      'status=%s delivered=%s' % (st, w.subtitles_set))

# --- 3. the "user picked another subtitle" guard (our own record) ------------
w = World(current_sub='%7B%22type%22%3A%22ai%22%7D')
mod = load_sabotaged(
    "            if not payload.get('embedded'):\n"
    "                _log('user picked another subtitle -- not delivering',\n"
    "                     level='INFO')\n"
    "                return 'superseded'\n",
    "            pass\n", w)
st = mod.repair()
check("SABOTAGE: without the guard, the user's own pick is overwritten",
      st == 'delivered' and len(w.subtitles_set) == 1,
      'status=%s delivered=%s' % (st, w.subtitles_set))

# --- 3b. subtitles turned off with KODI'S OWN control ------------------------
# Our record never sees this, so only the live player check can catch it.
w = World(current_sub=EMB_LINK, subs_enabled=False)
mod = load_sabotaged(
    "        if not xbmc.getCondVisibility('VideoPlayer.SubtitlesEnabled'):",
    "        if False:", w)
st = mod.repair()
check('SABOTAGE: without the live check, subtitles are switched back on',
      st == 'delivered' and len(w.subtitles_set) == 1,
      'status=%s delivered=%s' % (st, w.subtitles_set))

# --- 3c. switched to another language with Kodi's own control ---------------
w = World(current_sub=EMB_LINK, active_sub='English')
mod = load_sabotaged(
    "    if current and not _is_hebrew_name(current):",
    "    if False:", w)
st = mod.repair()
check("SABOTAGE: without the live check, a native switch is overridden",
      st == 'delivered' and len(w.subtitles_set) == 1,
      'status=%s delivered=%s' % (st, w.subtitles_set))

# --- 4. the policy gate -----------------------------------------------------
# On a LOCAL file, deliberately. The 'off' policy also has allow_http False, so
# over a remote URL the HTTP gate refuses first and removing the policy gate
# changes nothing -- the case would report a guard as proven that had never
# been reached. A local path takes the HTTP gate out of the picture entirely,
# leaving only the gate under test.
w = World(playing='/storage/movie.mkv', current_sub=EMB_LINK,
          policy={'mode': 'off', 'enabled': False, 'try_extract': False,
                  'allow_http': False})
mod = load_sabotaged(
    "    if not policy.get('enabled') or not policy.get('try_extract'):",
    "    if False:", w)
st = mod.repair()
check('SABOTAGE: without the policy gate, mode=off still extracts',
      st == 'delivered' and w.extract_args is not None,
      'status=%s extracted=%s' % (st, w.extract_args is not None))

# --- 5. the HTTP gate -------------------------------------------------------
w = World(current_sub=EMB_LINK,
          policy={'mode': 'local_only', 'enabled': True, 'try_extract': True,
                  'allow_http': False})
mod = load_sabotaged(
    "    if '://' in url and not allow_http:",
    "    if False:", w)
st = mod.repair()
check('SABOTAGE: without the HTTP gate, local_only hits the network',
      st == 'delivered' and w.extract_args is not None,
      'status=%s extracted=%s' % (st, w.extract_args is not None))

# --- 6. the identical-output gate -------------------------------------------
# Text that fix_rtl_punctuation leaves alone (no Hebrew, nothing to wrap).
w = World(current_sub=EMB_LINK,
          extract='1\n00:00:01,000 --> 00:00:03,000\nHello there.\n')
mod = load_sabotaged("    if fixed == text:", "    if False:", w)
st = mod.repair()
check('SABOTAGE: without it, an unchanged file is still swapped in',
      st == 'delivered' and len(w.subtitles_set) == 1,
      'status=%s delivered=%s' % (st, w.subtitles_set))
# ...and with the real module it must NOT be.
w2 = World(current_sub=EMB_LINK,
           extract='1\n00:00:01,000 --> 00:00:03,000\nHello there.\n')
st2 = w2.install().repair()
check('the real module leaves an unchanged file alone',
      st2 == 'no_change' and not w2.subtitles_set,
      'status=%s delivered=%s' % (st2, w2.subtitles_set))

# --- 7. the lower bound on a lock's age -------------------------------------
# The bug this suite caught: the first version asked `0 <= age < stale`, so a
# claim stamped even slightly in the FUTURE -- which is all it takes for the
# timestamp to be rounded forward as it is written -- read as neither live nor
# stale, got reclaimed, and both processes extracted. Restoring that exact
# condition must bring the failure back; if it does not, the fix was cosmetic.
# (The `age < 0` clamp above it is deliberate belt-and-braces, not the fix --
# with the lower bound gone, a negative age already compares as live.)
w = World(current_sub=EMB_LINK)
mod = load_sabotaged(
    ["        if age < 0:\n            age = 0.0\n",
     "            if age < _stale_after():\n                return 'busy'\n"],
    ["        pass\n",
     "            if 0 <= age < _stale_after():\n                return 'busy'\n"],
    w)
with open(os.path.join(w.home, 'embedded_rtl.lock'), 'w',
          encoding='utf-8') as f:
    f.write('busy\n%r\n%s\n' % (__import__('time').time() + 5, w.playing))
st = mod.repair()
check('SABOTAGE: with the old lower bound, a live lock is reclaimed',
      st == 'delivered' and w.extract_args is not None,
      'status=%s extracted=%s' % (st, w.extract_args is not None))

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
