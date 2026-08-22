#!/usr/bin/env python3
"""Refreshing a bundled third-party add-on inside the full build.

WHY IT EXISTS. "Carried over untouched" quietly became "a year out of date".
The build shipped POV 5.12.04 while every device in the field was already on
6.08.13 -- Kodi's own auto-update takes a fresh install there within a day --
so the bundle protected nobody. It only made a new install spend its first
hour downloading what it should have arrived with, and ran this build's own
add-on patchers against a POV that nobody actually runs.

That is also the safety argument, and it is the same one build_full_build's
header makes about the whole tool: shipping the version every existing device
already runs is not a new configuration, it is the one already in the field,
reached sooner.

THE DANGEROUS PART, and what most of this file is about: refreshing is the ONE
operation allowed to DELETE a member of the previous build. Upstream releases
remove files, and keeping their predecessors' leftovers ships a mixture of two
versions of somebody else's add-on. So the permission has to be exact:
everything under addons/<id>/ comes from the release and nothing else does,
and a member disappearing anywhere ELSE is still the failure the tool exists
to catch.

Run: python3 tools/test_build_addon_refresh.py
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
TOOL = os.path.join(HERE, 'build_full_build.py')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


WORK = tempfile.mkdtemp(prefix='bfbref-')


def zip_at(name, members):
    path = os.path.join(WORK, name)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for member, data in members.items():
            z.writestr(member, data)
    return path


def addon_xml(addon_id, version):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<addon id="%s" name="%s" version="%s" provider-name="x">\n'
            '</addon>\n' % (addon_id, addon_id, version))


OURS = 'addons/service.subtitles.kodipovilai'
WIZ = 'addons/plugin.program.kodipovilwizard'

PREV = {
    # A SIBLING WHOSE ID IS A PREFIX OF THE REFRESHED ONE. The scoping that
    # keeps a refresh inside its own add-on is one trailing slash in
    # _refresh_prefixes; without it, `addons/plugin.video.pov` also matches
    # `addons/plugin.video.povextra/...`. A review dropped that slash and
    # watched build() delete this add-on and verify() report success -- and
    # the old fixture could not see it, because `plugin.video.somethingelse`
    # shares no prefix with `plugin.video.pov` in either direction.
    'addons/plugin.video.povextra/addon.xml': addon_xml(
        'plugin.video.povextra', '1.0'),
    'addons/plugin.video.povextra/lib.py': 'A SIBLING, NOT A SUBDIRECTORY\n',
    OURS + '/addon.xml': addon_xml('service.subtitles.kodipovilai', '0.2.500'),
    OURS + '/service.py': 'old service\n',
    WIZ + '/addon.xml': addon_xml('plugin.program.kodipovilwizard', '0.1.40'),
    WIZ + '/startup.py': 'old startup\n',
    'addons/plugin.video.pov/addon.xml': addon_xml('plugin.video.pov',
                                                   '5.12.04'),
    'addons/plugin.video.pov/resources/lib/entry.py': 'OLD POV ENTRY\n',
    'addons/plugin.video.pov/resources/lib/gone.py': 'REMOVED UPSTREAM\n',
    'userdata/guisettings.xml': '<settings/>\n',
    'userdata/Database/Addons33.db': 'not really a db\n',
}
QF = {
    OURS + '/addon.xml': addon_xml('service.subtitles.kodipovilai', '0.2.510'),
    OURS + '/service.py': 'new service\n',
    WIZ + '/addon.xml': addon_xml('plugin.program.kodipovilwizard', '0.1.40'),
    WIZ + '/startup.py': 'stale wizard copy\n',
}
WIZPKG = {
    'plugin.program.kodipovilwizard/addon.xml': addon_xml(
        'plugin.program.kodipovilwizard', '0.1.50'),
    'plugin.program.kodipovilwizard/startup.py': 'new startup\n',
}
# the upstream release: entry.py changed, gone.py deleted, new.py added
POVPKG = {
    'plugin.video.pov/addon.xml': addon_xml('plugin.video.pov', '6.08.13'),
    'plugin.video.pov/resources/lib/entry.py': 'NEW POV ENTRY\n',
    'plugin.video.pov/resources/lib/new.py': 'ADDED UPSTREAM\n',
}

prev = zip_at('prev.zip', PREV)
qf = zip_at('qf.zip', QF)
wizpkg = zip_at('wizpkg.zip', WIZPKG)
povpkg = zip_at('pov.zip', POVPKG)


def run(out_name, extra=(), expect_ok=True):
    out = os.path.join(WORK, out_name)
    if os.path.exists(out):
        os.remove(out)
    cmd = [sys.executable, TOOL, '--previous', prev, '--quickfix', qf,
           '--wizard-zip', wizpkg, '--output', out,
           '--addon-version', '0.2.510', '--wizard-version', '0.1.50']
    cmd += list(extra)
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p, out


# --- 1. no refresh: nothing about the old behaviour changed ----------------
print('=== without --refresh-addon the tool behaves exactly as before ===')
p, out = run('plain.zip')
check('a plain build still succeeds', p.returncode == 0,
      (p.stdout + p.stderr)[-800:])
if p.returncode == 0:
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        check('...and POV is untouched at the old version',
              z.read('addons/plugin.video.pov/addon.xml').decode()
              == addon_xml('plugin.video.pov', '5.12.04'))
        check('...including the file upstream later removed',
              'addons/plugin.video.pov/resources/lib/gone.py' in names)


# --- 2. the refresh ---------------------------------------------------------
print()
print('=== the refresh replaces the whole subtree ===')
p, out = run('refreshed.zip',
             ['--refresh-addon', 'plugin.video.pov=' + povpkg])
check('the build succeeds', p.returncode == 0, (p.stdout + p.stderr)[-1200:])
if p.returncode == 0:
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        check('the new version is in', z.read(
            'addons/plugin.video.pov/addon.xml').decode()
            == addon_xml('plugin.video.pov', '6.08.13'))
        check('a changed file carries the release bytes',
              z.read('addons/plugin.video.pov/resources/lib/entry.py')
              == b'NEW POV ENTRY\n')
        check('a file the release ADDED is in',
              'addons/plugin.video.pov/resources/lib/new.py' in names)
        # THE ONE THAT MATTERS. Keeping this would ship a mixture of two
        # versions of somebody else's add-on -- a module the new code no
        # longer imports but Kodi still sees, and whichever of the two wins an
        # import is not something this build gets to decide.
        check('A FILE THE RELEASE REMOVED IS GONE',
              'addons/plugin.video.pov/resources/lib/gone.py' not in names,
              'the build now carries two versions of POV mixed together')
        # and nothing outside the refreshed subtree moved
        check('our add-on still comes from the quickfix',
              z.read(OURS + '/service.py') == b'new service\n')
        check('the wizard still comes from its own package',
              z.read(WIZ + '/startup.py') == b'new startup\n')
        check('userdata is still carried over untouched',
              z.read('userdata/guisettings.xml') == b'<settings/>\n'
              and 'userdata/Database/Addons33.db' in names)
        check('AN ADD-ON WHOSE ID STARTS WITH THE REFRESHED ONE IS UNTOUCHED',
              z.read('addons/plugin.video.povextra/lib.py')
              == b'A SIBLING, NOT A SUBDIRECTORY\n',
              'plugin.video.povextra was caught by plugin.video.pov\'s '
              'prefix -- the trailing slash in _refresh_prefixes is the only '
              'thing separating them')
    check('the run says what it refreshed',
          'refreshed plugin.video.pov -> 6.08.13' in p.stdout, p.stdout[-600:])
    check('...and says what it dropped', 'dropped 1 member' in p.stdout,
          'a silent deletion is the one thing this must never do')


# --- 3. the refusals --------------------------------------------------------
# Each of these is a way to ship a broken build, and each has to stop the tool
# rather than produce something plausible.
print()
print('=== every way to get it wrong stops the build ===')

# a package whose top-level directory is not the id
wrong = zip_at('wrong.zip', {
    'plugin.video.other/addon.xml': addon_xml('plugin.video.other', '1.0')})
p, _ = run('r1.zip', ['--refresh-addon', 'plugin.video.pov=' + wrong])
check('a package for a different add-on is refused', p.returncode != 0
      and 'top-level' in (p.stdout + p.stderr), (p.stdout + p.stderr)[-400:])

# two top-level directories
two = zip_at('two.zip', {
    'plugin.video.pov/addon.xml': addon_xml('plugin.video.pov', '6.0'),
    'script.module.extra/addon.xml': addon_xml('script.module.extra', '1.0')})
p, _ = run('r2.zip', ['--refresh-addon', 'plugin.video.pov=' + two])
check('a package carrying a second add-on is refused', p.returncode != 0,
      (p.stdout + p.stderr)[-400:])

# no addon.xml
noxml = zip_at('noxml.zip', {'plugin.video.pov/readme.txt': 'hi\n'})
p, _ = run('r3.zip', ['--refresh-addon', 'plugin.video.pov=' + noxml])
check('a package with no addon.xml is refused', p.returncode != 0
      and 'addon.xml' in (p.stdout + p.stderr), (p.stdout + p.stderr)[-400:])

# OURS IS NOT REFRESHED FROM UPSTREAM. Two sources claiming the same bytes and
# no stated precedence is how a release ships the wrong half of itself.
ourpkg = zip_at('ourpkg.zip', {
    'service.subtitles.kodipovilai/addon.xml': addon_xml(
        'service.subtitles.kodipovilai', '9.9.9'),
    'service.subtitles.kodipovilai/service.py': 'upstream service\n'})
p, _ = run('r4.zip',
           ['--refresh-addon', 'service.subtitles.kodipovilai=' + ourpkg])
check('refreshing an add-on the quickfix carries is refused',
      p.returncode != 0 and 'quickfix or wizard package' in (p.stdout +
                                                            p.stderr),
      (p.stdout + p.stderr)[-500:])

wizupstream = zip_at('wizup.zip', {
    'plugin.program.kodipovilwizard/addon.xml': addon_xml(
        'plugin.program.kodipovilwizard', '9.9.9')})
p, _ = run('r5.zip',
           ['--refresh-addon', 'plugin.program.kodipovilwizard=' + wizupstream])
check('...and so is one the wizard package carries', p.returncode != 0,
      (p.stdout + p.stderr)[-400:])

# A PATH THAT ESCAPES ITS OWN DIRECTORY. The top-level check reads the FIRST
# segment only, so `plugin.video.pov/../../userdata/guisettings.xml` passed it
# and was carried verbatim into the artifact a fresh install depends on -- and
# the prefix checks downstream agreed it was inside the add-on, because they
# compare the same un-normalised string.
slip = zip_at('slip.zip', {
    'plugin.video.pov/addon.xml': addon_xml('plugin.video.pov', '6.0'),
    'plugin.video.pov/../../userdata/guisettings.xml': '<pwned/>\n'})
p, _ = run('r5b.zip', ['--refresh-addon', 'plugin.video.pov=' + slip])
check('a member whose path escapes the add-on is refused',
      p.returncode != 0 and 'escapes' in (p.stdout + p.stderr),
      (p.stdout + p.stderr)[-500:])

absolute = zip_at('abs.zip', {
    'plugin.video.pov/addon.xml': addon_xml('plugin.video.pov', '6.0'),
    '/etc/passwd': 'nope\n'})
p, _ = run('r5c.zip', ['--refresh-addon', 'plugin.video.pov=' + absolute])
check('...and so is an absolute path', p.returncode != 0,
      (p.stdout + p.stderr)[-300:])

# TWO MEMBERS WITH THE SAME NAME. _members is a dict keyed by filename, so one
# silently wins; an input whose meaning we cannot state is not one to build a
# release from.
import io as _io
_dup_path = os.path.join(WORK, 'dup.zip')
with zipfile.ZipFile(_dup_path, 'w') as _z:
    _z.writestr('plugin.video.pov/addon.xml', addon_xml('plugin.video.pov', '6.0'))
    _z.writestr('plugin.video.pov/entry.py', 'FIRST\n')
    _z.writestr('plugin.video.pov/entry.py', 'SECOND\n')
p, _ = run('r5d.zip', ['--refresh-addon', 'plugin.video.pov=' + _dup_path])
check('a duplicated member name is refused', p.returncode != 0
      and 'duplicated' in (p.stdout + p.stderr), (p.stdout + p.stderr)[-300:])

# NOT A ZIP AT ALL -- a one-line refusal, like every other one, not a traceback
_txt = os.path.join(WORK, 'notazip.txt')
with open(_txt, 'w') as fh:
    fh.write('this is not a zip\n')
p, _ = run('r5e.zip', ['--refresh-addon', 'plugin.video.pov=' + _txt])
check('a file that is not a zip is refused by name, not by traceback',
      p.returncode != 0 and 'not a readable zip' in (p.stdout + p.stderr)
      and 'Traceback' not in (p.stdout + p.stderr),
      (p.stdout + p.stderr)[-400:])

# REFRESH REPLACES, IT DOES NOT INTRODUCE. Every new file under a refreshed
# add-on skips --allow-add, which is right for an upstream release that added
# a module and wrong as a way to add a whole add-on nobody reviewed.
newpkg = zip_at('newaddon.zip', {
    'plugin.video.totallynew/addon.xml': addon_xml('plugin.video.totallynew',
                                                   '1.0'),
    'plugin.video.totallynew/default.py': 'brand new\n'})
p, _ = run('r5f.zip', ['--refresh-addon', 'plugin.video.totallynew=' + newpkg])
check('refreshing an add-on the build does not carry is refused',
      p.returncode != 0 and 'does not contain' in (p.stdout + p.stderr),
      (p.stdout + p.stderr)[-400:])

# a malformed flag
p, _ = run('r6.zip', ['--refresh-addon', 'plugin.video.pov'])
check('ID=PATH is required', p.returncode != 0
      and 'ID=PACKAGE.ZIP' in (p.stdout + p.stderr), (p.stdout + p.stderr)[-300:])

p, _ = run('r7.zip', ['--refresh-addon', 'plugin.video.pov=/nope/nope.zip'])
check('a missing package is refused', p.returncode != 0,
      (p.stdout + p.stderr)[-300:])

p, _ = run('r8.zip', ['--refresh-addon', 'plugin.video.pov=' + povpkg,
                      '--refresh-addon', 'plugin.video.pov=' + povpkg])
check('the same id twice is refused', p.returncode != 0
      and 'more than once' in (p.stdout + p.stderr), (p.stdout + p.stderr)[-300:])

# THE DELETION PERMISSION IS SCOPED. A member vanishing anywhere but inside a
# refreshed add-on must still stop the build -- that is the check this feature
# had to punch a hole in, and the hole has to be exactly the right size.
print()
print('=== the deletion permission does not leak ===')
short_prev = dict(PREV)
short_prev['addons/plugin.video.somethingelse/x.py'] = 'still here\n'
prev2 = zip_at('prev2.zip', short_prev)


def run2(out_name, extra):
    out = os.path.join(WORK, out_name)
    p = subprocess.run(
        [sys.executable, TOOL, '--previous', prev2, '--quickfix', qf,
         '--wizard-zip', wizpkg, '--output', out,
         '--addon-version', '0.2.510', '--wizard-version', '0.1.50'] +
        list(extra), capture_output=True, text=True)
    return p, out


p, out = run2('scoped.zip', ['--refresh-addon', 'plugin.video.pov=' + povpkg])
check('an unrelated add-on is still carried whole', p.returncode == 0,
      (p.stdout + p.stderr)[-500:])
if p.returncode == 0:
    with zipfile.ZipFile(out) as z:
        check('...file for file',
              'addons/plugin.video.somethingelse/x.py' in z.namelist())

# and the verify half, independently: hand it a build with a leftover and it
# must refuse, even though build() produced a correct one.
print()
print('=== verify catches a leftover build() would never have made ===')
sys.path.insert(0, HERE)
import importlib.util
spec = importlib.util.spec_from_file_location('bfb', TOOL)
bfb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bfb)

from pathlib import Path
good = os.path.join(WORK, 'refreshed.zip')
tampered = os.path.join(WORK, 'tampered.zip')
with zipfile.ZipFile(good) as src, \
        zipfile.ZipFile(tampered, 'w', zipfile.ZIP_DEFLATED) as dst:
    for info in src.infolist():
        dst.writestr(info, src.read(info.filename))
    dst.writestr('addons/plugin.video.pov/resources/lib/gone.py',
                 b'REMOVED UPSTREAM\n')
try:
    bfb.verify(Path(prev), Path(qf), Path(tampered), '0.2.510', '0.1.50',
               Path(wizpkg), [('plugin.video.pov', Path(povpkg))])
    caught = False
except SystemExit as e:
    caught = 'does not have' in str(e)
check('a leftover inside a refreshed add-on is refused by verify', caught,
      'verify accepted a build carrying two versions of POV')

tampered2 = os.path.join(WORK, 'tampered2.zip')
with zipfile.ZipFile(good) as src, \
        zipfile.ZipFile(tampered2, 'w', zipfile.ZIP_DEFLATED) as dst:
    for info in src.infolist():
        data = src.read(info.filename)
        if info.filename.endswith('plugin.video.pov/resources/lib/entry.py'):
            data = b'SOMETHING ELSE\n'
        dst.writestr(info, data)
try:
    bfb.verify(Path(prev), Path(qf), Path(tampered2), '0.2.510', '0.1.50',
               Path(wizpkg), [('plugin.video.pov', Path(povpkg))])
    caught2 = False
except SystemExit as e:
    caught2 = 'byte for byte' in str(e)
check('a refreshed member that does not match the package is refused', caught2)

shutil.rmtree(WORK, ignore_errors=True)
print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
