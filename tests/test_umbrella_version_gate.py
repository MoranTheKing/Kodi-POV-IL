"""Umbrella moves only to the version the build's hooks were verified on.

Umbrella carries the kids-profile hooks and, since Wizard 0.4.68, follows its
developer's repository; a restructured Umbrella would have reached devices the
night it was published, as POV 6.10.16 did (21 Oct 2026). Wizard 0.4.69 holds
it with the POV gate and the same pin automation.
"""
import importlib.util
import io
import json
import os
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load('umbrella_gate', 'plugin.program.kodipovilwizard/resources/libs/pov_version_gate.py')
gen = load('umbrella_gen_manifest', '.github/scripts/gen_manifest.py')
UMBRELLA = 'plugin.video.umbrella'
PIN = {'id': UMBRELLA, 'version': '6.7.93', 'size': 3, 'sha256': 'b' * 64,
       'zip': 'https://github.com/MoranTheKing/Kodi-POV-IL/releases/download/addons-latest/x.zip'}


def umbrella_zip(version, requires=''):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(UMBRELLA + '/addon.xml',
                   '<addon id="%s" version="%s"><requires>%s</requires></addon>'
                   % (UMBRELLA, version, requires))
        z.writestr(UMBRELLA + '/resources/lib/modules/control.py', 'x = 1\n')
    return buf.getvalue()


def addons_db(path):
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE update_rules (id integer primary key, addonID TEXT, updateRule INTEGER)')
    conn.execute('CREATE TABLE installed (id integer primary key, addonID TEXT, enabled BOOLEAN)')
    conn.execute("INSERT INTO installed (addonID, enabled) VALUES ('plugin.video.umbrella', 1)")
    conn.commit()
    conn.close()


def rules(path):
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        return sorted(conn.execute('SELECT addonID, updateRule FROM update_rules').fetchall())
    finally:
        conn.close()


class Gate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.config = types.SimpleNamespace(ADDONS=str(root / 'addons'),
                                            ADDON_DATA=str(root / 'addon_data'),
                                            ADDON_ID='plugin.program.kodipovilwizard')
        host = root / 'addons' / UMBRELLA
        host.mkdir(parents=True)
        (host / 'addon.xml').write_text('<addon id="%s" version="6.7.85"/>' % UMBRELLA)
        self.db = str(root / 'Addons33.db')
        addons_db(self.db)
        self.calls = []
        self.package = umbrella_zip('6.7.93')
        self.local = {UMBRELLA: '6.7.85', 'script.module.requests': '2.31.0'}

    def updater(self):
        calls, local, package = self.calls, self.local, self

        class Updater:
            def get_local_version(self, addon_id):
                return local.get(addon_id)

            def _download_background_zip(self, url, dest, entry):
                calls.append(('download', url))
                with open(dest, 'wb') as out:
                    out.write(package.package)
        return Updater()

    def run_sync(self, manifest=None, **kw):
        def legacy():
            raise AssertionError('the POV legacy check never runs for Umbrella')
        return gate.sync(self.updater(), manifest or {'umbrella_pin': PIN}, kw.pop('fresh', False),
                         self.config, lambda msg: self.calls.append(('log', msg)), self.db,
                         legacy_host=legacy,
                         install=lambda path: self.calls.append(('install', os.path.basename(path))),
                         register=lambda: self.calls.append(('register',)),
                         repatch=lambda: {'applied': 4},
                         recover=lambda: None, addon_id=UMBRELLA,
                         moransubs_repair=lambda: self.calls.append(('moransubs',)) or True, **kw)

    def kinds(self):
        return [c[0] for c in self.calls if c[0] != 'log']

    def test_older_umbrella_gets_the_verified_version(self):
        self.assertEqual(self.run_sync(), 'installed 6.7.93')
        # MoranSubs patched the old tree at start; the new one is patched now
        self.assertEqual(self.kinds(), ['download', 'install', 'register', 'moransubs'])
        self.assertIn(('install', UMBRELLA + '-verified.zip'), self.calls)
        self.assertEqual(rules(self.db), [(UMBRELLA, 1)])

    def test_newer_umbrella_is_held_not_moved_back(self):
        self.local[UMBRELLA] = '6.7.94'
        self.assertEqual(self.run_sync(), 'held')
        self.assertEqual(self.kinds(), [])
        self.assertEqual(rules(self.db), [(UMBRELLA, 1)])

    def test_reads_its_own_pin_not_the_pov_one(self):
        self.assertEqual(self.run_sync({'pov_host_migration': dict(PIN, id='plugin.video.pov')}),
                         'no_pin')
        self.assertEqual(self.run_sync({'umbrella_pin': dict(PIN, id='plugin.video.pov')}),
                         'no_pin')

    def test_a_wizard_update_defers(self):
        self.assertEqual(self.run_sync(install_allowed=False), 'deferred')

    def test_a_dependency_the_device_has_older_waits(self):
        self.package = umbrella_zip('6.7.93', '<import addon="xbmc.python" version="3.0.0"/>'
                                              '<import addon="script.module.requests" version="2.32.0"/>'
                                              '<import addon="plugin.video.youtube" version="9" optional="true"/>'
                                              '<import addon="script.module.absent" version="1.0"/>')
        self.assertEqual(self.run_sync(), 'needs script.module.requests 2.32.0')
        self.assertNotIn('install', self.kinds())
        leftover = os.listdir(os.path.join(self.config.ADDON_DATA, self.config.ADDON_ID, 'ota-packages'))
        self.assertEqual(leftover, [UMBRELLA + '-waiting.json'])   # the zip itself is gone
        # next start: nothing changed -> no ~11 MB download again
        self.calls.clear()
        self.assertEqual(self.run_sync(), 'needs (unchanged)')
        self.assertEqual(self.kinds(), [])
        # the dependency updated -> download, install, marker removed
        self.local['script.module.requests'] = '2.32.0'
        self.assertEqual(self.run_sync(), 'installed 6.7.93')
        leftover = os.listdir(os.path.join(self.config.ADDON_DATA, self.config.ADDON_ID, 'ota-packages'))
        self.assertEqual(leftover, [])

    def test_an_umbrella_the_user_switched_off_is_left_alone(self):
        import sqlite3
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE installed SET enabled = 0 WHERE addonID = ?", (UMBRELLA,))
        conn.commit()
        conn.close()
        self.assertEqual(self.run_sync(), 'disabled')
        self.assertEqual(self.kinds(), [])

    def test_absent_umbrella_is_named_as_such(self):
        os.remove(os.path.join(self.config.ADDONS, UMBRELLA, 'addon.xml'))
        self.assertEqual(self.run_sync(), 'not_installed')

    def test_met_dependencies_install(self):
        self.package = umbrella_zip('6.7.93', '<import addon="script.module.requests" version="2.31.0"/>')
        self.assertEqual(self.run_sync(), 'installed 6.7.93')


class Pin(unittest.TestCase):
    def test_manifest_emits_the_pin_file(self):
        pin = json.loads((ROOT / '.github/umbrella-pin.json').read_text('utf-8'))
        self.assertEqual(gen._umbrella_pin(), pin)
        upstream = (ROOT / 'UPSTREAM_VERSIONS.txt').read_text('utf-8')
        self.assertIn('plugin.video.umbrella: %s' % pin['version'], upstream.splitlines())

    def test_only_the_owned_mirror_and_official_source(self):
        pin = gen._umbrella_pin()
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'pin.json'
            with mock.patch.object(gen, 'UMBRELLA_PIN', str(path)):
                for invalid in (dict(pin, zip=pin['upstream_zip']),
                                dict(pin, zip=pin['zip'].replace('MoranTheKing', 'other')),
                                dict(pin, upstream_zip='https://example.org/u.zip'),
                                dict(pin, sha256='0'), dict(pin, id='plugin.video.pov')):
                    path.write_text(json.dumps(invalid))
                    with self.assertRaises(ValueError):
                        gen._umbrella_pin()

    def test_wizard_gate_accepts_the_emitted_pin(self):
        self.assertIsNotNone(gate.pinned_entry({'umbrella_pin': gen._umbrella_pin()}, UMBRELLA))


class Bump(unittest.TestCase):
    def setUp(self):
        self.bump = load('auto_bump_umbrella', 'tools/auto_bump_pov_pin.py')
        self.bump.select(UMBRELLA)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.bump.PIN = self.dir / 'umbrella-pin.json'
        self.bump.UPSTREAM = self.dir / 'UPSTREAM_VERSIONS.txt'
        self.bump.PIN.write_text(json.dumps(self.bump.pin_for('6.7.93', b'old', 'u')))
        self.bump.UPSTREAM.write_text('plugin.video.pov: 6.10.18\nplugin.video.umbrella: 6.7.93\n')

    def run_bump(self, latest, data, seen):
        index = '<addons><addon id="%s" version="%s"/></addons>' % (UMBRELLA, latest)
        return self.bump.run(self.dir / 'out', fetcher=lambda url: index,
                             getter=lambda url: seen.append(url) or data,
                             verifier=lambda root, archive: None)

    def test_moves_the_umbrella_pin_and_line_only(self):
        seen = []
        code, line = self.run_bump('6.7.94', umbrella_zip('6.7.94'), seen)
        self.assertEqual(code, 0, line)
        self.assertEqual(seen, ['https://raw.githubusercontent.com/umbrellaplug/umbrellaplug.github.io'
                                '/master/omega/zips/plugin.video.umbrella/plugin.video.umbrella-6.7.94.zip'])
        pin = json.loads(self.bump.PIN.read_text())
        self.assertEqual((pin['id'], pin['version']), (UMBRELLA, '6.7.94'))
        self.assertTrue(pin['zip'].endswith('/addons-latest/official-plugin.video.umbrella-6.7.94.zip'))
        self.assertEqual(self.bump.UPSTREAM.read_text(),
                         'plugin.video.pov: 6.10.18\nplugin.video.umbrella: 6.7.94\n')
        with mock.patch.object(gen, 'UMBRELLA_PIN', str(self.bump.PIN)):
            self.assertEqual(gen._umbrella_pin()['version'], '6.7.94')

    def test_a_package_the_wizard_cannot_install_is_never_pinned(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr(UMBRELLA + '/addon.xml', '<addon id="%s" version="6.7.94"/>' % UMBRELLA)
            for n in range(2001):
                z.writestr('%s/f%d.py' % (UMBRELLA, n), '')
        code, line = self.run_bump('6.7.94', buf.getvalue(), [])
        self.assertEqual(code, 3)
        self.assertIn('installer limits', line)
        self.assertEqual(json.loads(self.bump.PIN.read_text())['version'], '6.7.93')


if __name__ == '__main__':
    unittest.main()
