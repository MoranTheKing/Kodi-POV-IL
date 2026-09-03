"""Every model the picker offers has a real quota number behind it.

WHY THIS FILE EXISTS. `gemini_quota.MODEL_LIMITS` carries a comment asking the
next person to "keep this in sync with the model dropdown in settings.xml AND
translate._gemini_free_rpm_cap()". A comment is not a check, and there are now
four tables that have to agree about one list of models:

  * the `<option>` list in settings.xml            (what a user can pick)
  * gemini_quota.MODEL_LIMITS                      (the free daily cap shown)
  * translate._gemini_free_rpm_cap()               (how hard we pace requests)
  * service._maybe_bump_gemini_model*()            (what a migration writes)

The failure this catches is quiet, which is the point. A model in the picker
with no MODEL_LIMITS row falls through to DEFAULT_LIMIT = 500 -- the Flash-Lite
number -- so a regular-Flash user is told they have 500 requests a day when the
real free cap is 20, and finds out from a hard 429 instead. And a migration
that writes a model id the picker no longer lists leaves the settings screen
showing a blank where the model should be.

Neither raises. Neither appears in a log. Both are one forgotten line.

Run: python3 tools/test_gemini_model_table.py
"""
import ast
import importlib.util
import os
import re
import sys
import types
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')
SETTINGS = os.path.join(ADDON, 'resources', 'settings.xml')
QUOTA = os.path.join(LIB, 'gemini_quota.py')
TRANSLATE = os.path.join(LIB, 'translate.py')
SERVICE = os.path.join(ADDON, 'service.py')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def load(path, name):
    for n in list(sys.modules):
        if n.startswith(('xbmc', 'resources', name)):
            sys.modules.pop(n, None)
    for stub in ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs'):
        sys.modules[stub] = types.ModuleType(stub)
    sys.modules['xbmcvfs'].translatePath = lambda p: p
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    pkg.lib = lib
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda m, level='INFO': None
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------ what the picker offers
root = ET.parse(SETTINGS).getroot()
picker = next((s for s in root.iter('setting') if s.get('id') == 'model'), None)
check('the model picker exists', picker is not None)
PICKER = [(o.text or '').strip() for o in picker.iter('option')] if picker else []
default_node = picker.find('default') if picker is not None else None
DEFAULT = (default_node.text or '').strip() if default_node is not None else ''

check('the picker lists models', len(PICKER) >= 2, repr(PICKER))
check('the picker has no duplicates', len(set(PICKER)) == len(PICKER),
      repr(PICKER))
check('the default is one of the offered models', DEFAULT in PICKER,
      '{0!r} not in {1}'.format(DEFAULT, PICKER))

# 3.8 replaced 3.7. Pinned by name because it is the change this release makes;
# if a later release moves on again, this pair moves with it.
check('the picker offers gemini-3.8-flash', 'gemini-3.8-flash' in PICKER,
      repr(PICKER))
check('the picker no longer offers gemini-3.7-flash',
      'gemini-3.7-flash' not in PICKER, repr(PICKER))

# ------------------------------------------------------------- the quota table
quota = load(QUOTA, 'gmt_quota')
missing = [m for m in PICKER if m not in quota.MODEL_LIMITS]
check('every model in the picker has a free-tier daily cap', not missing,
      'no MODEL_LIMITS row for: {0} (they would silently get the {1}/day '
      'Flash-Lite fallback)'.format(missing, quota.DEFAULT_LIMIT))

for m in PICKER:
    if m not in quota.MODEL_LIMITS:
        continue
    limit = quota.MODEL_LIMITS[m]
    lite = 'flash-lite' in m
    check('%s has a cap that matches its family' % m,
          (limit == 500) if lite else (limit == 20),
          'cap is {0} for a {1} model'.format(
              limit, 'Flash-Lite' if lite else 'regular Flash'))

# Retired ids must NOT be dropped: a stored setting outlives a dropdown, and a
# missing row hands a regular-Flash device the 500/day Flash-Lite number.
for retired in ('gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash'):
    check('retired id %s still has its cap' % retired,
          quota.MODEL_LIMITS.get(retired) == 20,
          'a device that has not run the migration would be told '
          '{0}/day'.format(quota.DEFAULT_LIMIT))

check('the quota fallback is still the Flash-Lite number',
      quota.DEFAULT_LIMIT == 500)
check('the fallback model is one the picker offers',
      quota.MODEL_TRACKED in PICKER,
      '{0!r} not in {1}'.format(quota.MODEL_TRACKED, PICKER))

# --------------------------------------------------------------- the RPM cap
translate_src = open(TRANSLATE, encoding='utf-8').read()
ns = {}
fn = re.search(r'def _gemini_free_rpm_cap\(model\):.*?\n(?=\n\n)',
               translate_src, re.DOTALL)
check('_gemini_free_rpm_cap is still there', fn is not None)
if fn:
    exec(compile(fn.group(0), '<rpm>', 'exec'), ns)
    cap = ns['_gemini_free_rpm_cap']
    for m in PICKER:
        want = 14 if 'flash-lite' in m else 4
        check('%s paces at the cap for its family' % m, cap(m) == want,
              'cap(%r) = %r, expected %r' % (m, cap(m), want))
    check('an unknown model falls back to the most conservative pace',
          cap('something-else') == 4 and cap('') == 4)

# ------------------------------------------------------- the migrations agree
service_src = open(SERVICE, encoding='utf-8').read()
tree = ast.parse(service_src)
written = set()
migrations = set()
for node in ast.walk(tree):
    if not isinstance(node, ast.FunctionDef):
        continue
    if not node.name.startswith('_maybe_bump_gemini_model'):
        continue
    migrations.add(node.name)
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        target = getattr(call.func, 'attr', '')
        if target != 'set_setting':
            continue
        if not call.args or not isinstance(call.args[0], ast.Constant):
            continue
        if call.args[0].value != 'model':
            continue
        # set_setting('model', <literal>) -- the literal is what lands on disk
        if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
            written.add(call.args[1].value)
    # ...and the dict-based form: {...}.get(cur)
    for d in ast.walk(node):
        if isinstance(d, ast.Dict):
            for v in d.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str) \
                        and v.value.startswith('gemini-'):
                    written.add(v.value)

check('the model-bump migrations were found', len(migrations) >= 2,
      repr(sorted(migrations)))
bad = sorted(w for w in written if w not in PICKER)
check('no migration writes a model the picker cannot show', not bad,
      'these are written by a migration but are not options: {0}'.format(bad))

# Each migration must own a distinct marker id -- reusing one makes the new
# migration a no-op for exactly the devices that took the previous one.
# One distinct marker per bump migration. Counting them against the number of
# migrations rather than against a fixed number is the check that survives the
# next release: reusing a marker makes the new migration a no-op for exactly
# the devices that took the previous one, which is the mistake service.py's own
# comment records having made once already.
markers = sorted(set(re.findall(r"_gemini_model_bump_v\d+", service_src)))
check('each bump migration has its own marker',
      len(markers) == len(migrations),
      '{0} migration(s) {1} but {2} marker(s) {3}'.format(
          len(migrations), sorted(migrations), len(markers), markers))
declared = {s.get('id') for s in root.iter('setting')}
undeclared = [m for m in markers if m not in declared]
check('every bump marker is declared in settings.xml', not undeclared,
      repr(undeclared))

print('\n%d check(s) failed' % len(FAIL))
sys.exit(1 if FAIL else 0)
