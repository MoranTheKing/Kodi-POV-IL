#!/usr/bin/env python3
"""Missing brackets that made the skin hide things it was written to show.

FROM A USER'S LOG, one line after the video window opened:

    error <general>: unmatched parentheses in
                     string.isempty(listitem.art(clearlogo)

`String.IsEmpty(` is opened and never closed. Kodi cannot parse the condition
and treats it as FALSE -- and the same shape appears twenty-three times across
eight files of the shipped skin.

FOUR SITES ACROSS TWO SKINS, AND THE POINT OF THIS FILE IS WHICH FOUR.

The one anybody will notice is the video OSD, where a complementary pair draws
the title's clear-logo or, failing that, the studio logo. Both conditions are
unparseable, so both are false, so NEITHER is ever drawn -- on every device,
on every title. One of the two is meant to be showing at all times, so
closing the bracket restores the author's own alternative with nothing to
guess.

The other is the ClearArtLogo variable, which is the expression in the log.
THAT ONE CHANGES NOTHING ON SCREEN, and a first version of this file claimed
it would. Its only consumer is a Poster_View_Art_Logo include whose invocation
in View_51_Poster.xml is commented out -- it reads as somebody trying the
logo, finding it blank because of these brackets, and commenting it out
instead of debugging. Un-commenting is a visible change nobody asked for, so
the variable is repaired and the decision left alone. This file pins that
distinction, because getting it wrong is how a release note ends up promising
something the user will not see.

Run: python3 tools/test_fentastic_clearlogo_var.py
"""
import difflib
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


def newest_full_build():
    """The full build, which is where skin.estuary actually ships.

    The quickfix carries skin.fentastic but NOT skin.estuary -- so a device
    that quick-updates keeps whatever Estuary it already has, and the only
    thing that ever repairs it is the runtime patcher this file guards. That
    asymmetry is the reason the estuary site cannot be verified against the
    quickfix and needs the full build.
    """
    best, best_n = None, ()
    for path in glob.glob(os.path.join(
            DIST, 'Kodi-POV-IL-FENtastic-test-*.zip')):
        m = re.search(r'test-([0-9.]+)\.zip$', path)
        if not m:
            continue
        n = tuple(int(p) for p in m.group(1).split('.'))
        if n > best_n:
            best, best_n = path, n
    return best


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


def home_with(files, estuary=None):
    """A fake special://home carrying the named skin xml files.

    `files` go under skin.fentastic, `estuary` under skin.estuary -- a real
    device has ONE of the two, so most checks below deliberately supply only
    one and expect `no_skin` for the other.

    Returns (home, xml_dir) so a check can read a file back by name.
    """
    home = tempfile.mkdtemp(prefix='fclv-')
    _SCRATCH.append(home)
    xml_dir = os.path.join(home, 'addons', 'skin.fentastic', 'xml')
    os.makedirs(xml_dir, exist_ok=True)
    for name, text in files.items():
        with io.open(os.path.join(xml_dir, name), 'w', encoding='utf-8',
                     newline='') as f:
            f.write(text)
    for name, text in (estuary or {}).items():
        d = os.path.join(home, 'addons', 'skin.estuary', 'xml')
        os.makedirs(d, exist_ok=True)
        with io.open(os.path.join(d, name), 'w', encoding='utf-8',
                     newline='') as f:
            f.write(text)
    return home, xml_dir


def read(path):
    with io.open(path, encoding='utf-8', newline='') as f:
        return f.read()


# --- 0. the shipped skin really is broken, and in the way described --------
print('=== the defect is in the released package ===')
qf = newest_quickfix()
check('a quickfix package was found to inspect', qf is not None)
SKIN = {}
EST = {}
if qf:
    with zipfile.ZipFile(qf) as z:
        for name in ('Variables.xml', 'Includes_VideoOsd4.xml',
                     'View_51_Poster.xml'):
            SKIN[name] = z.read(
                'addons/skin.fentastic/xml/' + name).decode('utf-8')
    fb = newest_full_build()
    check('a full build was found, which is where skin.estuary ships',
          fb is not None)
    if fb:
        with zipfile.ZipFile(fb) as z:
            for name in ('Variables.xml', 'View_51_Poster.xml'):
                EST[name] = z.read(
                    'addons/skin.estuary/xml/' + name).decode('utf-8')
    mod0 = load(tempfile.mkdtemp(prefix='fclv-probe-'))
    for label, skin, rel, broken, fixed in mod0.SITES:
        src = EST if skin == 'skin.estuary' else SKIN
        if not src:
            continue
        text = src[rel.split('/')[-1]]
        check('%s: the shipped skin has exactly the broken block' % label,
              text.count(mod0._fit(text, broken)) == 1,
              'found %d -- if the skin was fixed upstream, delete this repair '
              'rather than keeping one that matches nothing'
              % text.count(mod0._fit(text, broken)))

    # THE LIVE PAIR. Both conditions false at once means neither image is
    # drawn, and one of them is meant to be showing at all times.
    osd = SKIN['Includes_VideoOsd4.xml']
    pair = [c for c in re.findall(r'<visible>([^<]*)</visible>', osd)
            if 'Player.Art(clearlogo' in c]
    check('the video OSD pair is two complementary conditions', len(pair) == 2,
          str(pair))
    check('...and BOTH are unparseable as shipped, so neither image shows',
          pair and all(unbalanced(c) for c in pair), str(pair))
    check('...and the pair is live XML, not commented out',
          '<!-- <control type="image">' not in osd
          and '$VAR[PlayerClearLogoVar]' in osd)

    # AND THE ONE THAT CHANGES NOTHING. Said out loud, because the first
    # version of this file promised a logo that cannot appear.
    poster = SKIN['View_51_Poster.xml']
    check('the poster-view include is DEFINED',
          '<include name="Poster_View_Art_Logo">' in poster)
    check('...and its only invocation is commented out, so repairing the '
          'variable shows nothing new',
          '<!-- <include content="Poster_View_Art_Logo"> -->' in poster
          and '\n\t\t\t<include content="Poster_View_Art_Logo">' not in poster,
          'if somebody un-commented it, this repair became visible and the '
          'release note may say so')

    # ESTUARY IS THE OPPOSITE CASE, and that is the whole reason it was added.
    # FENtastic's consumer is commented out, so repairing it is bookkeeping.
    # Estuary's is live XML, so the variable resolving to nothing means a
    # texture that draws nothing, in the default poster view, on every device.
    est_poster = EST.get('View_51_Poster.xml', '')
    est_vars = EST.get('Variables.xml', '')
    check('estuary: the ClearArtLogo consumer is LIVE, not commented out',
          '<texture>$VAR[ClearArtLogo]</texture>' in est_poster
          and '<!-- <texture>$VAR[ClearArtLogo]</texture>' not in est_poster,
          'if this became commented out upstream, the estuary site is now '
          'bookkeeping too and the release note should stop promising a logo')
    est_conds = [c for c in re.findall(r'condition="([^"]*)"', est_vars)
                 if 'ListItem.Art(clearlogo' in c]
    check('estuary: both of its conditions are unparseable as shipped',
          len(est_conds) == 2 and all(unbalanced(c) for c in est_conds),
          str(est_conds))
    check('...so BOTH branches are false and the variable resolves to nothing',
          len(est_conds) == 2)


# --- 1. the repair, on the real files --------------------------------------
print()
print('=== the repair ===')
if SKIN:
    home, root = home_with(SKIN, estuary=EST)
    est_root = os.path.join(home, 'addons', 'skin.estuary', 'xml')
    mod = load(home)
    st = mod.ensure_patched()
    print('   status: %s' % st)
    check('every site patches when both skins are present',
          st.count('=patched') == len(mod.SITES), st)

    osd_after = read(os.path.join(root, 'Includes_VideoOsd4.xml'))
    conds = [c for c in re.findall(r'<visible>([^<]*)</visible>', osd_after)
             if 'Player.Art(clearlogo' in c]
    check('the OSD pair now parses', not any(unbalanced(c) for c in conds),
          str(conds))
    check('...and is still a complement, not two copies of one branch',
          sorted(conds) == ['!String.IsEmpty(Player.Art(clearlogo))',
                            'String.IsEmpty(Player.Art(clearlogo))'],
          str(conds))
    # THE PAYLOAD, not only the condition. Checking conditions alone passed a
    # mutant with the two textures exchanged -- "has a logo, so show the
    # studio logo" -- which is nonsense that every other assertion accepted.
    check('...each condition still guards the texture it was written for',
          '<texture>$VAR[PlayerClearLogoVar]</texture>\n\t\t\t'
          '<aspectratio>keep</aspectratio>\n\t\t\t'
          '<visible>!String.IsEmpty(Player.Art(clearlogo))</visible>'
          in osd_after
          and '<visible>String.IsEmpty(Player.Art(clearlogo))</visible>'
          in osd_after.split('Studiologotextureinfo')[1][:200],
          'the clear-logo and studio-logo textures were exchanged')

    vars_after = read(os.path.join(root, 'Variables.xml'))
    block = re.findall(r'<variable name="ClearArtLogo">(.*?)</variable>',
                       vars_after, re.S)
    vconds = re.findall(r'condition="([^"]*)"', block[0]) if block else []
    check('the ClearArtLogo conditions parse',
          vconds == ['!String.IsEmpty(ListItem.Art(clearlogo))',
                     'String.IsEmpty(ListItem.Art(clearlogo))'], str(vconds))
    check('...and each still returns the art it was written to return',
          block and '$INFO[ListItem.Art(clearlogo)]' in block[0].split(
              '</value>')[0]
          and '$INFO[ListItem.Art(clearart)]' in block[0].split(
              '</value>')[1],
          'the clearlogo and clearart payloads were exchanged')

    # ESTUARY, the one that is actually on screen.
    if EST:
        est_after = read(os.path.join(est_root, 'Variables.xml'))
        eblock = re.findall(r'<variable name="ClearArtLogo">(.*?)</variable>',
                            est_after, re.S)
        econds = re.findall(r'condition="([^"]*)"', eblock[0]) if eblock \
            else []
        check('estuary: the ClearArtLogo conditions now parse',
              econds == ['!String.IsEmpty(ListItem.Art(clearlogo))',
                         'String.IsEmpty(ListItem.Art(clearlogo))'],
              str(econds))
        check('estuary: ...and each still returns the art it was written for',
              eblock and '$INFO[ListItem.Art(clearlogo)]'
              in eblock[0].split('</value>')[0]
              and '$INFO[ListItem.Art(clearart)]'
              in eblock[0].split('</value>')[1],
              'the clearlogo and clearart payloads were exchanged')
        ebefore = sum(1 for c in re.findall(r'condition="([^"]*)"',
                                            EST['Variables.xml'])
                      if unbalanced(c))
        eafter = sum(1 for c in re.findall(r'condition="([^"]*)"', est_after)
                     if unbalanced(c))
        check('estuary: exactly 2 conditions repaired, the rest left alone',
              eafter == ebefore - 2, '%d before, %d after' % (ebefore, eafter))
        # EXACTLY two lines, EXACTLY two bytes -- one ')' each. The first
        # version of this check reverse-substituted the repair and compared
        # whole files, which also rewrote unrelated conditions that legally
        # end in `clearlogo))">` and reported a change the repair never made.
        diff = [l for l in difflib.unified_diff(
            EST['Variables.xml'].splitlines(), est_after.splitlines(),
            lineterm='', n=0)
            if l[:1] in '+-' and not l.startswith(('+++', '---'))]
        check('estuary: exactly two lines changed, and nothing else',
              len(diff) == 4
              and len(est_after) == len(EST['Variables.xml']) + 2,
              '%d changed line(s), %+d bytes'
              % (len(diff), len(est_after) - len(EST['Variables.xml'])))

    # NOTHING ELSE MOVED. Nineteen other unbalanced conditions in Variables
    # are deliberately untouched, so "the count went down by exactly two" is
    # the check, not "there are none left".
    for name, expect in (('Variables.xml', 2), ('Includes_VideoOsd4.xml', 2)):
        before = sum(1 for c in re.findall(r'condition="([^"]*)"|<visible>'
                                           r'([^<]*)</visible>', SKIN[name])
                     for c in c if c and unbalanced(c))
        after_text = read(os.path.join(root, name))
        after = sum(1 for c in re.findall(r'condition="([^"]*)"|<visible>'
                                          r'([^<]*)</visible>', after_text)
                    for c in c if c and unbalanced(c))
        check('%s: exactly %d condition(s) repaired' % (name, expect),
              after == before - expect, '%d before, %d after' % (before, after))

    check('running it again changes nothing',
          mod.ensure_patched().count('=unchanged') == len(mod.SITES))


# --- 2. the files it must not touch ----------------------------------------
print()
print('=== a skin it does not recognise is left alone ===')
home3, root3 = home_with({'Variables.xml': '<includes/>\n',
                          'Includes_VideoOsd4.xml': '<includes/>\n'})
mod3 = load(home3)
before3 = read(os.path.join(root3, 'Variables.xml'))
st3 = mod3.ensure_patched()
FENT_N = sum(1 for x in mod3.SITES if x[1] == 'skin.fentastic')
check('a file without the blocks is unmatched',
      st3.count('=unmatched') == FENT_N
      and st3.count('=no_skin') == len(mod3.SITES) - FENT_N, st3)
check('...and untouched', read(os.path.join(root3, 'Variables.xml')) == before3)

if SKIN:
    twice = dict(SKIN)
    _b = mod0.SITES[0][3]
    twice['Includes_VideoOsd4.xml'] = SKIN['Includes_VideoOsd4.xml'].replace(
        _b, _b + '\n' + _b, 1)
    home4, root4 = home_with(twice)
    mod4 = load(home4)
    before4 = read(os.path.join(root4, 'Includes_VideoOsd4.xml'))
    st4 = mod4.ensure_patched()
    check('two copies of a block are refused, not half-fixed',
          'video_OSD_logo=unmatched' in st4, st4)
    # THE BLOCK, not the file. The other site lives in the same file and is
    # still there exactly once, so it patches -- sites are independent on
    # purpose, and asserting the whole file unchanged asserted the opposite.
    after4 = read(os.path.join(root4, 'Includes_VideoOsd4.xml'))
    check('...and both copies of the refused block are left as they were',
          after4.count(mod4._fit(after4, mod0.SITES[0][3])) == 2
          and mod4._fit(after4, mod0.SITES[0][4]) not in after4,
          'the ambiguous block was edited anyway')
    check('...while the unambiguous site in the same file still got fixed',
          'video_OSD_studio_logo=patched' in st4, st4)

    # LINE ENDINGS DIFFER BETWEEN THE TWO FILES -- Variables.xml is CRLF and
    # Includes_VideoOsd4.xml is LF -- and both have been through extractors on
    # devices nobody here has seen. Flipping both proves neither is assumed.
    flipped = {'Variables.xml': SKIN['Variables.xml'].replace('\r\n', '\n'),
               'Includes_VideoOsd4.xml': SKIN['Includes_VideoOsd4.xml']
               .replace('\n', '\r\n')}
    home5, root5 = home_with(flipped)
    mod5 = load(home5)
    st5 = mod5.ensure_patched()
    check('both files patch with their line endings swapped',
          st5.count('=patched') == FENT_N, st5)
    check('...and no line ending is changed',
          '\r' not in read(os.path.join(root5, 'Variables.xml'))
          and '\n' not in read(os.path.join(
              root5, 'Includes_VideoOsd4.xml')).replace('\r\n', ''))

if EST:
    # Estuary's Variables.xml is CRLF like FENtastic's; prove the repair does
    # not depend on that either, since a device's copy has been through
    # whatever wrote it.
    home7, _ = home_with({}, estuary={
        'Variables.xml': EST['Variables.xml'].replace('\r\n', '\n')})
    mod7 = load(home7)
    st7 = mod7.ensure_patched()
    check('estuary patches with LF line endings too',
          'estuary_poster-view_clear-logo_variable=patched' in st7, st7)
    check('...and stays LF',
          '\r' not in read(os.path.join(
              home7, 'addons', 'skin.estuary', 'xml', 'Variables.xml')))

home6 = tempfile.mkdtemp(prefix='fclv-none-')
_SCRATCH.append(home6)
mod6 = load(home6)
check('no skin at all is reported, not crashed',
      mod6.ensure_patched().count('=no_skin') == len(mod6.SITES))


# --- 3. it is wired in, and actually RUNS ----------------------------------
# `'name' in service.py` was the whole check, and the function's own body
# contains the name three times -- so dropping it from the tuple the run loop
# iterates would have left this reporting ALL PASS while nothing ever ran.
print()
print('=== the service actually runs it ===')
svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                           'service.py'), encoding='utf-8').read()
check('service.py defines the step',
      'def _maybe_fix_fentastic_clearlogo_var(' in svc)
check('...and the repair pass actually lists it',
      '\n        _maybe_fix_fentastic_clearlogo_var,\n' in svc,
      'defined but not in the steps tuple: it would never run')

for d in _SCRATCH:
    shutil.rmtree(d, ignore_errors=True)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
