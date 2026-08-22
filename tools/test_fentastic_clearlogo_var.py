#!/usr/bin/env python3
"""A feature that was dead on arrival, because of two missing brackets.

FROM A USER'S LOG, one line after the video window opened:

    error <general>: unmatched parentheses in
                     string.isempty(listitem.art(clearlogo)

The skin's own Variables.xml:

    <variable name="ClearArtLogo">
        <value condition="!String.IsEmpty(ListItem.Art(clearlogo)">...
        <value condition="String.IsEmpty(ListItem.Art(clearlogo)">...
    </variable>

`String.IsEmpty(` is never closed. Kodi cannot parse either condition and
treats both as false; the variable has no unconditional fallback, so it
resolves to nothing on every device. Its ONE user is this build's own
Poster_View_Art_Logo include, whose entire body is an <image> with that
variable as its texture -- so the logo it exists to draw has never appeared,
anywhere, since it was written.

WHAT THIS PINS:

  * the shipped skin really is broken in the way described -- checked against
    the released package, so this test would go quiet if the skin were ever
    fixed upstream instead of silently keeping a repair nobody needs;
  * the repair produces a condition Kodi can actually parse -- checked by
    balancing brackets, not by string comparison, because "it matches the
    string I wrote" proves only that I typed it twice;
  * and it repairs THAT variable and nothing else: the file is otherwise
    byte-identical, and a skin edited into any other shape is left alone.

Run: python3 tools/test_fentastic_clearlogo_var.py
"""
import glob
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
MODULE = os.path.join(LIB, 'fentastic_clearlogo_var_patcher.py')
DIST = os.path.join(ROOT, 'dist')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def newest_quickfix():
    best, best_n = None, ()
    for path in glob.glob(os.path.join(
            DIST, 'Kodi-POV-IL-FENtastic-quickfix-*.zip')):
        m = re.search(r'quickfix-([0-9.]+)\.zip$', path)
        if not m:
            continue
        n = tuple(int(p) for p in m.group(1).split('.'))
        if n > best_n:
            best, best_n = path, n
    return best


def unbalanced(expr):
    depth = 0
    for ch in expr:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                return True
    return depth != 0


_SCRATCH = []


def load(home):
    for n in list(sys.modules):
        if n.split('.')[0] in ('resources', 'xbmcvfs'):
            sys.modules.pop(n, None)
    vfs = types.ModuleType('xbmcvfs')
    vfs.translatePath = lambda p: p.replace('special://home/', home + os.sep)
    sys.modules['xbmcvfs'] = vfs
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location('fclv_t', MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def home_with(text):
    home = tempfile.mkdtemp(prefix='fclv-')
    _SCRATCH.append(home)
    path = os.path.join(home, 'addons', 'skin.fentastic', 'xml',
                        'Variables.xml')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return home, path


def read(path):
    with io.open(path, encoding='utf-8', newline='') as f:
        return f.read()


# --- 0. the shipped skin really is broken ----------------------------------
print('=== the defect is in the released package ===')
qf = newest_quickfix()
check('a quickfix package was found to inspect', qf is not None)
SHIPPED = None
if qf:
    with zipfile.ZipFile(qf) as z:
        SHIPPED = z.read(
            'addons/skin.fentastic/xml/Variables.xml').decode('utf-8')
        POSTER = z.read(
            'addons/skin.fentastic/xml/View_51_Poster.xml').decode('utf-8')
    mod0 = load(home_with('x')[0])
    check('the shipped skin contains exactly the broken block',
          SHIPPED.count(mod0.BROKEN) == 1,
          'found %d -- if the skin was fixed upstream, delete this repair '
          'rather than keeping one that matches nothing'
          % SHIPPED.count(mod0.BROKEN))
    conds = re.findall(r'<variable name="ClearArtLogo">(.*?)</variable>',
                       SHIPPED, re.S)
    check('...and both of its conditions are unparseable as shipped',
          conds and all(unbalanced(c) for c in
                        re.findall(r'condition="([^"]*)"', conds[0])),
          'the premise of this whole file')
    # and the dead feature: one user, and it is ours
    check('$VAR[ClearArtLogo] has exactly one user in the skin',
          sum(f.count('$VAR[ClearArtLogo]') for f in (SHIPPED, POSTER)) == 1)
    check("...and it is this build's own poster-view include",
          'Poster_View_Art_Logo' in POSTER
          and '$VAR[ClearArtLogo]' in POSTER,
          'if that moved, the reason given for this repair moved with it')


# --- 1. the repair ---------------------------------------------------------
print()
print('=== the repair, on the real file ===')
if SHIPPED:
    home, path = home_with(SHIPPED)
    mod = load(home)
    st = mod.ensure_patched()
    check('it patches the shipped Variables.xml', st == 'patched', st)
    after = read(path)

    # THE POINT, checked by balancing rather than by string equality. A test
    # that compared against the same constant the module writes would pass
    # even if I had typed the wrong number of brackets in both places.
    block = re.findall(r'<variable name="ClearArtLogo">(.*?)</variable>',
                       after, re.S)
    conds = re.findall(r'condition="([^"]*)"', block[0]) if block else []
    check('the variable now has two conditions', len(conds) == 2, str(conds))
    check('...and Kodi can parse both of them',
          conds and not any(unbalanced(c) for c in conds), str(conds))
    check('...one asking for a clearlogo and one for the absence of it',
          conds == ['!String.IsEmpty(ListItem.Art(clearlogo))',
                    'String.IsEmpty(ListItem.Art(clearlogo))'], str(conds))

    # NOTHING ELSE MOVED. This file has around three dozen other unbalanced
    # conditions, deliberately untouched -- so "the count went down by two" is
    # the check, not "there are none left".
    before_bad = len([c for c in re.findall(r'condition="([^"]*)"', SHIPPED)
                      if unbalanced(c)])
    after_bad = len([c for c in re.findall(r'condition="([^"]*)"', after)
                     if unbalanced(c)])
    check('exactly two broken conditions were repaired',
          after_bad == before_bad - 2,
          '%d before, %d after' % (before_bad, after_bad))
    check('and the rest of the file is byte-identical',
          after.replace(mod.FIXED, mod.BROKEN, 1) == SHIPPED,
          'something outside the ClearArtLogo variable changed')

    check('running it again changes nothing',
          mod.ensure_patched() == 'unchanged')
    check('...and really does not rewrite the file', read(path) == after)


# --- 2. the files it must not touch ----------------------------------------
print()
print('=== a skin it does not recognise is left alone ===')
mod2 = load(home_with('x')[0])

home3, path3 = home_with('<includes>\n\t<variable name="Other"/>\n</includes>')
mod3 = load(home3)
before3 = read(path3)
check('a Variables.xml without the variable is unmatched',
      mod3.ensure_patched() == 'unmatched')
check('...and untouched', read(path3) == before3)

if SHIPPED:
    twice = SHIPPED.replace(mod2.BROKEN, mod2.BROKEN + '\r\n' + mod2.BROKEN, 1)
    home4, path4 = home_with(twice)
    mod4 = load(home4)
    before4 = read(path4)
    check('two copies of the variable are refused, not half-fixed',
          mod4.ensure_patched() == 'unmatched')
    check('...and untouched', read(path4) == before4)

    # an LF copy -- extractors and skin updates do this, and matching only
    # CRLF would report unmatched and leave such a device broken forever.
    home5, path5 = home_with(SHIPPED.replace('\r\n', '\n'))
    mod5 = load(home5)
    check('an LF copy is patched too', mod5.ensure_patched() == 'patched')
    lf = read(path5)
    check('...without introducing a CR', '\r' not in lf)
    conds5 = re.findall(r'condition="([^"]*)"',
                        re.findall(r'<variable name="ClearArtLogo">(.*?)'
                                   r'</variable>', lf, re.S)[0])
    check('...and its conditions parse as well',
          not any(unbalanced(c) for c in conds5), str(conds5))

home6 = tempfile.mkdtemp(prefix='fclv-none-')
_SCRATCH.append(home6)
mod6 = load(home6)
check('no skin at all is reported, not crashed',
      mod6.ensure_patched() == 'no_skin')


# --- 3. it is wired in ------------------------------------------------------
print()
print('=== the service runs it ===')
svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                           'service.py'), encoding='utf-8').read()
check('service.py calls the patcher',
      'fentastic_clearlogo_var_patcher' in svc)

for d in _SCRATCH:
    shutil.rmtree(d, ignore_errors=True)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
