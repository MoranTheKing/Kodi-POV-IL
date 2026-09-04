"""A scraper in the legacy folder must actually LOAD, not merely be found.

WHAT POV 6.09.01 CHANGED, and why patching the scan line alone would have been
a fix that fixed nothing.

Through 6.08.15, discovery and loading both went through the `loader` pkgutil
hands back for the directory a module was found in:

    for loader, module_name, is_pkg in __import__('pkgutil').iter_modules([source_path]):
        append(('internal', loader.find_spec(module_name).loader.load_module(module_name).source, module_name))

Adding a second directory to that list was enough -- whatever was found there
was loaded from there. 6.09.01 kept the scan but replaced the load:

    try: module_source = importlib.import_module('.' + module_name, package='debrids').source

`import_module('.name', package='debrids')` resolves through POV's OWN debrids
package, NOT through the directory the module came from. So a scraper in the
legacy folder is now discovered by the scan and then fails to import. POV logs
'Error: Loading module' and carries on with its own sources only -- the symptom
is identical to the folder never being scanned, two lines further down.

THIS FILE EXECUTES THE PATCHED BLOCK. Not `ensure_patched() == 'patched'` --
that is the return value, and the whole reason the health report exists is that
a return value is not evidence. The block is pulled out of the REAL patched
sources.py, run against a REAL legacy folder holding a real module, and the
test asserts that the module's `source` object arrives at POV's `append`.

Run: python3 tools/test_pov_internal_scraper_loads.py
"""
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import textwrap
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
SC = ('/tmp/claude-0/-home-user-Kodi-POV-IL/'
      '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad')
SOURCES_REL = ('resources', 'lib', 'modules', 'sources.py')

FAIL = []
_TMP = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def tmp(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    _TMP.append(d)
    return d


def pov_tree(ver):
    src = os.path.join(SC, 'pov%s' % ver, 'plugin.video.pov')
    return src if os.path.isdir(src) else None


def patched_tree(ver, mutate=None):
    """A real POV tree with the shim applied, or None."""
    tree = pov_tree(ver)
    if tree is None:
        return None, None, None
    work = tmp('isl-%s-' % ver)
    addons = os.path.join(work, 'addons')
    os.makedirs(addons)
    shutil.copytree(tree, os.path.join(addons, 'plugin.video.pov'))

    for n in list(sys.modules):
        if n.startswith(('xbmc', 'resources')):
            sys.modules.pop(n, None)
    for name in ('xbmc', 'xbmcaddon', 'xbmcgui'):
        sys.modules[name] = types.ModuleType(name)
    xv = types.ModuleType('xbmcvfs')
    xv.translatePath = lambda p: p.replace('special://home/addons/',
                                           addons + os.sep)
    sys.modules['xbmcvfs'] = xv
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [LIB]
    pkg.lib = lib
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.logged = []
    ku.log = lambda m, level='INFO': ku.logged.append((level, m))
    ku.get_setting = lambda k, d='': d
    ku.set_setting = lambda k, v: None
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku

    spec = importlib.util.spec_from_file_location(
        'resources.lib.pov_internal_scraper_shim',
        os.path.join(LIB, 'pov_internal_scraper_shim.py'))
    shim = importlib.util.module_from_spec(spec)
    sys.modules['resources.lib.pov_internal_scraper_shim'] = shim
    spec.loader.exec_module(shim)
    if mutate is not None:
        mutate(shim)
    verdict = shim.ensure_patched()
    return os.path.join(addons, 'plugin.video.pov'), verdict, addons


def extract_block(sources_path):
    """The patched activate_internal body, dedented to module level."""
    text = io.open(sources_path, encoding='utf-8').read()
    start = text.index('\t\tsource_path = kodi_utils.translate_path')
    end = text.index('\n\n\tdef activate_external', start)
    block = text[start:end]
    return textwrap.dedent(block.replace('\t', '    '))


def run_block(block, addons_root, own, active):
    """Execute the block with POV's surroundings stubbed. Returns what POV's
    `append` received.

    translate_path has to resolve special:// the way Kodi does. The first
    version of this returned its argument unchanged, so the patched code's
    legacy-folder lookup got a literal 'special://...' string, os.path.isdir
    said no, and the second directory was never added -- the test then reported
    the fix broken on the KNOWN-GOOD 6.08.15 baseline too, which is what gave
    the harness away rather than the patch."""
    appended = []
    ku = types.ModuleType('kodi_utils')
    ku.translate_path = lambda p: p.replace('special://home/addons/',
                                            addons_root + os.sep)
    ku.internal_path = own
    ku.scrapers_path = own
    ku.logger = lambda *a: None

    class _Src(object):
        pass
    src = _Src()
    src.active_internal_scrapers = list(active)
    src.mediatype = 'movie'

    class _Self(object):
        pass
    me = _Self()
    me.source = src

    import importlib as _il
    import pkgutil as _pk
    g = {
        'kodi_utils': ku,
        'append': appended.append,
        'self': me,
        'prescrape': False,
        'check_prescrape_sources': lambda *a: True,
        'importlib': _il,
        'pkgutil': _pk,
        '__import__': __import__,
    }
    exec(compile(block, '<activate_internal>', 'exec'), g)
    return appended


def make_module(folder, name, tag):
    os.makedirs(folder, exist_ok=True)
    init = os.path.join(folder, '__init__.py')
    if not os.path.isfile(init):
        io.open(init, 'w').close()
    with io.open(os.path.join(folder, name + '.py'), 'w',
                 encoding='utf-8') as f:
        f.write('class _S(object):\n    tag = %r\nsource = _S\n' % tag)


for ver, label in (('6901', 'POV 6.09.01'), ('6815', 'POV 6.08.15')):
    print('\n=== %s ===' % label)
    tree, verdict, addons_root = patched_tree(ver)
    if tree is None:
        check('%s: tree is on disk' % label, False,
              'no scratchpad copy -- this file proves nothing without it')
        continue
    check('%s: the shim reports scan=patched' % label,
          verdict and 'scan=patched' in verdict, repr(verdict))

    sources = os.path.join(tree, *SOURCES_REL)
    body = io.open(sources, encoding='utf-8').read()
    check('%s: the marker is in the file' % label,
          '# AI_SUBS_POV_INTERNAL_DIRS_v2' in body)

    block = extract_block(sources)
    own = os.path.join(tree, 'resources', 'lib', 'debrids')
    legacy = os.path.join(tree, 'resources', 'lib', 'scrapers')
    make_module(legacy, 'ai_probe_scraper', 'from-legacy')

    # THE CHECK THIS FILE EXISTS FOR: a module that lives ONLY in the legacy
    # folder has to arrive at append(), loaded, with its `source` attribute.
    got = run_block(block, addons_root, own, ['ai_probe_scraper'])
    names = [n for _k, _s, n in got]
    check('%s: the legacy scraper reaches POV\'s append()' % label,
          'ai_probe_scraper' in names, 'append got %r' % (names,))
    tags = [getattr(s, 'tag', None) for _k, s, _n in got]
    check('%s: it is LOADED, not just named' % label,
          'from-legacy' in tags,
          'the source objects were %r -- discovery without a working import is '
          'the exact failure 6.09.01 introduced' % (tags,))

    # POV'S OWN ROUTE MUST STILL WORK, and it is tested with a synthetic
    # module rather than one of POV's real ones. POV's actual scrapers open
    # with `from modules import ...` and only import inside a running Kodi, so
    # asserting on ad_cloud here would fail for a reason that has nothing to do
    # with this patch -- as it did, on the known-good 6.08.15 baseline, which
    # is how the harness gave itself away the second time.
    #
    # What matters is the BRANCH: a module inside POV's own debrids package
    # must be loaded by POV's own `import_module(..., package='debrids')` line
    # and never reach our fallback. The probe records which path ran.
    make_module(own, 'ai_probe_native', 'from-debrids')
    sys.path.insert(0, os.path.join(tree, 'resources', 'lib'))
    try:
        got2 = run_block(block, addons_root, own, ['ai_probe_native'])
    finally:
        sys.path.pop(0)
        sys.modules.pop('debrids.ai_probe_native', None)
        sys.modules.pop('debrids', None)
    check('%s: a module in POV\'s own folder still loads' % label,
          [n for _k, _s, n in got2] == ['ai_probe_native'],
          'append got %r' % ([n for _k, _s, n in got2],))
    check('%s: and it loads by POV\'s own route' % label,
          [getattr(x, 'tag', None) for _k, x, _n in got2] == ['from-debrids'],
          'the fallback must not be what makes POV\'s own scrapers work')

    # A name in NEITHER folder must not appear, and must not raise.
    got3 = run_block(block, addons_root, own, ['ai_absent_scraper'])
    check('%s: an unknown scraper name is simply absent' % label,
          got3 == [], repr(got3))

# ------------------------------------------------------------- sabotage
# The checks above pass trivially if the generated block is never really run,
# so each mutant breaks the shim in a way that can only show up in EXECUTION.
#
# Both mutants are written against the module's OWN constants rather than
# against copies of its source text. A sabotage that sets an attribute the
# module no longer has is worse than none: it reports a guard as proven while
# proving nothing, which is exactly what happened once in
# test_pov_internal_scraper_shim.py.


def _only_old_shape(shim):
    """M1: carry only the pre-6.09.01 shape. This IS the state this release
    repaired, so on 6.09.01 the legacy scraper must not load."""
    shim._SHAPES = shim._SHAPES[-1:]


def _no_extra_dir(shim):
    """M2: keep the new shape but never add the legacy folder to the scan."""
    plain = shim._DIRS_PROLOGUE.splitlines(True)[0]
    shim._SHAPES = tuple((a, r.replace(shim._DIRS_PROLOGUE, plain))
                         for a, r in shim._SHAPES)


print('\n-- sabotage (against POV 6.09.01) --')
for label, mutate in (
        ('M1 only the pre-6.09.01 shape is carried', _only_old_shape),
        ('M2 the legacy folder is never added to the scan', _no_extra_dir)):
    caught = False
    detail = ''
    try:
        tree, verdict, addons_root = patched_tree('6901', mutate=mutate)
        if tree is None:
            detail = 'no tree'
        else:
            sources = os.path.join(tree, *SOURCES_REL)
            own = os.path.join(tree, 'resources', 'lib', 'debrids')
            legacy = os.path.join(tree, 'resources', 'lib', 'scrapers')
            make_module(legacy, 'ai_probe_scraper', 'from-legacy')
            block = extract_block(sources)
            got = run_block(block, addons_root, own, ['ai_probe_scraper'])
            tags = [getattr(x, 'tag', None) for _k, x, _n in got]
            if 'from-legacy' not in tags:
                caught = True
    except Exception as exc:
        caught = True
        detail = 'raised %r' % (exc,)
    check(label + ' -> caught', caught,
          detail or 'mutant SURVIVED -- the legacy scraper still loaded, so '
                    'the checks above do not test what they claim')

for d in _TMP:
    shutil.rmtree(d, ignore_errors=True)

print('\n%d check(s) failed' % len(FAIL))
sys.exit(1 if FAIL else 0)
