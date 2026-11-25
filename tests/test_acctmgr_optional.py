"""Wizard 0.5.52: a new install no longer stops on Account Manager.

24 Nov 2026, 22:39 UTC: Account Manager's developer retired it ("End of Development") and removed
script.module.acctmgr and script.module.acctvwr from repository.709 and every other repository he runs.
The Wizard installed Account Manager from repository.709 as a core part of the build, so every new install
from then on stopped at 25% on it and ended "the installation did not complete -- script.module.acctmgr
(native core addon unavailable)" (field report, 25 Nov 2026, "everyone").

The build works without it (the services screen connects POV directly where it is missing): it is no
longer provisioned from a repository nor required to finish an install, and the menu's install takes it
only from the build's own manifest.
"""
import ast
import os
import sys
import types
import unittest

from test_provisioning_gate import _load_function, ROOT

LIBS = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'


def _version_tuple(v):
    return tuple(int(''.join(c for c in p if c.isdigit()) or 0) for p in str(v).split('.'))


class NoLongerRequired(unittest.TestCase):
    def test_provisioning_no_longer_asks_a_repository_for_it(self):
        source = (LIBS / 'modular_updater.py').read_text(encoding='utf-8')
        cls = next(n for n in ast.parse(source).body if getattr(n, 'name', '') == 'ModularUpdater')
        values = {}
        for node in cls.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') in (
                    'PROVISION_IDS', 'CORE_PROVISION_IDS'):
                values[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertEqual(set(values), {'PROVISION_IDS', 'CORE_PROVISION_IDS'})
        for name, ids in values.items():
            self.assertNotIn('script.module.acctmgr', ids, name)
            self.assertIn('plugin.video.pov', ids, name)
        self.assertNotIn("'script.module.acctmgr': 'repository.709'",
                         (LIBS / 'headless_installer.py').read_text(encoding='utf-8'))

    def complete(self, manifest_addons, versions, enabled):
        messages = []
        f = _load_function(LIBS / 'modular_updater.py', '_fresh_install_complete',
                           {'CONFIG': types.SimpleNamespace(get_setting=lambda _k: '2.0.12'),
                            'logging': types.SimpleNamespace(log=lambda m, **kw: messages.append(m)),
                            'xbmc': types.SimpleNamespace(
                                LOGERROR=4, getCondVisibility=lambda c: c[len('System.HasAddon('):-1] in enabled)},
                           class_name='ModularUpdater')
        # the real CORE_PROVISION_IDS
        source = (LIBS / 'modular_updater.py').read_text(encoding='utf-8')
        cls = next(n for n in ast.parse(source).body if getattr(n, 'name', '') == 'ModularUpdater')
        core = next(ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], 'id', '') == 'CORE_PROVISION_IDS')
        updater = types.SimpleNamespace(
            get_local_version=versions.get, OPTIONAL_SKINS=frozenset(), CORE_PROVISION_IDS=core,
            _pending_addon_receipt=lambda _a: False, _service_staged_for_restart=lambda *_a: False,
            _version_tuple=_version_tuple)
        return f(updater, {'addons': manifest_addons, 'config': {'config_version': '2.0.12'}}), messages

    def test_an_install_without_account_manager_is_complete(self):
        enabled = {'plugin.video.pov', 'plugin.video.idanplus', 'plugin.video.youtube',
                   'resource.language.he_il', 'skin.povil.onyx', 'script.fentastic.helper'}
        ok, messages = self.complete({'skin.povil.onyx': {'version': '1.0.39'}},
                                     {'skin.povil.onyx': '1.0.39'}, enabled)
        self.assertTrue(ok, messages)

    def test_a_manifest_that_ships_it_still_requires_it(self):
        enabled = {'plugin.video.pov', 'plugin.video.idanplus', 'plugin.video.youtube',
                   'resource.language.he_il', 'skin.povil.onyx', 'script.fentastic.helper'}
        versions = {'script.module.acctmgr': None}
        ok, messages = self.complete({'script.module.acctmgr': {'version': '1.2.1a'}}, versions, enabled)
        self.assertFalse(ok)
        self.assertIn('script.module.acctmgr (missing, expected 1.2.1a)', messages[0])
        versions['script.module.acctmgr'] = '1.2.1a'
        self.assertTrue(self.complete({'script.module.acctmgr': {'version': '1.2.1a'}}, versions, enabled)[0])


class ManualInstall(unittest.TestCase):
    """The menu's "install Account Manager" (and run_acctmgr on a device without it)."""

    def run_it(self, manifest_addons, local=None, enabled_after=True, download_error=None):
        calls, enabled = [], set()
        local = dict(local or {})

        class Updater:
            def __init__(self, background=False):
                calls.append(('background', background))

            def _load_manifest(self):
                return None if manifest_addons is None else {'addons': manifest_addons}

            def get_local_version(self, ident):
                return local.get(ident)

            _version_tuple = staticmethod(_version_tuple)

            def _download_background_zip(self, url, package, entry):
                if download_error:
                    raise download_error
                calls.append(('download', entry['id'], url))

            def _install_verified_module(self, package, entry, sha):
                calls.append(('install', entry['id'], sha))
                local[entry['id']] = entry['version']

            @staticmethod
            def _enable_addon(ident):
                calls.append(('enable', ident))
                if enabled_after:
                    enabled.add(ident)

        modular = types.ModuleType('resources.libs.modular_updater')
        modular.ModularUpdater = Updater
        sys.modules['resources.libs.modular_updater'] = modular
        self.addCleanup(sys.modules.pop, 'resources.libs.modular_updater', None)
        xbmc = types.SimpleNamespace(
            LOGINFO=1, LOGWARNING=2, LOGERROR=4,
            getCondVisibility=lambda cond: cond[len('System.HasAddon('):-1] in enabled,
            executebuiltin=lambda b: calls.append(('builtin', b)),
            Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda _s: False))
        f = _load_function(LIBS / 'wizard.py', 'ensure_acctmgr_installed', {
            'xbmc': xbmc, 'os': os, 'ACCTMGR_ID': 'script.module.acctmgr',
            'ACCTMGR_PARTS': ('script.module.acctvwr', 'script.module.acctmgr'),
            'CONFIG': types.SimpleNamespace(PACKAGES='pk'),
            'tools': types.SimpleNamespace(ensure_folders=lambda _p: None,
                                           remove_file=lambda p: calls.append(('removed', p))),
            'db': types.SimpleNamespace(addon_database=lambda ids, state, overwrite: calls.append(
                ('db', list(ids), state, overwrite))),
            'logging': types.SimpleNamespace(log=lambda m, **kw: calls.append(('log', m)))})
        return f(), calls

    ENTRY = {'script.module.acctvwr': {'version': '1.1.6a', 'zip': 'https://h/v.zip', 'sha256': 'b' * 64},
             'script.module.acctmgr': {'version': '1.2.1a', 'zip': 'https://h/a.zip', 'sha256': 'a' * 64}}

    def test_the_viewer_then_account_manager_come_from_the_manifest(self):
        ok, calls = self.run_it(self.ENTRY)
        self.assertIs(ok, True)
        steps = [c for c in calls if c[0] in ('download', 'install', 'db')]
        self.assertEqual(steps, [
            ('download', 'script.module.acctvwr', 'https://h/v.zip'),
            ('install', 'script.module.acctvwr', 'b' * 64),
            ('download', 'script.module.acctmgr', 'https://h/a.zip'),
            ('install', 'script.module.acctmgr', 'a' * 64),
            ('db', ['script.module.acctvwr', 'script.module.acctmgr'], 1, True)])
        self.assertIn(('builtin', 'UpdateLocalAddons'), calls)
        self.assertIn(('background', True), calls)
        # the downloaded zips never stay behind
        self.assertEqual([c[1] for c in calls if c[0] == 'removed'],
                         [os.path.join('pk', 'script.module.acctvwr-modular.zip'),
                          os.path.join('pk', 'script.module.acctmgr-modular.zip')])

    def test_a_current_viewer_is_not_downloaded_again(self):
        ok, calls = self.run_it(self.ENTRY, local={'script.module.acctvwr': '1.1.6a'})
        self.assertIs(ok, True)
        self.assertEqual([c[1] for c in calls if c[0] == 'download'], ['script.module.acctmgr'])
        self.assertIn(('db', ['script.module.acctvwr', 'script.module.acctmgr'], 1, True), calls)

    def test_a_manifest_that_does_not_offer_it_says_so_and_installs_nothing(self):
        for addons in ({}, {'script.module.acctvwr': self.ENTRY['script.module.acctvwr']}):
            ok, calls = self.run_it(addons)
            self.assertIsNone(ok)
            self.assertFalse([c for c in calls if c[0] in ('download', 'install', 'db')])

    def test_no_manifest_is_a_failure_not_a_withdrawal(self):
        ok, calls = self.run_it(None)
        self.assertIs(ok, False)
        self.assertFalse([c for c in calls if c[0] in ('download', 'install', 'db')])

    def test_a_failed_download_says_no(self):
        ok, calls = self.run_it(self.ENTRY, download_error=IOError('offline'))
        self.assertIs(ok, False)
        self.assertFalse([c for c in calls if c[0] in ('install', 'db')])
        self.assertEqual(len([c for c in calls if c[0] == 'removed']), 1)

    def test_kodi_not_enabling_it_says_no(self):
        ok, _calls = self.run_it(self.ENTRY, enabled_after=False)
        self.assertFalse(ok)

    def test_the_menu_tells_which(self):
        source = (LIBS / 'wizard.py').read_text(encoding='utf-8')
        body = source[source.index('def install_acctmgr_pilot'):source.index('def ensure_umbrella_installed')]
        self.assertIn('done = ensure_acctmgr_installed()', body)
        self.assertIn('if done is None:', body)
        self.assertIn('אינו זמין כרגע', body)
        self.assertIn('לא הצליחה', body)
        self.assertNotIn('post_install_provisioning', source[source.index('def ensure_acctmgr_installed'):
                                                            source.index('ACCTMGR_AUTO_SETTING =')])


if __name__ == '__main__':
    unittest.main()
