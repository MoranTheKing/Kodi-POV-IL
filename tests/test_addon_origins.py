"""Third-party add-ons get updates from their repositories; the build's don't.

Kodi 21 checks an add-on whose `installed.origin` is empty against the
OFFICIAL repositories only, and the headless installer wrote every content
add-on that way -- so POV stayed on 6.10.03 while repository.kodifitzwell
published 6.10.05. The same rule is what keeps repository.709's FENtastic,
published under the build's own ids, off the build's skin.
"""

import ast
import importlib.util
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


origins = _module(LIBS / 'addon_origins.py', 'addon_origins_test')
upstream = _module(ROOT / 'tools' / 'check_upstream_addons.py', 'upstream_test')


def _make_db(path, installed, offers):
    """installed: [(id, enabled, origin)]; offers: {repo: [(id, version)]}."""
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE installed (id INTEGER PRIMARY KEY, addonID TEXT, "
        "enabled BOOLEAN, installDate TEXT, lastUpdated TEXT, lastUsed TEXT, "
        "origin TEXT NOT NULL DEFAULT '', disabledReason INTEGER NOT NULL "
        "DEFAULT 0);"
        "CREATE TABLE addons (id INTEGER PRIMARY KEY, metadata BLOB, "
        "addonID TEXT, version TEXT);"
        "CREATE TABLE repo (id INTEGER PRIMARY KEY, addonID TEXT);"
        "CREATE TABLE addonlinkrepo (idRepo INTEGER, idAddon INTEGER);")
    for aid, enabled, origin in installed:
        conn.execute('INSERT INTO installed (addonID, enabled, origin) '
                     'VALUES (?, ?, ?)', (aid, enabled, origin))
    for repo_id, rows in offers.items():
        rid = conn.execute('INSERT INTO repo (addonID) VALUES (?)',
                           (repo_id,)).lastrowid
        for aid, ver in rows:
            pid = conn.execute('INSERT INTO addons (addonID, version) '
                               'VALUES (?, ?)', (aid, ver)).lastrowid
            conn.execute('INSERT INTO addonlinkrepo VALUES (?, ?)', (rid, pid))
    conn.commit()
    conn.close()


def _origins_of(path):
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute('SELECT addonID, origin FROM installed'))
    finally:
        conn.close()


class AddonOriginTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, 'Addons33.db')
        _make_db(self.db, installed=[
            ('plugin.video.pov', 1, ''),
            ('plugin.video.otaku', 1, ''),
            ('context.otaku', 1, ''),
            ('skin.fentastic', 1, ''),
            ('script.fentastic.helper', 1, ''),
            ('script.module.requests', 1, ''),
            ('script.module.twice', 1, ''),
            ('plugin.video.chosen', 1, 'repository.other'),
            ('plugin.video.orphan', 1, ''),
            ('plugin.video.deadrepo', 1, ''),
            ('repository.kodifitzwell', 1, ''),
            ('repository.otaku', 1, ''),
            ('repository.709', 1, ''),
            ('repository.xbmc.org', 1, 'b6a50484-93a0-4afb-a01c-8d17e059feda'),
            ('repository.off', 0, ''),
            ('repository.other', 1, ''),
        ], offers={
            'repository.kodifitzwell': [('plugin.video.pov', '6.10.05')],
            'repository.otaku': [('plugin.video.otaku', '5.3.3'),
                                 ('context.otaku', '1.0.35'),
                                 ('repository.otaku', '1.0')],
            'repository.709': [('skin.fentastic', '100.0.34'),
                               ('script.fentastic.helper', '100.6.28a'),
                               ('script.module.twice', '2.0')],
            'repository.xbmc.org': [('script.module.requests', '2.31.0')],
            'repository.other': [('plugin.video.chosen', '2.0'),
                                 ('script.module.twice', '2.1')],
            'repository.off': [('plugin.video.deadrepo', '1.0')],
        })

    def tearDown(self):
        for name in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, name))
        os.rmdir(self.dir)

    def test_content_addons_are_registered_to_their_only_repository(self):
        done = origins.repair(self.db)
        self.assertEqual(sorted(done), [
            ('context.otaku', 'repository.otaku'),
            ('plugin.video.otaku', 'repository.otaku'),
            ('plugin.video.pov', 'repository.kodifitzwell')])
        got = _origins_of(self.db)
        # The build's FENtastic keeps the empty origin that keeps 709's off it.
        self.assertEqual(got['skin.fentastic'], '')
        self.assertEqual(got['script.fentastic.helper'], '')
        # Official already updates it; two repositories are ambiguous; a
        # chosen origin, an unlisted add-on, a disabled repository and the
        # repositories themselves are all left as they are.
        self.assertEqual(got['script.module.requests'], '')
        self.assertEqual(got['script.module.twice'], '')
        self.assertEqual(got['plugin.video.chosen'], 'repository.other')
        self.assertEqual(got['plugin.video.orphan'], '')
        self.assertEqual(got['plugin.video.deadrepo'], '')
        self.assertEqual(got['repository.otaku'], '')
        self.assertEqual(origins.repair(self.db), [])

    def test_manifest_addons_are_never_registered(self):
        done = origins.repair(self.db, owned=('plugin.video.pov',))
        self.assertNotIn('plugin.video.pov', dict(done))
        self.assertEqual(_origins_of(self.db)['plugin.video.pov'], '')

    def test_the_installer_records_where_it_downloaded_from(self):
        done = origins.register(self.db, {
            'plugin.video.pov': 'repository.kodifitzwell',
            'script.module.requests': 'repository.xbmc.org',
            'skin.fentastic': 'repository.709',
            'repository.otaku': 'repository.otaku',
            'plugin.video.chosen': 'repository.kodifitzwell',
            'plugin.video.orphan': None})
        self.assertEqual(sorted(done), [
            ('plugin.video.pov', 'repository.kodifitzwell'),
            ('script.module.requests', 'repository.xbmc.org')])
        got = _origins_of(self.db)
        self.assertEqual(got['skin.fentastic'], '')
        self.assertEqual(got['plugin.video.chosen'], 'repository.other')

    def test_a_missing_database_is_never_created(self):
        path = os.path.join(self.dir, 'Addons99.db')
        self.assertEqual(origins.repair(path), [])
        self.assertEqual(origins.register(path, {'a': 'b'}), [])
        self.assertFalse(os.path.exists(path))

    def test_the_wizard_wires_both_paths(self):
        startup = (ROOT / 'plugin.program.kodipovilwizard' / 'startup.py'
                   ).read_text('utf-8')
        self.assertIn('addon_origins.repair(', startup)
        installer = (LIBS / 'headless_installer.py').read_text('utf-8')
        self.assertIn("'repo': repo_name", installer)
        self.assertIn('addon_origins.register(', installer)


def _heal():
    tree = ast.parse((LIBS / 'modular_updater.py').read_text('utf-8'))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == 'ModularUpdater')
    fn = next(n for n in cls.body
              if isinstance(n, ast.FunctionDef) and n.name == 'heal_missing_addons')
    namespace = {
        'xbmc': types.SimpleNamespace(
            getCondVisibility=lambda cond: cond.endswith('(skin.povil.nox)'),
            executebuiltin=lambda cmd: None, LOGWARNING=2, LOGERROR=3),
        'logging': types.SimpleNamespace(log=lambda *a, **k: None),
        'youtube_platform': types.SimpleNamespace(eligible=lambda ids: []),
    }
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=[fn], type_ignores=[])), 'heal', 'exec'), namespace)
    return namespace['heal_missing_addons']


class HealCaseTests(unittest.TestCase):
    def run_heal(self, enabled_in_kodi):
        enabled = []
        me = types.SimpleNamespace(
            _manifest={'addons': {
                'repository.Fishenzon': {'id': 'repository.Fishenzon'},
                'repository.otaku': {'id': 'repository.otaku'},
                'skin.povil.nox': {'id': 'skin.povil.nox'}}},
            _on_disk=lambda aid: True,
            _runtime_addon_enabled=lambda aid: enabled_in_kodi,
            _enable_addon=enabled.append,
            execute_updates=lambda mods: None,
            PROVISION_IDS=[], post_install_provisioning=lambda: None)
        _heal()(me)
        return enabled

    def test_a_mixed_case_id_kodi_already_enabled_is_left_alone(self):
        # HasAddon lowercases its argument, so it reads repository.Fishenzon
        # as absent; it was "enabled" again on every boot.
        self.assertEqual(self.run_heal(enabled_in_kodi=True),
                         ['repository.otaku'])

    def test_a_really_disabled_mixed_case_id_is_still_enabled(self):
        self.assertEqual(self.run_heal(enabled_in_kodi=False),
                         ['repository.Fishenzon', 'repository.otaku'])


class UpstreamCheckTests(unittest.TestCase):
    INDEX = ('<addons><addon id="plugin.video.pov" version="6.10.05"/>'
             '<addon id="plugin.video.pov" version="6.10.10"/>'
             '<addon id="plugin.video.otaku" name="x" version="5.3.3">'
             '</addon></addons>')

    def test_reports_only_moved_versions(self):
        newest = upstream.upstream_versions(fetcher=lambda url: self.INDEX)
        self.assertEqual(newest['plugin.video.pov'], '6.10.10')
        marker = upstream.read_marker(
            '# comment\nplugin.video.pov: 6.10.05\nplugin.video.otaku: 5.3.3\n')
        self.assertEqual(upstream.changes(marker, newest),
                         ['plugin.video.pov: 6.10.05 -> 6.10.10'])

    def test_an_unreadable_repository_is_skipped(self):
        warnings = []

        def fail(url):
            raise IOError('down')

        self.assertEqual(upstream.upstream_versions(fetcher=fail,
                                                    warn=warnings.append), {})
        self.assertTrue(warnings)

    def test_the_marker_lists_every_watched_addon(self):
        marker = upstream.read_marker(
            (ROOT / 'UPSTREAM_VERSIONS.txt').read_text('utf-8'))
        self.assertEqual(set(marker), {aid for aid, _u in upstream.WATCH})


if __name__ == '__main__':
    unittest.main()
