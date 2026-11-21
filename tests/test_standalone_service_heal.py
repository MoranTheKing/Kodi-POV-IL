"""A standalone MoranSubs inside the build is replaced by the build's own (Wizard 0.5.42).

A viewer's log, 21 Nov 2026: the build's MoranSubs 0.3.105 had been replaced by the standalone 0.3.106 (the
edition published for a Kodi without the build). Its service ran the build's steps without their modules --
"cannot import name 'subs_chooser'" on every press of the subtitles button -- and the Wizard never replaced it:
the version matched the manifest's, and a newer one waits for a handoff bridge the standalone does not have.
"""
import ast
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'plugin.program.kodipovilwizard/resources/libs/modular_updater.py'


def methods(namespace, *names):
    tree = ast.parse(SOURCE.read_text('utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ModularUpdater')
    nodes = []
    for name in names:
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        node.decorator_list = []
        nodes.append(node)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SOURCE), 'exec'),
         namespace)
    return [namespace[name] for name in names]


def tree(addons, version, *files):
    base = Path(addons) / 'service.subtitles.kodipovilai'
    (base / 'resources' / 'lib').mkdir(parents=True)
    (base / 'addon.xml').write_text('<addon id="service.subtitles.kodipovilai" version="%s"/>' % version)
    for name in ('translate.py',) + files:
        (base / 'resources' / 'lib' / name).write_text('#')


class StandaloneOnDisk(unittest.TestCase):
    def check(self, version, *files):
        with tempfile.TemporaryDirectory() as addons:
            if version:
                tree(addons, version, *files)
            namespace = {'os': os, 'CONFIG': types.SimpleNamespace(ADDONS=addons)}
            fn, = methods(namespace, '_standalone_service_on_disk')
            return fn()

    def test_the_standalone_edition_is_told_apart(self):
        self.assertTrue(self.check('0.3.106'))

    def test_the_builds_own_trees_are_not(self):
        self.assertFalse(self.check('0.3.106', 'modular_service_handoff.py', 'subs_chooser.py'))
        self.assertFalse(self.check('0.3.106', 'modular_service_handoff.py'))
        self.assertFalse(self.check('0.3.106', 'subs_chooser.py'))

    def test_the_legacy_tree_owns_povs_repairs_and_is_never_taken(self):
        self.assertFalse(self.check('0.2.568'))

    def test_nothing_installed_is_no_standalone(self):
        self.assertFalse(self.check(None))


class ReplaceStandalone(unittest.TestCase):
    def run_case(self, playing=False, disable=True, enable=True, prepared=False, sha='a' * 64,
                 download_fails=False):
        events = []
        staged = types.ModuleType('resources.libs.staged_addon_install')
        staged.prepared_matches = lambda *_a: prepared
        staged.install = lambda *a, **k: events.append(('prepare', k.get('defer_swap')))
        staged.activate_prepared = lambda *_a: events.append('swap') or 240
        db = types.ModuleType('resources.libs.db')
        db.addon_database = lambda *_a: events.append('db')
        libs = types.ModuleType('resources.libs')
        libs.staged_addon_install = staged
        libs.db = db
        notification = Mock()
        rpc = lambda text: (events.append('disable') or json.dumps(
            {'result': 'OK'} if disable else {'error': {'message': 'cannot disable'}}))
        ota = tempfile.mkdtemp()
        namespace = {
            'json': json, 'os': os,
            'CONFIG': types.SimpleNamespace(ADDONS='addons', ADDON_DATA=ota, ADDON_ID='wiz', ADDONTITLE='QA'),
            'tools': types.SimpleNamespace(remove_file=lambda *_a: None),
            'logging': types.SimpleNamespace(log=lambda *_a, **_k: None),
            'xbmcgui': types.SimpleNamespace(Dialog=lambda: types.SimpleNamespace(notification=notification)),
            'xbmc': types.SimpleNamespace(LOGINFO=1, LOGERROR=4, executeJSONRPC=rpc,
                                          getCondVisibility=lambda *_a: playing,
                                          executebuiltin=lambda *_a: events.append('scan'))}
        fn, = methods(namespace, '_replace_standalone_service')

        def download(url, dest, entry):
            if download_fails:
                raise IOError('offline')
            events.append('download')
        owner = types.SimpleNamespace(
            _download_background_zip=download,
            _note_storage_failure=lambda *_a: None,
            _runtime_addon_enabled=lambda *_a: not disable,
            _enable_addon=lambda *_a: events.append('enable') or enable,
            _mark_service_disabled=lambda flag: events.append('mark' if flag else 'unmark'),
            _addon_enabled_state=lambda *_a: not disable)
        mod = {'id': 'service.subtitles.kodipovilai', 'version': '0.3.107', 'sha256': sha,
               'zip': 'https://example.invalid/ms.zip', 'size': 10}
        with patch.dict(sys.modules, {'resources': types.ModuleType('resources'), 'resources.libs': libs,
                                      'resources.libs.staged_addon_install': staged,
                                      'resources.libs.db': db}):
            result = fn(owner, mod)
        return result, events, notification

    def test_the_builds_package_is_verified_then_swapped_in(self):
        result, events, notice = self.run_case()
        self.assertTrue(result)
        self.assertEqual(events, ['download', ('prepare', True), 'mark', 'disable', 'swap', 'db', 'scan',
                                  'enable', 'unmark'])
        self.assertEqual(notice.call_args.args[1], 'עדכון הכתוביות הושלם.')

    def test_a_package_prepared_already_is_not_downloaded_again(self):
        result, events, _ = self.run_case(prepared=True)
        self.assertTrue(result)
        self.assertNotIn('download', events)

    def test_nothing_is_touched_while_something_plays(self):
        result, events, notice = self.run_case(playing=True)
        self.assertFalse(result)
        self.assertEqual(events, [])
        notice.assert_not_called()

    def test_a_service_that_does_not_stop_is_never_swapped(self):
        result, events, notice = self.run_case(disable=False)
        self.assertFalse(result)
        self.assertNotIn('swap', events)
        self.assertEqual((events[0], events[-1]), ('download', 'unmark'))
        notice.assert_not_called()

    def test_a_failed_enable_does_not_claim_success(self):
        result, events, notice = self.run_case(enable=False)
        self.assertFalse(result)
        self.assertIn('swap', events)
        self.assertIn('השירות לא התחיל', notice.call_args.args[1])

    def test_no_package_no_change(self):
        for options in ({'download_fails': True}, {'sha': 'short'}):
            result, events, notice = self.run_case(**options)
            self.assertFalse(result)
            self.assertNotIn('disable', events)
            notice.assert_not_called()


class Queued(unittest.TestCase):
    def test_the_same_version_of_the_other_edition_is_queued_and_replaced(self):
        src = SOURCE.read_text('utf8')
        check = src.index("and self._standalone_service_on_disk()):")
        self.assertLess(src.index("self._version_tuple(local_ver) == self._version_tuple(remote_ver)"), check)
        replace = src.index('self._replace_standalone_service(service_mod)')
        self.assertLess(replace, src.index("elif self._runtime_addon_enabled('service.subtitles.kodipovilai'):"))


if __name__ == '__main__':
    unittest.main()
