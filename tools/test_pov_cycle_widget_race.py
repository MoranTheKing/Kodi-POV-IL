#!/usr/bin/env python3
"""Taking POV away must not land on a home screen that is still loading.

TWO FIELD REPORTS, one a photo of the wizard's error viewer and one a log,
both `RuntimeError: Unknown addon id 'plugin.video.pov'` raised at module
import inside the add-on's own control.py -- and the timestamps put both
tracebacks inside the window this build opens on purpose:

    14:59:25.736  traceback (the movies widget)
    14:59:25.786  traceback (the tv shows widget)
    14:59:26.271  pov_reload: cycled POV -- resolvable=True

When a patcher writes, POV's warm interpreter still holds the old code, so the
fix would not take effect until the next Kodi start. Cycling the add-on makes
it re-import the same session. The cost is a second and a half in which Kodi
does not know the add-on -- and the old wait let that land whenever "home is
visible and nothing is playing", which on a COLD start is true immediately,
while the home screen is running its first pass of widget queries.

Every widget that asked POV during that window died. And because the rebuild
is triggered by the DISABLE, nothing rebuilt them afterwards: the widgets stay
empty for the session. Both reporters found their own workaround -- one
cleared the cache, the other moved to the 64-bit build -- and neither fixed
anything; both just shift startup timing.

WHAT THIS PINS:

  * the wait now needs the home screen to be QUIET, continuously, and the
    service to be old enough that the first widget pass is behind it -- and
    when it runs out of patience it gives up instead of cycling anyway, on the
    strength of the owed record that makes the next start try again;
  * the repair: when the captured container comes back empty, one skin reload,
    and ONLY once POV is resolvable again. This file's own history records
    that same reload fired 0.6s inside the window taking POV's service down
    with it, so the ordering is the whole point;
  * and the noise that made both users open the error viewer in the first
    place: asking "is Umbrella installed?" by constructing an Addon writes
    `EXCEPTION: Unknown addon id` at ERROR level before it raises. Catching it
    does not unwrite the line.

Run: python3 tools/test_pov_cycle_widget_race.py
"""
import ast
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import threading
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# --- a Kodi that answers whatever the test needs ----------------------------
class FakeKodi(object):
    """Just enough xbmc, on a virtual clock so a 3-minute wait costs nothing."""

    def __init__(self, **state):
        self.now = 0.0
        self.state = {'home': True, 'playing': False, 'updating': False,
                      'idle': 999, 'abort_at': None, 'numitems': '0',
                      'dialog': False}
        self.state.update(state)
        self.builtins = []
        self.log = []
        test = self

        class Monitor(object):
            def waitForAbort(self, secs):
                test.now += secs
                a = test.state['abort_at']
                return a is not None and test.now >= a
        self.Monitor = Monitor

    # -- the xbmc surface pov_reload uses
    def getCondVisibility(self, cond):
        if 'Window.IsVisible(home)' in cond:
            return bool(self.state['home'])
        if 'Player.HasMedia' in cond:
            return bool(self.state['playing'])
        if 'Container.IsUpdating' in cond:
            return bool(self.state['updating'])
        if 'ModalDialog' in cond:
            return bool(self.state['dialog'])
        return False

    def getGlobalIdleTime(self):
        return self.state['idle']

    def getInfoLabel(self, label):
        if '.NumItems' in label:
            return self.state['numitems']
        return ''

    def executebuiltin(self, cmd):
        self.builtins.append(cmd)

    def sleep(self, ms):
        self.now += ms / 1000.0


def load(fake):
    """pov_reload with our fake xbmc and a clock it cannot outrun."""
    for n in list(sys.modules):
        if n.split('.')[0] in ('resources', 'xbmc', 'xbmcvfs', 'xbmcaddon'):
            sys.modules.pop(n, None)
    sys.modules['xbmc'] = fake
    sys.modules['xbmcvfs'] = types.ModuleType('xbmcvfs')
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: fake.log.append(a[0] if a else '')
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location(
        'pov_reload_t', os.path.join(LIB, 'pov_reload.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # the module's clock is the fake one, so the age floor is testable
    clock = types.ModuleType('time')
    clock.time = lambda: fake.now
    m.time = clock
    m._IMPORTED_AT = 0.0
    return m


# --- 1. the wait ------------------------------------------------------------
print('=== the wait needs a settled home, not a visible one ===')
fake = FakeKodi()
mod = load(fake)
check('the module declares both halves of the floor',
      mod._MIN_AGE_SECONDS >= 30 and mod._SETTLE_SECONDS >= 10,
      'age=%s settle=%s' % (mod._MIN_AGE_SECONDS, mod._SETTLE_SECONDS))

fake = FakeKodi()          # home up, quiet, from the first instant
mod = load(fake)
mod._wait_until_idle()
check('a home that is merely VISIBLE does not release the cycle',
      fake.now >= mod._MIN_AGE_SECONDS,
      'returned after %.0fs, the age floor is %s'
      % (fake.now, mod._MIN_AGE_SECONDS))

fake = FakeKodi(updating=True)
mod = load(fake)
mod._wait_until_idle(timeout=60)
check('a container mid-update holds it off to the timeout', fake.now >= 60,
      'returned after %.0fs' % fake.now)

fake = FakeKodi(idle=0)    # the user is pressing buttons
mod = load(fake)
mod._wait_until_idle(timeout=60)
check('so does a user who is actively navigating', fake.now >= 60,
      'returned after %.0fs' % fake.now)

fake = FakeKodi(playing=True)
mod = load(fake)
mod._wait_until_idle(timeout=60)
check('and so does playback', fake.now >= 60)

# A DIALOG ON TOP IS NOT AN IDLE SCREEN, and the four conditions above cannot
# see one. Every window POV puts up while it works -- its scrape progress, its
# source list -- is a WindowXMLDialog, which floats over what is beneath. Start
# a title from a home widget and home is still visible, nothing is playing, no
# container is updating, and somebody reading a list of sources presses
# nothing. All four say idle while POV is mid-scrape in front of the user.
#
# Two field logs, one on each route in:
#
#     21:16:06  sources_results.xml   (the list is up)
#     21:16:11  cycled POV
#     21:16:12  restored home focus -> control 2000
#
#     21:41:44  progress_media.xml    (a scrape starts)
#     21:41:51  home never settled in 180s; cycling anyway
#     21:41:52  cycled POV
#
# The first took POV away from a user choosing a source and then yanked his
# focus to the home screen. The second killed a scrape seven seconds in -- the
# one he reported as "no results, and there are definitely results".
fake = FakeKodi(dialog=True)
mod = load(fake)
check('a dialog on screen is never a moment to take POV away',
      mod._wait_until_idle(timeout=100) is False,
      'released after %.0fs -- straight into somebody\'s source list'
      % fake.now)
check('...and it waited the whole budget rather than releasing early',
      fake.now >= 100, 'returned after %.0fs' % fake.now)

# AND ASKED AGAIN AT THE LAST MOMENT. The poll's last look is up to two
# seconds before the disable, and two seconds is enough to press a title.
fake = FakeKodi()
mod = load(fake)
mod._owed_path = lambda: os.path.join(tempfile.mkdtemp(prefix='dlg-'), 'o.txt')
mod._wait_until_idle = lambda timeout=180: True     # the poll said yes...
fake.state['dialog'] = True                          # ...and then this opened
_touched = []
mod._set_enabled = lambda on: _touched.append(on)
mod._capture_home_focus = lambda: _touched.append('captured')
mod._run_cycle()
check('a dialog that opens after the wait still stops the cycle',
      not _touched, 'reached %s' % _touched)

# THE CAP DOES NOT FIRE INTO THE USER'S HANDS. It used to return True here --
# 'never cycling means the patch never lands' -- and that was a real argument
# until the owed record existed. The first device to actually reach the cap
# showed what it costs. An NVIDIA Shield, three minutes of a user browsing
# without a pause long enough to count as settled, and then:
#
#     19:56:29.507  home never settled in 180s; cycling anyway
#     19:56:30.672  Unable to find plugin plugin.video.pov
#     19:56:30.673  GetDirectory - Error getting plugin://...Disney+...
#     19:56:31.037  cycled POV -- resolvable=True
#
# He pressed a tile 1.2 seconds into the window and Kodi dropped him in the
# bare Videos root, because it could not resolve the add-on the tile points
# at. The cap did not protect anyone; it just moved the damage to the one
# moment the user was certainly watching -- three minutes of continuous
# activity is the definition of a user who is looking at the screen.
#
# So the cap gives up, and the debt on disk is what makes that safe: the
# patch costs one session, not forever.
_cap_dir = tempfile.mkdtemp(prefix='cap-')
try:
    fake = FakeKodi(updating=True)
    mod = load(fake)
    mod._owed_path = lambda: os.path.join(_cap_dir, 'owed.txt')
    mod._mark_owed(True)
    check('the cap gives up rather than cycling into a busy screen',
          mod._wait_until_idle(timeout=60) is False,
          'a True here is a 1.5s hole punched under whatever the user is '
          'pressing right now')

    # and the half that makes giving up affordable: the run leaves without
    # touching POV, and the debt it did not pay is still on disk.
    _touched = []
    mod._set_enabled = lambda on: _touched.append(on)
    mod._capture_home_focus = lambda: _touched.append('captured')
    mod._wait_until_idle = lambda timeout=180: False
    mod._run_cycle()
    check('...without disabling POV on the way out', not _touched,
          'reached %s after a wait that said no' % _touched)
    check('...and the debt it did not pay is still owed',
          mod.cycle_owed() is True,
          'a forgotten debt means POV keeps the pre-patch code for good')
finally:
    shutil.rmtree(_cap_dir, ignore_errors=True)

fake = FakeKodi(abort_at=20)
mod = load(fake)
check('an abort stops it', mod._wait_until_idle() is False)

# A SCREEN WE CANNOT READ IS NOT A SCREEN WE KNOW IS QUIET. The old body
# guessed 'quiet' when the infolabel calls raised, and this rewrite inherited
# it -- which would re-open the very race it exists to close, on exactly the
# devices too confused to answer. Guessing the other way costs only time, and
# the cap means the cycle still happens.
fake = FakeKodi()
mod = load(fake)


def _raises(cond):
    raise RuntimeError('this box cannot answer')


fake.getCondVisibility = _raises
mod._wait_until_idle(timeout=60)
check('a screen that cannot be read is treated as NOT quiet', fake.now >= 60,
      'released after %.0fs -- an unreadable screen was assumed safe'
      % fake.now)
check('...and the dialog question answers the cautious way too',
      mod._dialog_up() is True,
      'a box that cannot say whether a dialog is up must not be cycled')

# The quiet stretch has to be CONTINUOUS: a screen that goes quiet, twitches,
# and goes quiet again has not settled.
fake = FakeKodi()
mod = load(fake)
_real_cond = fake.getCondVisibility


def _flapping(cond):
    if 'Container.IsUpdating' in cond:
        return int(fake.now) % 10 < 4      # busy 4s in every 10
    return _real_cond(cond)


fake.getCondVisibility = _flapping
mod._wait_until_idle(timeout=200)
check('a screen that keeps twitching never counts as settled',
      fake.now >= 200, 'returned after %.0fs' % fake.now)


# --- 2. the repair ----------------------------------------------------------
print()
print('=== the repair, and its ordering ===')
fake = FakeKodi(numitems='0')
mod = load(fake)
check('an empty container after the cycle is reported as empty',
      mod._restore_home_focus((9000, 2)) is False)
fake = FakeKodi(numitems='7')
mod = load(fake)
check('a container that refilled is reported as refilled',
      mod._restore_home_focus((9000, 2)) is True)
check('...and focus is restored either way',
      any('SetFocus' in c for c in fake.builtins))
fake = FakeKodi()
mod = load(fake)
check('nothing captured means nothing claimed',
      mod._restore_home_focus(None) is None)

fake = FakeKodi(numitems='7')
mod = load(fake)
mod._is_resolvable = lambda: True
check('the repair reloads the skin when POV is resolvable',
      mod._repair_home_widgets((9000, 2)) is True
      and any('ReloadSkin' in c for c in fake.builtins))
check('...exactly once', sum('ReloadSkin' in c for c in fake.builtins) == 1)

fake = FakeKodi(numitems='7')
mod = load(fake)
mod._is_resolvable = lambda: False
check('THE ORDERING: it refuses to reload while POV is unresolvable',
      mod._repair_home_widgets((9000, 2)) is False
      and not any('ReloadSkin' in c for c in fake.builtins),
      'this exact reload, fired inside the window, is what took POV down')

# and the wiring: the repair must be reached only from the empty answer.
_src = io.open(os.path.join(LIB, 'pov_reload.py'), encoding='utf-8').read()
_tree = ast.parse(_src)
_run = [f for f in ast.walk(_tree) if isinstance(f, ast.FunctionDef)
        and f.name == '_run_cycle']
check('_run_cycle was found to inspect', len(_run) == 1)
_calls = [n for n in ast.walk(_run[0]) if isinstance(n, ast.Call)
          and isinstance(n.func, ast.Name)
          and n.func.id == '_repair_home_widgets']
check('the cycle calls the repair', len(_calls) == 1)
_guarded = [n for n in ast.walk(_run[0]) if isinstance(n, ast.If)
            and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == '_repair_home_widgets'
                    for c in ast.walk(n))
            and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == '_restore_home_focus'
                    for c in ast.walk(n.test))]
check('...only on the empty answer, never unconditionally', len(_guarded) == 1,
      'an unconditional reload flashes the home screen for every user whose '
      'widgets were fine')


# --- 3. the error lines nobody needed ---------------------------------------
print()
print('=== asking "is it installed?" without writing an error line ===')
_ap = io.open(os.path.join(LIB, 'addon_presence.py'), encoding='utf-8').read()
_ap_tree = ast.parse(_ap)
_inst = [f for f in ast.walk(_ap_tree) if isinstance(f, ast.FunctionDef)
         and f.name == 'installed']
check('addon_presence.installed exists', len(_inst) == 1)
check('...and never constructs an Addon',
      not [n for n in ast.walk(_inst[0]) if isinstance(n, ast.Call)
           and isinstance(n.func, ast.Attribute) and n.func.attr == 'Addon'],
      'Kodi logs the failure before it raises; that is the whole point')

# THE SIXTH AND SEVENTH SITES, found a release later and in the worst place.
# The two mirrors ask POV and Umbrella for their tokens through a shared
# _reader(addon_id), and the keeper thread calls them EVERY SIXTY SECONDS for
# as long as Kodi is up. On a device without Umbrella that was one
# `EXCEPTION: Unknown addon id 'plugin.video.umbrella'` per minute, at ERROR,
# forever -- a field log carries them a minute apart, 19:54:55 and 19:55:55,
# on a device whose only fault was not having an optional add-on. The five
# below were startup-only; these two never stop.
SITES = {
    'favourites_personal_tiles_patcher.py': ('_umbrella_installed',),
    'af3_home_patcher.py': ('_umbrella_installed',),
    'umbrella_setup_patcher.py': ('_addon', 'ensure_coco_providers'),
    'umbrella_language_patcher.py': ('_umbrella_addon',),
    'mdblist_umbrella_mirror.py': ('_reader',),
    'trakt_umbrella_mirror.py': ('_reader',),
}
for fn, names in sorted(SITES.items()):
    src = io.open(os.path.join(LIB, fn), encoding='utf-8').read()
    tree = ast.parse(src)
    found = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
             and f.name in names]
    check('%s: the presence tests were found' % fn,
          len(found) == len(names),
          'looked for %s, found %s' % (list(names), [f.name for f in found]))
    bad = [f.name for f in found for n in ast.walk(f)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == 'Addon']
    check('%s: none of them constructs an Addon to ask' % fn, not bad,
          'still constructing in: %s' % bad)

# The whole tree: no OPTIONAL add-on is probed by construction any more.
OPTIONAL = ('plugin.video.umbrella', 'script.module.cocoscrapers')
leaks = []
for root, _dirs, files in os.walk(LIB):
    for fn in files:
        if not fn.endswith('.py') or fn == 'pool.py':
            continue
        src = io.open(os.path.join(root, fn), encoding='utf-8').read()
        for n in ast.walk(ast.parse(src)):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == 'Addon' and n.args
                    and isinstance(n.args[0], ast.Constant)
                    and n.args[0].value in OPTIONAL):
                leaks.append('%s:%s' % (fn, n.lineno))
check('no optional add-on is probed by constructing an Addon anywhere',
      not leaks, 'still doing it at %s' % leaks)

# The scan above only sees a LITERAL add-on id. Both mirrors take the id as a
# parameter, so a bare construction there is invisible to it -- which is
# exactly how the per-minute error line survived the first pass. Name them.
for fn in ('mdblist_umbrella_mirror.py', 'trakt_umbrella_mirror.py'):
    src = io.open(os.path.join(LIB, fn), encoding='utf-8').read()
    tree = ast.parse(src)
    reader = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)
              and f.name == '_reader']
    check('%s: _reader was found' % fn, len(reader) == 1)
    if reader:
        check('%s: it asks through addon_presence' % fn,
              [n for n in ast.walk(reader[0]) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute)
               and n.func.attr == 'addon'
               and isinstance(n.func.value, ast.Name)
               and n.func.value.id == 'addon_presence'],
              'a bare Addon(addon_id) here is an ERROR line every 60 seconds '
              'for the whole time Kodi is up')
        check('%s: and never constructs one itself' % fn,
              not [n for n in ast.walk(reader[0]) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr == 'Addon'])

# --- 4. the longer wait must not starve the callers that block on it -------
# ARMING RAISES A FLAG OTHER CODE WAITS ON. Three of wait_until_settled's four
# callers are steps inside _run_build_startup_repairs, run inline on the
# service thread with a 30s budget each that is NOT shared. Arming before them
# meant each could spend its whole budget waiting for a cycle that had not
# started, come back False and leave its work for the next boot -- half a
# minute apiece, for nothing. Survivable while the cycle waited only for the
# home window to appear; not once it waits for the home screen to settle.
print()
print('=== the cycle is armed after the work that blocks on it ===')
_svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                            'service.py'), encoding='utf-8').read()
_arms = [m for m in re.finditer(r'pov_reload\.reload_if_patched\(\)', _svc)]
check('the cycle is armed in exactly one place', len(_arms) == 1,
      'found %d' % len(_arms))
# INDENTATION-AGNOSTIC. The call is wrapped in a try/except now -- a repair
# step raising SystemExit used to take main() down with it, and everything
# below that line is what starts the subtitle service -- so pinning it to a
# fixed indent pinned a detail nobody promised.
_repairs = [m for m in re.finditer(r'^\s*_run_build_startup_repairs\(\)',
                                   _svc, re.M)]
check('the build repair pass was found', len(_repairs) == 1)
if _arms and _repairs:
    check('arming comes AFTER the pass whose steps block on it',
          _arms[0].start() > _repairs[0].start(),
          'armed first: every guarded step in the pass pays its full budget '
          'waiting for a cycle that has not begun')
    _notes = [m.start() for m in
              re.finditer(r'pov_reload\.note_patched\(\)', _svc)]
    check('every note_patched is seen before the one question about it',
          _notes and all(n < _arms[0].start() for n in _notes),
          'a patcher that arms after the question is never cycled at all')

# AND THE PROPERTY THAT MAKES THE LONGER WAIT SAFE AT ALL: running out of
# patience is not evidence that POV came back. If this ever returned True on
# timeout, a guarded skin reload would fire straight into the window.
fake = FakeKodi()
mod = load(fake)
mod._armed = True
mod._is_installed = lambda budget=None: True
mod._is_resolvable = lambda: False
check('wait_until_settled reports NOT SAFE when it runs out of time',
      mod.wait_until_settled(timeout=2) is False,
      'a bound that reports safe is a guard that fails open')

# --- 5. NOBODY WAITS FOR ANY OF THIS ---------------------------------------
# The wait got three times longer, so the question that matters is who pays
# for it. The answer has to be nobody: the whole deferral runs on a daemon
# thread, and the only thing on the service's own thread is starting it.
# A version that ever ran the cycle inline would turn a patch into a minute
# of a Kodi that looks stuck -- which is how a build gets a reputation.
print()
print('=== the wait costs the user nothing ===')
_req = [f for f in ast.walk(_tree) if isinstance(f, ast.FunctionDef)
        and f.name == 'request_reload']
check('request_reload was found', len(_req) == 1)
if _req:
    _starts = [n for n in ast.walk(_req[0]) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute)
               and n.func.attr == 'start']
    check('it starts a thread and returns', len(_starts) == 1)
    _inline = [n for n in ast.walk(_req[0]) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name)
               and n.func.id in ('_deferred_cycle', '_run_cycle',
                                 '_wait_until_idle')]
    check('and never runs the cycle or the wait on the caller\'s thread',
          not _inline,
          'the service thread would block for the whole settle window')
    _daemon = [k for n in ast.walk(_req[0]) if isinstance(n, ast.Call)
               for k in n.keywords if k.arg == 'daemon']
    check('...on a daemon thread, so quitting Kodi is never held up',
          len(_daemon) == 1)

# And the cycle only ever lands while the user is sitting still on the home
# screen: not mid-navigation, not on another window. The rebuild it causes is
# visible, and this is what keeps it out of the user's way.
for _label, _kw in (('while the user is on another window', {'home': False}),
                    ('while the user is pressing keys', {'idle': 0}),
                    ('while something is playing', {'playing': True})):
    fake = FakeKodi(**_kw)
    mod = load(fake)
    mod._wait_until_idle(timeout=100)
    check('the rebuild is never sprung %s' % _label, fake.now >= 100,
          'released after %.0fs' % fake.now)

# --- 6. A CYCLE THAT DID NOT RUN IS NOT A CYCLE THAT IS FORGIVEN -----------
# The owner asked the right question about the longer wait: what happens to
# someone who never sits still, or who quits Kodi during it? The wait itself
# always ends -- the cap sees to that. The real hole was afterwards: the next
# start finds every patch already on disk, writes nothing, and therefore never
# arms, so an owed cycle was lost for good and POV kept the pre-patch code
# until some future release happened to touch it again. Ten seconds of
# exposure hid that. Three minutes does not.
#
# The answer is not to freeze the screen until it works. It is to not forget.
print()
print('=== an owed cycle survives a quit ===')
_owed_dir = tempfile.mkdtemp(prefix='owed-')
fake = FakeKodi()
mod = load(fake)
mod._owed_path = lambda: os.path.join(_owed_dir, 'owed.txt')
try:
        # A LINE THAT COMPILED AND WAS STILL WRONG. An edit glued two module-level
    # assignments into `_cycled = False_pending = False`, which is a perfectly
    # legal chained assignment to a variable named False_pending -- so ast
    # parsed it, the import succeeded, and `_pending` simply never existed.
    # reload_if_patched raised NameError into service.py's bare except, and
    # the cycle silently never happened again. Found because this section
    # calls it; the eight checks above never did.
    check('every flag the module reads actually exists',
          all(hasattr(mod, n) for n in
              ('_pending', '_cycled', '_armed', '_cycling')),
          'missing: %s' % [n for n in ('_pending', '_cycled', '_armed',
                                       '_cycling') if not hasattr(mod, n)])
    check('nothing is owed on a clean device', mod.cycle_owed() is False)
    check('...so a run that patched nothing does not cycle',
          mod.reload_if_patched() is False)

    mod._pending = True
    mod._is_installed = lambda budget=None: True
    _started = []
    mod._deferred_cycle = lambda: _started.append(1)
    mod.request_reload()
    check('arming writes the debt BEFORE the thread starts',
          mod.cycle_owed() is True)

    # a Kodi that dies here leaves the record behind: next process, nothing
    # patched, and it must still cycle.
    fake2 = FakeKodi()
    mod2 = load(fake2)
    mod2._owed_path = lambda: os.path.join(_owed_dir, 'owed.txt')
    mod2._is_installed = lambda budget=None: True
    mod2._deferred_cycle = lambda: None
    check('a fresh process starts with nothing pending', mod2._pending is False)
    check('...and cycles anyway, because the debt is on disk',
          mod2.reload_if_patched() is True)

    # paid only by a cycle that ran
    mod2._mark_owed(False)
    check('a completed cycle clears it', mod2.cycle_owed() is False)

    # and a debt to an add-on that is gone is not a debt
    mod2._mark_owed(True)
    mod3 = load(FakeKodi())
    mod3._owed_path = lambda: os.path.join(_owed_dir, 'owed.txt')
    mod3._is_installed = lambda budget=None: False
    check('POV uninstalled: the debt is forgotten, not retried forever',
          mod3.reload_if_patched() is False and mod3.cycle_owed() is False)
finally:
    shutil.rmtree(_owed_dir, ignore_errors=True)

# The debt is cleared in exactly one place in _run_cycle, and it is the same
# branch that proves POV came back. Every other exit leaves it standing.
_clears = [n for n in ast.walk(_run[0]) if isinstance(n, ast.Call)
           and isinstance(n.func, ast.Name) and n.func.id == '_mark_owed']
check('_run_cycle clears the debt in exactly one place', len(_clears) == 1)
check('...and only with False, never re-arming itself',
      all(a.value is False for c in _clears for a in c.args
          if isinstance(a, ast.Constant)))


# --- switching POV off must be PROVED, not assumed ------------------------
# _set_enabled read `'"error"' not in reply`, which calls an EMPTY reply a
# success. That was harmless while nobody looked at the answer; it stopped
# being harmless when _run_cycle started refusing to claim a cycle on False,
# because a silent empty reply would then mean "we switched POV off" for a
# switch that never happened -- POV stays resolvable, the debt is cleared, and
# the patch never lands, which is the exact bug the return check was added to
# prevent. Executed against the real function, not read.
print()
print('=== a JSON-RPC call that answered nothing did not succeed ===')


class _RPC(object):
    def __init__(self, reply):
        self.reply, self.seen = reply, []

    def executeJSONRPC(self, payload):
        self.seen.append(payload)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


_m = load(FakeKodi())
for label, reply, want in (
        ('a real success', '{"id":1,"jsonrpc":"2.0","result":"OK"}', True),
        ('an empty string', '', False),
        ('None', None, False),
        ('an error envelope',
         '{"id":1,"jsonrpc":"2.0","error":{"code":-32602,"message":"no"}}',
         False),
        ('a reply with neither member', '{"id":1,"jsonrpc":"2.0"}', False),
        ('a raising call', RuntimeError('boom'), False)):
    _m.xbmc = _RPC(reply)
    got = _m._set_enabled(False)
    check('%s -> %s' % (label, want), got is want, 'got %r' % got)

_m.xbmc = _RPC('{"id":1,"jsonrpc":"2.0","result":"OK"}')
_m._set_enabled(True)
check('...and it asks about POV, with the flag it was given',
      'plugin.video.pov' in _m.xbmc.seen[0]
      and '"enabled": true' in _m.xbmc.seen[0].replace('True', 'true'),
      _m.xbmc.seen[0])


# --- a debt that can never be paid must eventually shout ------------------
# THE REVIEW'S FAIR QUESTION about the new "never over a dialog" rule: what
# happens on a device where the quiet moment never comes? The cycle is
# deferred, the next start defers it again, and nothing in the log reads as a
# problem -- for ever. The owed file now carries a count and the line stops
# being INFO once it is clearly not a coincidence.
print()
print('=== an owed cycle that keeps failing stops whispering ===')
_dir = tempfile.mkdtemp(prefix='povowed-')
try:
    _m = load(FakeKodi())
    _m._owed_path = lambda: os.path.join(_dir, 'owed.txt')
    _levels = []
    _m._log = lambda msg, level='INFO': _levels.append((level, msg))
    check('a fresh device owes nothing', _m._owed_attempts() == 0)
    for n in range(1, _m._OWED_SHOUT_AFTER + 2):
        _levels[:] = []
        _m._note_owed_attempt('a dialog is on screen')
        want = 'WARNING' if n >= _m._OWED_SHOUT_AFTER else 'INFO'
        check('attempt %d is logged at %s' % (n, want),
              _levels and _levels[-1][0] == want,
              str(_levels[-1] if _levels else None))
        check('...and the count survives to the next start',
              _m._owed_attempts() == n, str(_m._owed_attempts()))
    check('the warning says how many starts it has been',
          str(_m._OWED_SHOUT_AFTER) in _levels[-1][1]
          or str(_m._OWED_SHOUT_AFTER + 1) in _levels[-1][1],
          _levels[-1][1])
    check('...and the debt itself is still owed', _m.cycle_owed() is True)

    # AND THROUGH THE REAL CHAIN, not just by calling _note_owed_attempt in a
    # loop. THE BUG A REVIEW FOUND: request_reload() runs at every start,
    # BEFORE the thread that defers the cycle, and its bare _mark_owed(True)
    # defaulted attempts to 0 -- so every boot reset the tally before anything
    # could add to it, the count never got past 1, and the warning was
    # unreachable. Testing the escalation in isolation could not see it. This
    # drives whole boots.
    _levels[:] = []
    _m._mark_owed(False)
    _seen = []
    for boot in range(1, _m._OWED_SHOUT_AFTER + 2):
        _m._cycled = False              # a fresh process
        _m._armed = False
        # request_reload STARTS A THREAD running _deferred_cycle. Calling it
        # inline as well ran the attempt twice per boot, from two threads, on
        # one file -- which is how the shared `.tmp` name in _mark_owed was
        # found. Let the thread be the only one that runs it, and wait.
        _done = threading.Event()

        def _cycle():
            try:
                _m._note_owed_attempt('a dialog is up')
            finally:
                _done.set()
        _m._deferred_cycle = _cycle
        _m.request_reload()
        _done.wait(5)
        _seen.append(_m._owed_attempts())
    check('the count survives request_reload on every boot',
          _seen == list(range(1, _m._OWED_SHOUT_AFTER + 2)), str(_seen))
    check('...so the warning actually fires across real boots',
          any(lv == 'WARNING' for lv, _msg in _levels),
          'never escalated across %d boots' % len(_seen))
    # An owed file from a release that did not write a count reads as zero
    # rather than raising, so an upgrade does not lose the debt.
    with open(os.path.join(_dir, 'owed.txt'), 'w', encoding='utf-8') as _f:
        _f.write('plugin.video.pov\n')
    check('a file from an older release reads as zero, not as an error',
          _m._owed_attempts() == 0 and _m.cycle_owed() is True)
    _m._mark_owed(False)
    check('paying the debt clears the count with it',
          _m._owed_attempts() == 0 and _m.cycle_owed() is False)
finally:
    shutil.rmtree(_dir, ignore_errors=True)


# --- two writers at once, which the boot-loop test CANNOT see --------------
# THE REVIEW'S POINT, and it was right: the loop above waits for each boot's
# thread to finish before starting the next, so the two writers never overlap
# and the test passes against the SHARED-tmp version that the fix replaced. It
# is a good test of the count-carrying-forward bug and no test at all of the
# race. This is the race: real threads, one barrier, one file.
print()
print('=== the owed record survives two writers at the same instant ===')
_dir = tempfile.mkdtemp(prefix='povrace-')
try:
    _m = load(FakeKodi())
    _m._owed_path = lambda: os.path.join(_dir, 'owed.txt')
    _m._log = lambda msg, level='INFO': None

    def hammer(mod, rounds=250, workers=6):
        """Every worker writes the same record at the same moment."""
        gate = threading.Barrier(workers)
        errors, empties = [], []

        def work(w):
            gate.wait()
            for r in range(rounds):
                try:
                    mod._mark_owed(True, attempts=w * 1000 + r)
                except Exception as e:      # noqa: BLE001 - that is the test
                    errors.append(repr(e))
                try:
                    with open(mod._owed_path(), encoding='utf-8') as f:
                        body = f.read()
                    if not body.strip():
                        empties.append(r)
                except FileNotFoundError:
                    empties.append('missing')
                except Exception as e:      # noqa: BLE001
                    errors.append(repr(e))
        ts = [threading.Thread(target=work, args=(w,)) for w in range(workers)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(60)
        strays = [n for n in os.listdir(_dir) if n.endswith('.tmp')]
        return errors, empties, strays

    _err, _empty, _stray = hammer(_m)
    check('no writer raised', not _err, str(_err[:3]))
    check('the record is never empty or missing under concurrency',
          not _empty, '%d bad reads' % len(_empty))
    check('...and no temp file is left behind', not _stray, str(_stray[:5]))
    check('...and what is left is a readable record',
          _m.cycle_owed() is True and isinstance(_m._owed_attempts(), int))

    # SABOTAGE: the shared name this replaced must FAIL the same check, or the
    # test above is proving nothing. Reinstate it and watch it break.
    _real = _m._mark_owed

    def _shared_tmp(owed, applied=True, attempts=0):
        path = _m._owed_path()
        if not owed:
            return _real(owed, applied, attempts)
        tmp = path + '.tmp'                      # the bug: one name for all
        with open(tmp, 'w', encoding='utf-8') as h:
            h.write('%s\n%d\n' % (_m.POV_ADDON_ID, attempts))
        os.replace(tmp, path)
        return True
    _m._mark_owed = _shared_tmp
    _e2, _empty2, _s2 = hammer(_m)
    check('SABOTAGE: the shared temp name really does lose writes',
          bool(_e2 or _empty2),
          'the concurrency test cannot tell the two apart, so it proves '
          'nothing about the fix')
    _m._mark_owed = _real

    # AND THE SWEEP MUST NOT EAT A LIVE WRITER'S FILE. The first version of
    # _sweep_stale_temps deleted every temp sibling it recognised -- including
    # the one another thread was between writing and renaming. That writer's
    # os.replace then failed, its update was silently lost, and the hammer
    # above could not see it: nothing raised out of _mark_owed, the record was
    # never empty, and the temp file ended up DELETED rather than left behind,
    # so "no temp file left behind" passed BECAUSE of the bug.
    _m._mark_owed(True, attempts=7)
    _live = _m._owed_path() + '.999999.1.tmp'
    with open(_live, 'w', encoding='utf-8') as _f:
        _f.write('a live writer is mid-flight here\n')
    _m._sweep_stale_temps(_m._owed_path())
    check('a temp file written just now is left alone', os.path.exists(_live),
          'the sweep deleted a file another writer was still using')
    _old = _m._owed_path() + '.111111.1.tmp'
    with open(_old, 'w', encoding='utf-8') as _f:
        _f.write('orphaned by a kill an hour ago\n')
    os.utime(_old, (0, 0))
    _m._sweep_stale_temps(_m._owed_path())
    check('...and one orphaned long ago is swept', not os.path.exists(_old))
    check('...and the record itself is never touched',
          _m.cycle_owed() is True and _m._owed_attempts() == 7)
    os.remove(_live)
finally:
    shutil.rmtree(_dir, ignore_errors=True)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
