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


# --- 2d. A REPAIR THE HOST ADOPTED IS NOT A REPAIR THAT BROKE -------------
print()
print('=== "the host fixed it itself" is reported, never warned about ===')

# THIS SECTION GUARDS AN ALARM-SUPPRESSION PATH, which is the most dangerous
# kind of code in this file: a bug here does not break a feature, it makes a
# real regression silent. So every check below has its mirror -- suppressed
# when it should be, and STILL WARNING when it should be.
#
# Two arrived in one week: POV 6.09.02 rewrote its resume-cancel path to call
# progress_media() itself, and Umbrella 6.7.87 rewrote its MDBList sync cursor
# to store the server's checkpoint instead of the device wall clock. Both are
# the defects those patchers were written for. Without this, every device that
# had them applied and then updated reports two LAPSED repairs at WARNING --
# and a warning that means "nothing is wrong" is a warning nobody reads.
_ph = load('probe-hf')


def _row(hv, fixed_in='6.09.02', present=False, patcher='p', marker='M'):
    return {'patcher': patcher, 'marker': marker, 'host': 'plugin.video.pov',
            'host_version': hv, 'installed': True, 'present': present,
            'rebuilt': False, 'fixed_in': fixed_in,
            'host_fixed': _ph._at_or_above(hv, fixed_in)}


def _seen(patcher='p', marker='M', at='6.09.01'):
    return {'seen': {'%s|plugin.video.pov|%s' % (patcher, marker):
                     {'last_ok_version': at}}}


st = lambda hv, **kw: _ph.classify([_row(hv, **kw)], _seen())[0][0]['status']

check('on the host that FIXED it -> superseded', st('6.09.02') == 'superseded',
      st('6.09.02'))
check('on a LATER host -> still superseded', st('6.09.03') == 'superseded',
      st('6.09.03'))
check('on a host that still HAS the bug -> lapsed, as before',
      st('6.09.01') == 'lapsed', st('6.09.01'))
check('a rollback below the fixed version alarms again',
      st('6.08.15') == 'lapsed', st('6.08.15'))
check('a patcher with NO declaration is untouched by any of this',
      st('6.09.02', fixed_in='') == 'lapsed', st('6.09.02', fixed_in=''))
check('still present in the host -> plain ok, not superseded',
      st('6.09.02', present=True) == 'ok', st('6.09.02', present=True))

# superseded must not be counted or announced as a lapse
rows, _ = _ph.classify([_row('6.09.02')], _seen())
check('superseded is not in lapsed()', _ph.lapsed(rows) == [])
text = _ph._render(rows)
check('...and the report names the version that fixed it',
      'superseded' in text and '6.09.02' in text, text.splitlines()[-1])

# The declaration is parsed out of the real files, both spellings.
LIBSRC = lambda n: io.open(os.path.join(LIB, n + '.py'), encoding='utf-8').read()
check('the real POV patcher declares 6.09.02',
      _ph.host_fixed_in(LIBSRC('pov_resume_cancel_patcher')) == {'*': '6.09.02'})
check('the real Umbrella patcher declares 6.7.87',
      _ph.host_fixed_in(LIBSRC('umbrella_mdblist_sync_patcher')) == {'*': '6.7.87'})
check('a patcher without one declares nothing',
      _ph.host_fixed_in(LIBSRC('pov_navigator_read_patcher')) == {})
check('the per-host dict spelling parses too',
      _ph.host_fixed_in("HOST_FIXED_IN = {'plugin.video.pov': '6.09.02',\n"
                        "                 'plugin.video.umbrella': '6.7.87'}")
      == {'plugin.video.pov': '6.09.02', 'plugin.video.umbrella': '6.7.87'})

# An unreadable version must fail CLOSED -- keep warning rather than go quiet.
check('an unreadable host version does not silence the alarm',
      st('') in ('lapsed', 'not_installed') and not _ph._at_or_above('', '6.0'))
check('an unreadable declaration does not silence the alarm',
      not _ph._at_or_above('6.09.02', ''))

# The review of 0.2.521 found the suppression correct but incomplete, and every
# one of these is a case it constructed. They are pinned because each is a way
# for an alarm to go quiet, and a quiet alarm is invisible by definition.

# (a) A version segment we cannot read as a number must NOT rank. Stripping
#     non-digits inverted the order -- '6.7.9~rc2' became (6,7,92) and compared
#     ABOVE 6.7.87, silencing a repair a device still needed.
for _have, _want in (('6.7.9~rc2', '6.7.87'), ('6.09.01a2', '6.09.02'),
                     ('6.7.87~beta1', '6.7.87'), ('6.7.9-1', '6.7.87')):
    check('a pre-release version does not rank: %s vs %s' % (_have, _want),
          not _ph._at_or_above(_have, _want))
check('...while real versions still rank correctly',
      _ph._at_or_above('6.10.0', '6.9.9')
      and _ph._at_or_above('6.7.87', '6.7.87')
      and not _ph._at_or_above('6.7.86', '6.7.87'))

# (b) The declaration is read with ast, so it cannot be picked up out of a
#     string, a docstring or a comment. Same trap as the phantom marker, aimed
#     the other way: there it invented a repair, here it would silence one.
check('a declaration at column 0 inside a docstring is NOT read',
      _ph.host_fixed_in('"""\nHOST_FIXED_IN = \'6.09.02\'\n"""\n') == {})
check('a commented-out declaration is NOT read',
      _ph.host_fixed_in("# HOST_FIXED_IN = '1.0'\n") == {})
check('a commented-out pair inside the dict is NOT read',
      _ph.host_fixed_in("HOST_FIXED_IN = {  # 'plugin.video.pov': '1.0'\n"
                        "    'plugin.video.umbrella': '6.7.87'}\n")
      == {'plugin.video.umbrella': '6.7.87'})
check('a file that will not parse declares nothing',
      _ph.host_fixed_in("HOST_FIXED_IN = '6.0'\ndef (\n") == {})
check('a real assignment still is read',
      _ph.host_fixed_in("HOST_FIXED_IN = '6.09.02'\n") == {'*': '6.09.02'})

# (c) EVERY patcher whose bug the host fixed must declare it. 0.2.521 removed
#     two false alarms and left a third standing on the patcher it cited as the
#     precedent -- which teaches exactly the habit the change was meant to stop.
check('pov_alldebrid_status_fix declares 6.08.15 (its bug is 6.08.14 only)',
      _ph.host_fixed_in(LIBSRC('pov_alldebrid_status_fix'))
      == {'*': '6.08.15'})

# (d) The summary line -- the one that reaches a pasted log -- must not drop a
#     status. superseded was added without touching it, so `ok` silently fell
#     by two with nothing to account for it.
_rows_sup, _ = _ph.classify([_row('6.09.02')], _seen())
_txt = _ph._render(_rows_sup)
check('the report table counts superseded', 'superseded=1' in _txt, _txt.split(chr(10))[0])


print()
print('-- sabotage: the suppression must be able to fail --')
_SRC = io.open(MODULE, encoding='utf-8').read()
for label, old, new in (
        ('S1 suppression ignores the version and always fires',
         "        elif r.get('host_fixed'):",
         "        elif True:"),
        ('S2 the version compare is inverted',
         "    return a >= b",
         "    return a <= b"),
        ('S3 a missing declaration counts as fixed',
         "    if not have or not want:\n        return False",
         "    if not have or not want:\n        return True"),
):
    if _SRC.count(old) != 1:
        check(label, False, 'mutation target not found once (%d)'
              % _SRC.count(old))
        continue
    mut = load('probe-hf-mut', src=_SRC.replace(old, new, 1))
    caught = False
    try:
        r_old = dict(_row('6.09.01'))
        r_old['host_fixed'] = mut._at_or_above('6.09.01', '6.09.02')
        if mut.classify([r_old], _seen())[0][0]['status'] != 'lapsed':
            caught = True          # a device that still needs the patch went quiet
        r_none = dict(_row('6.09.02', fixed_in=''))
        r_none['host_fixed'] = mut._at_or_above('6.09.02', '')
        if mut.classify([r_none], _seen())[0][0]['status'] != 'lapsed':
            caught = True          # an undeclared patcher went quiet
    except Exception:
        caught = True
    check(label + ' -> caught', caught,
          'mutant SURVIVED -- a real regression would be silenced')


# --- 2e. NO MARKER MAY BE A STRING THE HOST ALREADY CONTAINS -------------
print()
print('=== the report cannot invent a repair we never made ===')

# HOW THIS BIT ME, twice now. Markers are harvested by SHAPE -- any identifier
# ending in _v<digits> -- from the patcher's whole source, comments included.
# Writing somebody else's versioned name in a comment therefore invents a
# marker this add-on never writes; the health report then finds it in the host
# (they DO write it) and reports a phantom repair as `ok`.
#
# The first time it was a docstring in patcher_health itself. The second was a
# comment naming Umbrella's own new sync cursor while explaining that Umbrella
# had fixed the bug -- and the report cheerfully called it a healthy repair.
# Both times the fix was the comment, never the rule: the shape rule is what
# lets a constructed marker be found at all.
#
# A phantom `ok` is worse than a phantom `lapsed`: it MASKS. It says a repair is
# applied when nothing of ours is there. So this checks every patcher against
# real host trees -- if a harvested marker already exists in a CLEAN host, it
# was never ours.
_hosts_on_disk = {}
for _hid, _vers in (('plugin.video.pov', ('6902', '6901', '6815')),
                    ('plugin.video.umbrella', ('787', '786'))):
    for _v in _vers:
        _d = os.path.join(SC, ('pov' if 'pov' in _hid else 'umb') + _v, _hid)
        if os.path.isdir(_d):
            _hosts_on_disk[_hid] = _d
            break

if not _hosts_on_disk:
    check('a clean host tree is on disk to check against', False,
          'this check proves nothing without one')
else:
    _text = {}
    for _hid, _d in _hosts_on_disk.items():
        _buf = []
        for _dp, _dn, _fn in os.walk(_d):
            for _f in _fn:
                if _f.endswith('.py'):
                    try:
                        _buf.append(io.open(os.path.join(_dp, _f),
                                            encoding='utf-8',
                                            errors='replace').read())
                    except Exception:
                        pass
        _text[_hid] = '\n'.join(_buf)
    _ph2 = load('probe-phantom')
    _phantoms = []
    for _name in sorted(n for n in os.listdir(LIB) if n.endswith('.py')):
        if _name in ('__init__.py', 'patcher_health.py'):
            continue
        try:
            _src = io.open(os.path.join(LIB, _name), encoding='utf-8',
                           errors='replace').read()
        except Exception:
            continue
        _mk, _hs = _ph2.markers_and_hosts(_src)
        _live, _reb = _ph2.live_markers(_mk, _src)
        for _h in _hs:
            if _h not in _text:
                continue
            for _k in (_live | _reb):
                if _k in _text[_h]:
                    _phantoms.append('%s: %r already in a clean %s'
                                     % (_name[:-3], _k, _h))
    check('no harvested marker already exists in a clean host',
          not _phantoms,
          'phantom repair(s) would be reported as healthy:\n      '
          + '\n      '.join(_phantoms))
    check('...and the check had real hosts to look at',
          len(_hosts_on_disk) >= 1, repr(sorted(_hosts_on_disk)))


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
