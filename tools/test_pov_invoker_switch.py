"""The POV reuse-language-invoker switch, exercised end to end.

`pov_language_invoker_guard` used to hard-code its target: reuse OFF, always,
because concurrent POV invocations sharing one Python interpreter is a native
crash that closes Kodi. Since 0.2.507 the direction comes from our own
`pov_fast_navigation` setting instead, because OFF was measured at a fixed
~1.75s of Python import time on EVERY POV menu press and the owner wanted that
choice to exist.

Two properties matter, and neither is provable by reading:

  1. OFF is the destination of EVERY failure. No kodi_utils, a settings store
     that raises, a setting nobody has ever touched -- all of them land on
     'false'. The only route to 'true' is an explicit true. `_wanted()`'s five
     states are pinned in tools/test_repair_order.py, next to the ordering
     property they replaced.

  2. Whichever value it picks reaches BOTH halves POV keeps the flag in -- the
     hidden setting and POV's addon.xml -- from a SINGLE read, so the halves
     can never disagree. That is what this file is for. It builds a POV-shaped
     addon.xml on disk and runs ensure_patched() for real in both directions.

ONLY KODI IS FAKED, AND THAT IS THE WHOLE POINT OF THE SHAPE BELOW. The first
version of this file stubbed `_write_setting` and `_read_setting` with its own
two-line implementations -- and then claimed to prove that the chosen value
reaches both halves. It could not: a `_write_setting` that ignored its argument
entirely and always wrote 'false' passed every check, because the test had
replaced the function it was supposed to be testing. Found by sabotage, which
is why the sabotage pass at the end exists rather than being taken on trust.
What is faked now is `xbmcvfs` and `xbmcaddon` -- Kodi's own modules, injected
into sys.modules -- so `_addon_xml_path`, `_read_setting`, `_write_setting`,
`_xml_state` and `_write_xml` are all the real ones. The only stub left is
kodi_utils, which is the INPUT under test, and whose five states are pinned
next door.

Plus the join nothing else checks: the setting id the guard asks Kodi for has
to be the id settings.xml DECLARES, and its label/help have to exist in both
languages. Rename one and not the other and the switch silently does nothing
-- no error, no log line, just a control that never takes effect.

Run: python3 tools/test_pov_invoker_switch.py
"""
import io
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(
    HERE, '..', 'addons', 'service.subtitles.kodipovilai'))
GUARD = os.path.join(ADDON, 'resources', 'lib',
                     'pov_language_invoker_guard.py')
SETTINGS = os.path.join(ADDON, 'resources', 'settings.xml')
LANGS = ('resource.language.en_gb', 'resource.language.he_il')

FAIL = []


def check(name, cond, detail=''):
    if cond:
        print('ok   %s' % name)
    else:
        FAIL.append(name)
        print('FAIL %s%s' % (name, ('  -- ' + detail) if detail else ''))


with io.open(GUARD, encoding='utf-8') as fh:
    GSRC = fh.read()


class _KU(object):
    """Stand-in for resources.lib.kodi_utils, counting what it is asked."""

    def __init__(self, value):
        self.value = value
        self.calls = 0

    def get_bool(self, key, default=False):
        self.calls += 1
        return self.value

    def log(self, *a, **k):
        pass


class _FakeAddon(object):
    """xbmcaddon.Addon for POV, backed by a dict. getSetting returns '' for an
    id that has never been written, which is what Kodi does."""

    def __init__(self, store):
        self.store = store

    def getSetting(self, key):
        return self.store.get(key, '')

    def setSetting(self, key, value):
        self.store[key] = value


def install_kodi(tmpdir, store):
    """Put fake xbmcvfs/xbmcaddon in sys.modules and return them. Everything
    the guard does with POV -- finding addon.xml, reading and writing the
    hidden setting -- then runs through its own real code."""
    vfs = types.ModuleType('xbmcvfs')
    vfs.translatePath = lambda p: (
        tmpdir + os.sep if p.startswith('special://home/addons/') else p)
    sys.modules['xbmcvfs'] = vfs

    addon = types.ModuleType('xbmcaddon')
    addon.Addon = lambda addon_id=None: _FakeAddon(store)
    sys.modules['xbmcaddon'] = addon
    return vfs, addon


def load(ku, src=None):
    mod = types.ModuleType('_guard_e2e')
    mod.__file__ = GUARD
    exec(compile(src or GSRC, GUARD, 'exec'), mod.__dict__)
    mod.kodi_utils = ku
    return mod


POV_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<addon id="plugin.video.pov" name="POV" version="6.08.13">\n'
    '\t<requires><import addon="xbmc.python" version="3.0.0"/></requires>\n'
    '\t<extension point="xbmc.python.pluginsource"'
    ' library="resources/lib/router.py">\n'
    '\t\t<provides>video</provides>\n'
    '\t</extension>\n'
    '\t<reuselanguageinvoker>%s</reuselanguageinvoker>\n'
    '</addon>\n')


def run(tmpdir, fast, setting_now, xml_now, src=None, quiet=False):
    """ensure_patched() against a real file and a real settings round-trip.
    Returns (status, setting_after, xml_after, get_bool_calls)."""
    path = os.path.join(tmpdir, 'addon.xml')
    with io.open(path, 'w', encoding='utf-8') as fh:
        fh.write(POV_XML % xml_now)

    store = {'reuse_language_invoker': setting_now}
    install_kodi(tmpdir, store)

    ku = _KU(fast)
    mod = load(ku, src)
    if not quiet:
        check('  the guard found POV where we put it',
              mod._addon_xml_path() == path,
              '%r != %r' % (mod._addon_xml_path(), path))

    status = mod.ensure_patched()
    with io.open(path, encoding='utf-8') as fh:
        after = fh.read()
    found = re.findall(r'<reuselanguageinvoker>([a-z]*)</reuselanguageinvoker>',
                       after)
    if not quiet:
        check('  the rewritten addon.xml still has exactly one flag',
              len(found) == 1, repr(found))
    return (status, store['reuse_language_invoker'],
            (found[0] if found else None), ku.calls)


def main():
    import tempfile
    root = tempfile.mkdtemp(prefix='povinv')
    # _addon_xml_path builds special://home/addons/<id>/addon.xml, so the fake
    # translatePath's answer has to be a directory of that shape or the real
    # function would not find the file.
    tmp = os.path.join(root, 'plugin.video.pov')
    os.makedirs(tmp)

    print('=== fast OFF (the default): the guard holds POV at false ===')
    st, setting, xml, calls = run(tmp, False, 'false', 'false')
    check('nothing to do when both halves already say false',
          st == 'already_set', st)
    check('...and neither half moved', (setting, xml) == ('false', 'false'))
    check('...and the setting was read exactly once', calls == 1, calls)

    st, setting, xml, _ = run(tmp, False, 'false', 'true')
    check('a POV self-update that restored its own addon.xml is repaired',
          st == 'patched', st)
    check('...and the xml is false again', xml == 'false', xml)

    st, setting, xml, _ = run(tmp, False, 'true', 'true')
    check('a device that has never been guarded gets both halves',
          st == 'patched', st)
    check('...setting false', setting == 'false', setting)
    check('...xml false', xml == 'false', xml)

    print()
    print('=== fast ON: the same machinery, aimed the other way ===')
    st, setting, xml, calls = run(tmp, True, 'false', 'false')
    check('turning the switch on writes BOTH halves', st == 'patched', st)
    check('...setting true', setting == 'true', setting)
    check('...xml true', xml == 'true', xml)
    check('...and it still read the setting exactly once', calls == 1, calls)

    st, setting, xml, _ = run(tmp, True, 'true', 'true')
    check('POV shipped true and we want true -> nothing written',
          st == 'already_set', st)
    check('...and both halves are still true', (setting, xml) == ('true',
                                                                  'true'))

    st, setting, xml, _ = run(tmp, True, 'true', 'false')
    check('a half-applied state is finished, not half-undone',
          st == 'patched', st)
    check('...xml true', xml == 'true', xml)

    print()
    print('=== the halves are never left disagreeing ===')
    for fast in (False, True):
        for s0 in ('false', 'true'):
            for x0 in ('false', 'true'):
                st, setting, xml, _ = run(tmp, fast, s0, x0)
                check('fast=%s setting=%s xml=%s -> both halves agree'
                      % (fast, s0, x0), setting == xml, '%s vs %s'
                      % (setting, xml))
                check('  ...and they agree with what was asked for',
                      setting == ('true' if fast else 'false'), setting)

    print()
    print('=== the caller can pass the direction in, but not widen it ===')
    # service.py reads _wanted() once and hands it to ensure_patched, so the
    # write and the log line it prints describe the same decision. A parameter
    # is a way in, though, so it must not become a way to ASK for FAST without
    # the setting saying so.
    for passed, label in ((None, 'None'), ('', 'empty'), ('yes', 'garbage'),
                          ('TRUE', 'wrong case'), (True, 'a bool')):
        path = os.path.join(tmp, 'addon.xml')
        with io.open(path, 'w', encoding='utf-8') as fh:
            fh.write(POV_XML % 'true')
        store = {'reuse_language_invoker': 'true'}
        install_kodi(tmp, store)
        mod = load(_KU(False))          # the SETTING says safe
        mod.ensure_patched(passed)
        check('a caller passing %s cannot force FAST' % label,
              store['reuse_language_invoker'] == 'false',
              'wrote %r' % store['reuse_language_invoker'])

    # ...and the honest case still works: a caller that already knows
    mod = load(_KU(False))
    path = os.path.join(tmp, 'addon.xml')
    with io.open(path, 'w', encoding='utf-8') as fh:
        fh.write(POV_XML % 'false')
    store = {'reuse_language_invoker': 'false'}
    install_kodi(tmp, store)
    mod = load(_KU(False))
    ku = mod.kodi_utils
    mod.ensure_patched(mod.FAST)
    check('a caller that passes FAST is obeyed without re-reading',
          store['reuse_language_invoker'] == 'true' and ku.calls == 0,
          'wrote %r after %d reads' % (store['reuse_language_invoker'],
                                       ku.calls))

    print()
    print('=== the log line explains the direction that was actually written ===')
    # This lives in the guard and not in service.py because service.py needs a
    # whole Kodi to import and so cannot be tested at all. A ternary written
    # there would be a coin flip nobody would notice landing wrong.
    g = load(_KU(False))
    check('SAFE is explained as the crash fix',
          'crash' in g.describe(g.SAFE), g.describe(g.SAFE))
    check('FAST is explained as a risk that was accepted',
          'risk' in g.describe(g.FAST), g.describe(g.FAST))
    check('...and the two do not say the same thing',
          g.describe(g.SAFE) != g.describe(g.FAST))
    check('...and the FAST one names the setting to look for',
          g.SETTING_FAST in g.describe(g.FAST), g.describe(g.FAST))
    for junk in (None, '', 'yes', True):
        check('a direction it does not recognise still gets a line (%r)' % junk,
              bool(g.describe(junk)))

    print()
    print('=== the id the guard asks for is the id Kodi declares ===')
    mod = load(_KU(False))
    with io.open(SETTINGS, encoding='utf-8') as fh:
        sx = fh.read()
    m = re.search(r'<setting\s+id="%s"[^>]*>' % re.escape(mod.SETTING_FAST), sx)
    check('settings.xml declares %s' % mod.SETTING_FAST, m is not None,
          'the guard would read an undeclared id, get the default, and the '
          'control would never do anything')
    decl = m.group(0) if m else ''
    check('...as a boolean', 'type="boolean"' in decl, decl)
    check('...defaulting to false -- SAFE out of the box',
          re.search(r'id="%s".*?<default>false</default>'
                    % re.escape(mod.SETTING_FAST), sx, re.S) is not None)

    ids = re.findall(r'(?:label|help)="(\d+)"', decl)
    check('...with a label and a help string', len(ids) == 2, ids)
    for lang in LANGS:
        po = os.path.join(ADDON, 'resources', 'language', lang, 'strings.po')
        with io.open(po, encoding='utf-8') as fh:
            src = fh.read()
        for sid in ids:
            check('%s defines #%s' % (lang, sid),
                  ('msgctxt "#%s"' % sid) in src)
        dupes = [i for i in ids
                 if src.count('msgctxt "#%s"' % i) > 1]
        check('%s defines each of them once' % lang, not dupes, repr(dupes))

    print()
    print('=== SABOTAGE: the checks above must be able to fail ===')
    # Every one of these is a plausible way to get the switch wrong, and the
    # list is not decorative: the FIRST version of this file stubbed
    # _write_setting with its own implementation, and sabotage 2 sailed
    # straight through it. In memory, never on disk -- a test that edits the
    # add-on it is testing is one crash away from shipping the sabotage.
    def broken(old, new):
        assert GSRC.count(old) == 1, old
        return GSRC.replace(old, new, 1)

    SABOTAGES = (
        ('the addon.xml write ignores the value it was given',
         broken("+ match.group(1) + wanted.encode('ascii') + match.group(5)",
                "+ match.group(1) + SAFE.encode('ascii') + match.group(5)")),
        ('the setting write ignores the value it was given',
         broken('setSetting(SETTING_ID, wanted)',
                'setSetting(SETTING_ID, SAFE)')),
        ('the two halves each read the setting for themselves',
         broken('    setting_ok = cur == wanted',
                '    setting_ok = cur == _wanted()')),
        ('SAFE and FAST are swapped',
         broken("SAFE = 'false'\nFAST = 'true'",
                "SAFE = 'true'\nFAST = 'false'")),
    )
    for name, src in SABOTAGES:
        bit = False
        for fast in (False, True):
            for s0 in ('false', 'true'):
                for x0 in ('false', 'true'):
                    try:
                        _, setting, xml, calls = run(tmp, fast, s0, x0,
                                                     src, True)
                    except Exception:
                        bit = True
                        continue
                    want = 'true' if fast else 'false'
                    # The call count is a property in its own right, not a
                    # detail: a guard that asks twice can be handed two
                    # different answers by a setting changed mid-pass, and
                    # then writes the two halves disagreeing. With a constant
                    # stub the VALUES come out identical, so counting is the
                    # only way this loop can see it at all.
                    if setting != want or xml != want or calls != 1:
                        bit = True
        check('SABOTAGE: %s is caught' % name, bit,
              'this test cannot see the mistake it claims to prevent')

    print()
    if FAIL:
        print('%d FAILURE(S): %s' % (len(FAIL), ', '.join(FAIL)))
        return 1
    print('ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
