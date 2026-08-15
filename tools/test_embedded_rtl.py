#!/usr/bin/env python3
"""Exercise embedded_rtl.repair() headless, one branch per case.

The module's whole job is to decide WHETHER to overwrite what the user is
watching, so the cases that matter are the refusals, not the happy path. Each
case asserts the returned status AND the observable side effects (did it call
setSubtitles, what did it write), because a status string alone would let a
branch return the right word while doing the wrong thing.

The real srt.py is loaded -- the RTL wrap is the point of the exercise, so
stubbing it would test nothing.

Run: python3 tools/test_embedded_rtl.py
"""

import importlib.util
import os
import sys
import tempfile
import types

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# The Hebrew an embedded track carries: logical order, mark at the end. Kodi
# renders this with an LTR base direction and throws the '?' to the far side.
EMB_SRT = (
    '1\n00:00:01,000 --> 00:00:03,000\nאתה מאמין לזה?\n\n'
    '2\n00:00:04,000 --> 00:00:06,000\n-תשיגו חדר, בני זונות מלוכלכים!\n'
)


class World(object):
    """One scenario's Kodi + translate, rebuilt per case so nothing leaks."""

    def __init__(self, playing='http://cdn/movie.mkv', policy=None,
                 extract=EMB_SRT, current_sub='', playing_after=None,
                 playing_video=True, subs_enabled=True, active_sub='heb'):
        self.playing = playing
        self.playing_after = playing_after or playing
        self.playing_video = playing_video
        # What Kodi itself reports, which our own record never sees change.
        self.subs_enabled = subs_enabled
        self.active_sub = active_sub
        self.policy = policy or {'mode': 'auto', 'enabled': True,
                                 'try_extract': True, 'allow_http': True}
        self.extract = extract
        self.current_sub = current_sub
        self.props = {}
        self.subtitles_set = []
        self.notified = []
        self.logs = []
        self.quiet_seen = []
        self.extract_args = None
        self.calls = 0
        self.builtins = []
        self.streams = ['heb', 'eng']
        self.stream_set = []
        self.home = tempfile.mkdtemp()

    # --- the module under test sees these ---------------------------------
    def install(self):
        w = self

        player = types.SimpleNamespace()

        class _Player(object):
            def isPlayingVideo(self):
                return w.playing_video

            def getPlayingFile(self):
                # First read = before the extraction, later reads = after.
                w.calls += 1
                return w.playing if w.calls <= 1 else w.playing_after

            def getSubtitles(self):
                return w.active_sub

            # select_embedded (the real one) drives these.
            def getAvailableSubtitleStreams(self):
                return w.streams

            def setSubtitleStream(self, i):
                w.stream_set.append(i)

            def setSubtitles(self, p):
                w.subtitles_set.append(p)

            def showSubtitles(self, on):
                pass

        xbmc = types.ModuleType('xbmc')
        xbmc.Player = _Player
        xbmc.log = lambda *a, **k: None
        xbmc.getCondVisibility = (
            lambda cond: w.subs_enabled
            if cond == 'VideoPlayer.SubtitlesEnabled' else False)
        xbmc.executebuiltin = lambda *a, **k: w.builtins.append(a[0] if a else '')

        class _Win(object):
            def __init__(self, *a):
                pass

            def getProperty(self, k):
                return w.props.get(k, '')

            def setProperty(self, k, v):
                w.props[k] = v

            def clearProperty(self, k):
                w.props.pop(k, None)

        gui = types.ModuleType('xbmcgui')
        gui.Window = _Win

        for name in list(sys.modules):
            if name.split('.')[0] in ('xbmc', 'xbmcgui', 'xbmcvfs',
                                      'xbmcaddon', 'resources'):
                sys.modules.pop(name, None)
        sys.modules['xbmc'] = xbmc
        sys.modules['xbmcgui'] = gui

        pkg = types.ModuleType('resources')
        pkg.__path__ = [os.path.join(ADDON, 'resources')]
        lib = types.ModuleType('resources.lib')
        lib.__path__ = [LIB]
        sys.modules['resources'] = pkg
        sys.modules['resources.lib'] = lib

        ku = types.ModuleType('resources.lib.kodi_utils')
        ku.log = lambda m, level='INFO', **k: w.logs.append('%s %s' % (level, m))
        ku.notify = lambda m, **k: w.notified.append(m)
        ku.cache_dir = lambda: w.home
        ku.get_current_subtitle = lambda: w.current_sub
        sys.modules['resources.lib.kodi_utils'] = ku
        lib.kodi_utils = ku

        # The REAL srt.py -- fix_rtl_punctuation is what we are checking.
        spec = importlib.util.spec_from_file_location(
            'resources.lib.srt', os.path.join(LIB, 'srt.py'))
        srt = importlib.util.module_from_spec(spec)
        sys.modules['resources.lib.srt'] = srt
        spec.loader.exec_module(srt)
        lib.srt = srt
        w.srt = srt

        tr = types.ModuleType('resources.lib.translate')
        tr._QUIET = False

        def set_quiet(v):
            tr._QUIET = bool(v)
            w.quiet_seen.append(bool(v))
        tr.set_quiet = set_quiet

        def _extract(info, lang, track_num=None, deadline_s=900.0,
                     progress_cb=None, allow_http=True):
            w.extract_args = {'info': info, 'lang': lang,
                              'deadline_s': deadline_s,
                              'allow_http': allow_http,
                              'quiet_during': tr._QUIET}
            if w.extract is None:
                return None
            p = os.path.join(w.home, 'embedded_he.srt')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(w.extract)
            return p
        tr._extract_embedded_srt = _extract
        tr._embedded_translation_policy = lambda: w.policy

        def _decode(link):
            import json
            import urllib.parse
            try:
                return json.loads(urllib.parse.unquote(link))
            except Exception:
                return None
        tr._decode_link = _decode
        sys.modules['resources.lib.translate'] = tr
        lib.translate = tr
        w.translate = tr

        spec = importlib.util.spec_from_file_location(
            'resources.lib.embedded_rtl', os.path.join(LIB, 'embedded_rtl.py'))
        mod = importlib.util.module_from_spec(spec)
        sys.modules['resources.lib.embedded_rtl'] = mod
        spec.loader.exec_module(mod)
        return mod


EMB_LINK = '%7B%22type%22%3A%22engine%22%2C%22embedded%22%3Atrue%7D'   # {"type":"engine","embedded":true}
AI_LINK = '%7B%22type%22%3A%22ai%22%7D'                                # {"type":"ai"}

# ---- 1. happy path --------------------------------------------------------
w = World(current_sub=EMB_LINK)
st = w.install().repair()
check('happy path returns delivered', st == 'delivered', st)
check('happy path handed the player a file', len(w.subtitles_set) == 1,
      repr(w.subtitles_set))
if w.subtitles_set:
    body = open(w.subtitles_set[0], encoding='utf-8').read()
    check('the delivered file is RTL-wrapped',
          '‫' in body and '‬' in body, repr(body[:120]))
    check('the delivered text keeps the mark at the logical end',
          '‫אתה מאמין לזה?‬' in body, repr(body[:200]))
    check('the delivered file still has both cues', body.count('-->') == 2,
          repr(body))
    check('timings are untouched', '00:00:04,000 --> 00:00:06,000' in body)
check('the user was told once', len(w.notified) == 1, repr(w.notified))
check('extraction ran quiet', w.extract_args and w.extract_args['quiet_during'],
      repr(w.extract_args))
check('quiet was restored afterwards', w.translate._QUIET is False)
check('asked for Hebrew', w.extract_args and w.extract_args['lang'] == 'he')

# ---- 2. a second fire for the same file must not re-extract ---------------
w2 = World(current_sub=EMB_LINK)
mod2 = w2.install()
mod2.repair()
before = dict(w2.extract_args)
w2.extract_args = None
w2.calls = 0
st = mod2.repair()
check('a repeat fire for the same file is refused', st == 'already', st)
check('the repeat did not re-extract', w2.extract_args is None,
      repr(w2.extract_args))
check('the first run recorded the file as done',
      open(os.path.join(w2.home, 'embedded_rtl.lock'),
           encoding='utf-8').read().startswith('done\n'),
      open(os.path.join(w2.home, 'embedded_rtl.lock'), encoding='utf-8').read())

# ---- 3. a DIFFERENT file is not mistaken for a repeat ---------------------
w3 = World(current_sub=EMB_LINK)
mod3 = w3.install()
mod3.repair()
w3.playing = w3.playing_after = 'http://cdn/other.mkv'
w3.calls = 0
st = mod3.repair()
check('a different file is repaired, not skipped', st == 'delivered', st)

# ---- 4. the user's setting is obeyed -------------------------------------
for mode, pol, want in (
        ('off', {'mode': 'off', 'enabled': False, 'try_extract': False,
                 'allow_http': False}, 'disabled'),
        ('align_only', {'mode': 'align_only', 'enabled': True,
                        'try_extract': False, 'allow_http': True}, 'disabled'),
        ('local_only', {'mode': 'local_only', 'enabled': True,
                        'try_extract': True, 'allow_http': False},
         'http_not_allowed')):
    w4 = World(policy=pol, current_sub=EMB_LINK)
    st = w4.install().repair()
    check('mode %s refuses (%s)' % (mode, want), st == want, st)
    check('mode %s never extracted' % mode, w4.extract_args is None)
    check('mode %s never touched the player' % mode, not w4.subtitles_set)

# local_only on a LOCAL file must still work
w4b = World(playing='/storage/movie.mkv', current_sub=EMB_LINK,
            policy={'mode': 'local_only', 'enabled': True,
                    'try_extract': True, 'allow_http': False})
st = w4b.install().repair()
check('local_only still repairs a local file', st == 'delivered', st)

# ---- 5. playback moved on mid-extraction ---------------------------------
w5 = World(current_sub=EMB_LINK, playing_after='http://cdn/next_episode.mkv')
st = w5.install().repair()
check('a new file mid-extraction is not overwritten', st == 'moved_on', st)
check('moved_on delivered nothing', not w5.subtitles_set)

# ---- 6. the user picked something else -----------------------------------
w6 = World(current_sub=AI_LINK)
st = w6.install().repair()
check("another subtitle picked meanwhile is not stomped", st == 'superseded',
      st)
check('superseded delivered nothing', not w6.subtitles_set)

# ---- 7. nothing to repair ------------------------------------------------
w7 = World(current_sub=EMB_LINK)
mod7 = w7.install()
already = mod7.repair.__globals__  # noqa: F841  (keep the module alive)
w7b = World(current_sub=EMB_LINK, extract='')
st = w7b.install().repair()
check('an empty extraction is refused', st in ('no_text', 'no_change'), st)
check('an empty extraction delivered nothing', not w7b.subtitles_set)

w7c = World(current_sub=EMB_LINK, extract=None)
st = w7c.install().repair()
check('a failed extraction is refused', st == 'no_text', st)

# ---- 8. not playing ------------------------------------------------------
w8 = World(playing_video=False)
st = w8.install().repair()
check('nothing playing -> no work', st == 'not_playing', st)
check('nothing playing never extracted', w8.extract_args is None)

# ---- 9. Kodi's OWN subtitle controls, which our record never sees ---------
# moransubs.current_sub is written only by our pick flows. If the user reaches
# for the remote during the minutes this runs, that record still says
# "embedded" -- so these two cases are the difference between respecting the
# user and overriding them.
w9 = World(current_sub=EMB_LINK, subs_enabled=False)
st = w9.install().repair()
check('subtitles turned off natively are not turned back on',
      st == 'subs_off', st)
check('subs_off delivered nothing', not w9.subtitles_set)

w9b = World(current_sub=EMB_LINK, active_sub='English')
st = w9b.install().repair()
check('a native switch to another language is respected',
      st == 'superseded', st)
check('the native switch delivered nothing', not w9b.subtitles_set)

for name in ('heb', 'Hebrew', 'he', 'iw'):
    w9c = World(current_sub=EMB_LINK, active_sub=name)
    st = w9c.install().repair()
    check('%r still counts as Hebrew' % name, st == 'delivered', st)

# An empty answer from the player must not block the repair (fail-open).
w9d = World(current_sub=EMB_LINK, active_sub='')
st = w9d.install().repair()
check('an unknown active subtitle does not block delivery',
      st == 'delivered', st)

# ---- 10. a transient failure must not disable the file for the session ----
w10 = World(current_sub=EMB_LINK, extract=None)
mod10 = w10.install()
check('the extraction failed', mod10.repair() == 'no_text')
w10.extract = EMB_SRT
w10.calls = 0
st = mod10.repair()
check('re-picking after a failure tries again', st == 'delivered', st)

# ...but a settled outcome IS remembered.
w10b = World(current_sub=EMB_LINK)
mod10b = w10b.install()
mod10b.repair()
w10b.calls = 0
check('a delivered file is not repaired twice', mod10b.repair() == 'already')

# ---- 11. two processes cannot both extract the same file ------------------
# The lock is what stands between this feature and the failure mode that
# closed a movie in the field, so it is tested as a LOCK -- a second caller
# arriving while the first still holds it -- not as a status string.
w11 = World(current_sub=EMB_LINK)
mod11 = w11.install()
lock = os.path.join(w11.home, 'embedded_rtl.lock')
with open(lock, 'w', encoding='utf-8') as f:
    f.write('busy\n%r\n%s\n' % (__import__('time').time(), w11.playing))
st = mod11.repair()
check('a live claim on this file blocks a second extraction', st == 'busy', st)
check('the blocked call never extracted', w11.extract_args is None)

# A claim stamped slightly in the FUTURE is still a live claim. Rounding the
# timestamp forward when writing it is enough to produce this, and the first
# version of the lock reclaimed it -- exactly the double extraction the lock
# exists to stop. Found by this suite, not by review.
w11f = World(current_sub=EMB_LINK)
mod11f = w11f.install()
with open(os.path.join(w11f.home, 'embedded_rtl.lock'), 'w',
          encoding='utf-8') as f:
    f.write('busy\n%r\n%s\n'
            % (__import__('time').time() + 5, w11f.playing))
st = mod11f.repair()
check('a claim dated in the future is treated as live', st == 'busy', st)
check('the future-dated claim blocked the extraction',
      w11f.extract_args is None)

# A claim old enough to belong to a killed process is reclaimed.
w11b = World(current_sub=EMB_LINK)
mod11b = w11b.install()
with open(os.path.join(w11b.home, 'embedded_rtl.lock'), 'w',
          encoding='utf-8') as f:
    f.write('busy\n%.1f\n%s\n'
            % (__import__('time').time() - 100000, w11b.playing))
st = mod11b.repair()
check('a stale claim is reclaimed, not obeyed forever', st == 'delivered', st)

# A live claim left by the PREVIOUS file must not block the current one.
w11c = World(current_sub=EMB_LINK)
mod11c = w11c.install()
with open(os.path.join(w11c.home, 'embedded_rtl.lock'), 'w',
          encoding='utf-8') as f:
    f.write('busy\n%.1f\nhttp://cdn/the_previous_movie.mkv\n'
            % __import__('time').time())
st = mod11c.repair()
check("a previous file's claim does not block this one", st == 'delivered', st)

# ---- 12. the WIRING, by behaviour -----------------------------------------
# The first version of this section grepped the source for the call. A copy of
# subs_engine_bridge with an early `return True` above the block passed it
# while firing nothing -- the string was still in the file. So call the real
# function and count what it actually does.
import types as _types


def wiring(lang):
    w = World()
    w.install()
    fired = []
    stub = _types.ModuleType('resources.lib.embedded_rtl')
    stub.fire = lambda: fired.append(1) or True
    sys.modules['resources.lib.embedded_rtl'] = stub
    sys.modules['resources.lib'].embedded_rtl = stub
    spec = importlib.util.spec_from_file_location(
        'resources.lib.subs_engine_bridge', os.path.join(LIB, 'subs_engine_bridge.py'))
    seb = importlib.util.module_from_spec(spec)
    sys.modules['resources.lib.subs_engine_bridge'] = seb
    spec.loader.exec_module(seb)
    ok = seb.select_embedded(0, lang=lang)
    return ok, len(fired)


ok, n = wiring('he')
check('select_embedded reports success for a Hebrew pick', ok is True)
check('a Hebrew pick really fires the repair (once)', n == 1, 'fired %d' % n)
ok, n = wiring('heb')
check("Kodi's own 'heb' spelling fires it too", n == 1, 'fired %d' % n)
ok, n = wiring('en')
check('an English embedded pick fires nothing', n == 0, 'fired %d' % n)
ok, n = wiring(None)
check('an unspecified language fires nothing', n == 0, 'fired %d' % n)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
