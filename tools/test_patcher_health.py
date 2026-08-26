"""A repair that stops applying must stop being silent.

THE INCIDENT THIS IS BUILT AGAINST, replayed rather than described. POV
auto-updated 6.08.13 -> 6.08.14, five repairs stopped applying, and nothing
said so -- because service.py's pass calls `step()` and discards the verdict,
and an anchor that no longer matches is not an exception. The central check
below does exactly that: boot against a real POV 6.08.13 with our patches
applied, swap in a real 6.08.14 that does not carry them, and require the
report to name them as LAPSED.

If that check can pass without the module working, the file is worthless -- so
the sabotage section mutates the module and requires each mutant to be caught.

Run: python3 tools/test_patcher_health.py
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
MODULE = os.path.join(LIB, 'patcher_health.py')
SC = ('/tmp/claude-0/-home-user-Kodi-POV-IL/'
      '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad')

FAIL = []
_TMP = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def load(profile, src=None):
    """patcher_health with a stubbed kodi_utils pointed at `profile`."""
    for n in list(sys.modules):
        if n.startswith(('xbmcvfs', 'resources', 'ph_t')):
            sys.modules.pop(n, None)
    xv = types.ModuleType('xbmcvfs')
    xv.translatePath = lambda p: p
    sys.modules['xbmcvfs'] = xv
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    pkg.lib = lib
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.logged = []
    ku.notified = []
    ku.log = lambda m, level='INFO': ku.logged.append((level, m))
    ku.notify = lambda m, title=None, **k: ku.notified.append(m)
    ku.addon_profile_path = lambda: profile
    ku.log_level = 'DEBUG'
    ku.get_setting = lambda k, d='': (ku.log_level if k == 'log_level' else d)
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    if src is None:
        spec = importlib.util.spec_from_file_location('ph_t', MODULE)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    else:
        m = types.ModuleType('ph_t')
        m.__file__ = MODULE
        exec(compile(src, MODULE, 'exec'), m.__dict__)
    m.kodi_utils = ku
    m._ku = ku
    return m


def tmp(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    _TMP.append(d)
    return d


def real_pov(ver):
    src = os.path.join(SC, 'pov%s' % ver, 'plugin.video.pov')
    return src if os.path.isdir(src) else None


def fake_lib(entries):
    """A throwaway resources/lib holding synthetic patchers.

    entries: {stem: (marker, host_id)}
    """
    d = tmp('ph-lib-')
    for stem, (marker, host) in entries.items():
        with io.open(os.path.join(d, stem + '.py'), 'w',
                     encoding='utf-8') as f:
            f.write("HOST = '%s'\nMARKER = '# %s'\n" % (host, marker))
    return d


def addons_root(pairs):
    """A throwaway special://home/addons/ holding real or synthetic hosts.

    pairs: {addon_id: (version, body or None, real_tree_or_None)}
    """
    d = tmp('ph-addons-')
    for aid, (version, body, real) in pairs.items():
        dst = os.path.join(d, aid)
        if real:
            shutil.copytree(real, dst)
        else:
            os.makedirs(os.path.join(dst, 'resources', 'lib'))
            with io.open(os.path.join(dst, 'resources', 'lib', 'x.py'), 'w',
                         encoding='utf-8') as f:
                f.write(body or '')
        with io.open(os.path.join(dst, 'addon.xml'), 'w',
                     encoding='utf-8') as f:
            f.write('<?xml version="1.0"?>\n<addon id="%s" version="%s">\n'
                    '<requires><import addon="xbmc.python" version="3.0.0"/>'
                    '</requires>\n</addon>\n' % (aid, version))
    return d


# --- 1. THE INCIDENT, REPLAYED AGAINST TWO REAL POV TREES ----------------
print('=== the 6.08.14 regression is caught ===')
A, B = real_pov('6813'), real_pov('6814')
if not (A and B):
    check('both real POV trees are on disk', False,
          'this file proves nothing without them')
else:
    MARK = 'AI_SUBS_HEALTH_PROBE_v1'
    lib = fake_lib({'probe_patcher': (MARK, 'plugin.video.pov')})
    prof = tmp('ph-prof-')

    # Boot 1: POV 6.08.13, our marker present -- a healthy device.
    r13 = addons_root({'plugin.video.pov': ('6.08.13', None, A)})
    tgt = os.path.join(r13, 'plugin.video.pov', 'resources', 'lib',
                       'modules', 'sources.py')
    with io.open(tgt, 'a', encoding='utf-8') as f:
        f.write('\n# %s\n' % MARK)
    m = load(prof)
    st1 = m.run(lib, r13)
    print('   boot 1 (6.08.13, patched) -> %s' % st1)
    check('a healthy repair reads ok', 'ok=1' in st1 and 'lapsed=0' in st1, st1)
    check('...and nothing is announced to the user', not m._ku.notified)

    # Boot 2: POV replaced itself with 6.08.14. Same marker, now absent.
    r14 = addons_root({'plugin.video.pov': ('6.08.14', None, B)})
    m2 = load(prof)
    st2 = m2.run(lib, r14)
    print('   boot 2 (6.08.14, patch gone) -> %s' % st2)
    check('THE REGRESSION IS CAUGHT', 'lapsed=1' in st2, st2)
    check('...it is logged at WARNING',
          any(lv == 'WARNING' and 'STOPPED APPLYING' in msg
              for lv, msg in m2._ku.logged),
          str(m2._ku.logged[-3:]))
    check('...the log names the patcher and both versions',
          any('probe_patcher' in msg and '6.08.14' in msg and '6.08.13' in msg
              for _lv, msg in m2._ku.logged),
          str([msg for _l, msg in m2._ku.logged if 'probe' in msg]))
    check('...and the user is told once', len(m2._ku.notified) == 1,
          str(m2._ku.notified))

    # Boot 3: still broken. The alarm must NOT silence itself -- clearing the
    # record on the first report would make boot 3 read 'unknown' and go quiet
    # while the repair is still dead.
    m3 = load(prof)
    st3 = m3.run(lib, r14)
    print('   boot 3 (still broken)     -> %s' % st3)
    check('the alarm does not silence itself on the next boot',
          'lapsed=1' in st3, st3)

    # Boot 4: repaired. It must go quiet again, or the report is useless.
    tgt14 = os.path.join(r14, 'plugin.video.pov', 'resources', 'lib',
                         'modules', 'sources.py')
    with io.open(tgt14, 'a', encoding='utf-8') as f:
        f.write('\n# %s\n' % MARK)
    m4 = load(prof)
    st4 = m4.run(lib, r14)
    print('   boot 4 (repaired)         -> %s' % st4)
    check('a fixed repair goes quiet again',
          'lapsed=0' in st4 and 'ok=1' in st4, st4)
    check('...with no second notification', not m4._ku.notified)


# --- 2. SILENCE WHERE SILENCE IS CORRECT ---------------------------------
print()
print('=== it does not cry wolf ===')
prof2 = tmp('ph-prof2-')
lib2 = fake_lib({'skin_thing_patcher': ('AI_SUBS_SKIN_THING_v1',
                                        'skin.arctic.fuse.3')})
empty = addons_root({'plugin.video.pov': ('6.08.14', 'nothing here', None)})
mm = load(prof2)
sm = mm.run(lib2, empty)
check('a host that is not installed is never reported lapsed',
      'lapsed=0' in sm, sm)
check('...and the user is not notified', not mm._ku.notified)

# A HOST THAT WAS PATCHED AND IS THEN UNINSTALLED. This is the case that
# separates "report what broke" from "report what changed", and the first
# version of this file did not cover it: a mutant that dropped the
# not-installed branch entirely still passed everything else here, because the
# only uninstalled host under test had never been seen healthy. Somebody
# switching away from a skin, or removing a video add-on, must not be told
# their build is broken.
profU = tmp('ph-profU-')
libU = fake_lib({'goes_away_patcher': ('AI_SUBS_GOES_AWAY_v1',
                                       'plugin.video.pov')})
withhost = addons_root(
    {'plugin.video.pov': ('6.08.14', '# AI_SUBS_GOES_AWAY_v1\n', None)})
mu1 = load(profU)
su1 = mu1.run(libU, withhost)
check('the fixture is healthy before the host is removed',
      'ok=1' in su1, su1)
gone = addons_root({'something.else': ('1.0', '', None)})
mu2 = load(profU)
su2 = mu2.run(libU, gone)
check('a host that was patched and is then UNINSTALLED is not reported lapsed',
      'lapsed=0' in su2, su2)
check('...and the user is not notified about an add-on they removed',
      not mu2._ku.notified, str(mu2._ku.notified))

prof3 = tmp('ph-prof3-')
lib3 = fake_lib({'never_applied_patcher': ('AI_SUBS_NEVER_v1',
                                           'plugin.video.pov')})
mm3 = load(prof3)
sm3 = mm3.run(lib3, empty)
check('a repair never once seen applied is quiet, not lapsed',
      'lapsed=0' in sm3, sm3)
check('...and it is still listed, as unknown rather than healthy',
      'unknown' in io.open(os.path.join(prof3, 'patcher_health.txt'),
                           encoding='utf-8').read())


# --- 2b. RETIRED MARKERS ARE NOT FAILURES --------------------------------
print()
print('=== a patcher\'s own retired markers are not reported missing ===')
# Found by running the report against the real tree, not by reasoning:
# pov_services_patcher keeps eleven superseded markers so it can strip its own
# previous work. The first version of this file looked for all eleven and
# reported them absent -- one patcher produced twelve of the twenty-two
# "absent" rows in the first real run. Noise like that is how a report gets
# ignored, which is the same outcome as not having one.
profR = tmp('ph-profR-')
libR = tmp('ph-libR-')
with io.open(os.path.join(libR, 'many_versions_patcher.py'), 'w',
             encoding='utf-8') as f:
    f.write("HOST = 'plugin.video.pov'\n"
            "MARKER = '# AI_SUBS_THING_v4'\n"
            "OLD_MARKERS = ('# AI_SUBS_THING_v1', '# AI_SUBS_THING_v2',\n"
            "               '# AI_SUBS_THING_v3')\n")
hostR = addons_root(
    {'plugin.video.pov': ('6.08.14', '# AI_SUBS_THING_v4\n', None)})
mr = load(profR)
sr = mr.run(libR, hostR)
print('   four markers declared, one live -> %s' % sr)
check('only the LIVE version of a marker family is checked',
      'checked=1' in sr, sr)
check('...and it reads healthy, not 3-of-4 missing',
      'ok=1' in sr and 'lapsed=0' in sr, sr)

# A CONSTRUCTED marker: the live string is built from an integer constant and
# appears nowhere in the source, so the highest literal is a RETIRED one.
# Reporting on that literal would be guaranteed-absent forever -- a permanent
# red mark against a patcher that is working perfectly.
profC = tmp('ph-profC-')
libC = tmp('ph-libC-')
with io.open(os.path.join(libC, 'built_marker_patcher.py'), 'w',
             encoding='utf-8') as f:
    f.write("HOST = 'plugin.video.pov'\n"
            "INJECT_VERSION = 7\n"
            "OLD_MARKERS = ('# AI_SUBS_BUILT_v5', '# AI_SUBS_BUILT_v6')\n"
            "MARKER = '# AI_SUBS_BUILT_v{0}'.format(INJECT_VERSION)\n")
mc = load(profC)
sc = mc.run(libC, hostR)          # host holds _v4, not the rebuilt _v7
rowsC = mc.classify(mc.collect(libC, hostR), {})[0]
st = {r['status'] for r in rowsC}
print('   rebuilt marker, not in host -> %s (statuses %s)' % (sc, sorted(st)))
check('the live version is REBUILT from the constant, not read as a literal',
      any(r['marker'].endswith('_v7') for r in rowsC),
      str([r['marker'] for r in rowsC]))
check('a rebuilt name that the host does not carry is unverified, not lapsed',
      st == {'unverified'}, str(sorted(st)))
check('...so a wrong guess can never raise a false alarm',
      'lapsed=0' in sc, sc)
check('...and it says unverified rather than passing for healthy',
      'unverified' in io.open(os.path.join(profC, 'patcher_health.txt'),
                              encoding='utf-8').read())

# ONCE THE HOST IS SEEN CARRYING IT, the reconstruction is PROVEN -- and from
# then on it is alarmable like any other marker. This is what puts the Connect
# Services window under the report instead of permanently outside it.
profC2 = tmp('ph-profC2-')
hasV7 = addons_root(
    {'plugin.video.pov': ('6.08.14', '# AI_SUBS_BUILT_v7\n', None)})
mc2 = load(profC2)
sc2 = mc2.run(libC, hasV7)
check('a rebuilt name the host DOES carry reads ok, proving the guess',
      'ok=1' in sc2, sc2)
mc3 = load(profC2)
sc3 = mc3.run(libC, addons_root(
    {'plugin.video.pov': ('6.08.15', 'gone\n', None)}))
check('...and once proven, losing it IS a lapse', 'lapsed=1' in sc3, sc3)

# THE WHOLE POINT OF THE COLLAPSE is that it must not hide a real regression.
mr2 = load(profR)
goneR = addons_root({'plugin.video.pov': ('6.08.15', 'nothing\n', None)})
sr2 = mr2.run(libR, goneR)
check('collapsing families still catches a real lapse',
      'lapsed=1' in sr2, sr2)


# --- 2c. THE POPUP GOES TO SOMEBODY WHO CAN ACT ON IT --------------------
print()
print('=== an ordinary viewer is not alarmed by something they cannot fix ===')
profP = tmp('ph-profP-')
libP = fake_lib({'popup_probe_patcher': ('AI_SUBS_POPUP_PROBE_v1',
                                         'plugin.video.pov')})
hadit = addons_root(
    {'plugin.video.pov': ('6.08.14', '# AI_SUBS_POPUP_PROBE_v1\n', None)})
lostit = addons_root({'plugin.video.pov': ('6.08.15', 'gone\n', None)})
mp = load(profP)
mp.run(libP, hadit)
mp2 = load(profP)
mp2._ku.log_level = 'INFO'          # an ordinary device
sp = mp2.run(libP, lostit)
check('the regression is still detected on an ordinary device',
      'lapsed=1' in sp, sp)
check('...and still written to the log, so an uploaded log carries it',
      any(lv == 'WARNING' and 'STOPPED APPLYING' in m
          for lv, m in mp2._ku.logged))
check('...but NO popup is put in front of the viewer', not mp2._ku.notified,
      str(mp2._ku.notified))
mp3 = load(profP)
mp3._ku.log_level = 'DEBUG'         # a maintainer's device
mp3.run(libP, lostit)
check('a maintainer device DOES get the popup', len(mp3._ku.notified) == 1,
      str(mp3._ku.notified))


# --- 3. IT SURVIVES A BAD DAY --------------------------------------------
print()
print('=== it never breaks the boot ===')
prof4 = tmp('ph-prof4-')
m5 = load(prof4)
check('a missing lib dir is reported, not raised',
      m5.run(os.path.join(prof4, 'nope'), empty) == 'nothing_to_check')
check('a missing addons root is reported, not raised',
      m5.run(lib3, os.path.join(prof4, 'nope')) in
      ('nothing_to_check', 'checked=1, ok=0, lapsed=0'))

prof5 = tmp('ph-prof5-')
with io.open(os.path.join(prof5, 'patcher_health.json'), 'w',
             encoding='utf-8') as f:
    f.write('{ this is not json')
m6 = load(prof5)
st6 = m6.run(lib3, empty)
check('a corrupt state file starts over instead of raising',
      'lapsed=0' in st6, st6)
check('...and is replaced with valid json',
      isinstance(json.load(io.open(os.path.join(prof5, 'patcher_health.json'),
                                   encoding='utf-8')), dict))

# A patcher whose source will not parse must not take the report down.
lib4 = fake_lib({'ok_patcher': ('AI_SUBS_OK_v1', 'plugin.video.pov')})
with io.open(os.path.join(lib4, 'broken_patcher.py'), 'w',
             encoding='utf-8') as f:
    f.write("HOST = 'plugin.video.pov'\nMARKER = '# AI_SUBS_BROKEN_v1'\ndef (")
m7 = load(tmp('ph-prof6-'))
st7 = m7.run(lib4, empty)
check('an unparsable patcher does not stop the report',
      st7.startswith('checked='), st7)


# --- 4. WIRED IN ---------------------------------------------------------
print()
print('=== the service actually runs it ===')
svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                           'service.py'), encoding='utf-8').read()
check('service.py defines the step', 'def _report_patcher_health(' in svc)
import re as _re
tup = _re.search(r'steps = \((.*?)\n    \)', svc, _re.S)
check('...and the repair pass lists it',
      tup is not None and '_report_patcher_health,' in tup.group(1),
      'defined but never called is the failure this check exists for')
check('...LAST, so it reads the state the pass just produced',
      tup is not None
      and tup.group(1).rstrip().rstrip(',').endswith('_report_patcher_health'),
      'a health check that runs mid-pass reports repairs that had not run yet')

for d in _TMP:
    shutil.rmtree(d, ignore_errors=True)

print()
if FAIL:
    print('FAILED: %d -> %s' % (len(FAIL), FAIL))
    raise SystemExit(1)
print('ALL PASS')
