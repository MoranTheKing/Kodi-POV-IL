"""Keep the real legacy OTA manifest available after modular public releases."""

import importlib.util
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LegacyUpdatePublicationTests(unittest.TestCase):
    def test_latest_public_note_has_a_legacy_bridge_manifest(self):
        # The addon builder removes old dist ZIPs in its temporary checkout.
        # Pages deployment separately requires the referenced binary on disk.
        load_tool('check_legacy_update_publication').verify(ROOT, require_artifact=False)

    def test_legacy_automatic_reader_resolves_the_published_bridge(self):
        delivery = load_tool('test_quick_update_delivery')
        note, artifact = load_tool('check_legacy_update_publication').verify(
            ROOT, require_artifact=False)
        tools = types.ModuleType('resources.libs.common.tools')
        seen = []

        def open_url(url):
            seen.append(url)
            self.assertTrue(url.endswith('/build_versions/' + note + '.txt'))
            return types.SimpleNamespace(text=(ROOT / 'wizard/assets/build_versions'
                                              / (note + '.txt')).read_text(encoding='utf-8'))

        tools.open_url = open_url
        modules = {name: types.ModuleType(name) for name in
                   ('resources', 'resources.libs', 'resources.libs.common')}
        modules['resources.libs.common'].tools = tools
        modules['resources.libs.common.tools'] = tools
        config = types.SimpleNamespace(BUILDFILE='https://example.invalid/build.txt')
        with patch.dict(sys.modules, modules):
            check = delivery._function_from_file(delivery.CHECK, 'check_build',
                                                 {'CONFIG': config, 're': delivery.re})
            result = check('Kodi POV IL - FENtastic', 'gui', release_id=note)
        self.assertTrue(result.endswith('/dist/' + artifact))
        self.assertEqual(len(seen), 1)

    def test_missing_snapshot_or_artifact_blocks_publication(self):
        check = load_tool('check_legacy_update_publication')
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            notes = root / 'wizard/assets/notification_files'
            notes.mkdir(parents=True)
            (notes / 'quick_update.txt').write_text('669|||Update\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'manifest is missing'):
                check.verify(root)
            versions = root / 'wizard/assets/build_versions'
            versions.mkdir()
            (versions / '669.txt').write_text(
                'gui="https://github.com/MoranTheKing/Kodi-POV-IL/raw/main/dist/'
                'Kodi-POV-IL-FENtastic-quickfix-0.1.612.zip"\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'artifact is absent'):
                check.verify(root)

    def test_new_note_recovers_devices_that_exhausted_the_missing_manifest(self):
        delivery = load_tool('test_quick_update_delivery')
        with tempfile.TemporaryDirectory() as profile:
            data = Path(profile) / 'addon_data/plugin.program.kodipovilwizard'
            data.mkdir(parents=True)
            (data / 'quick_update_state.json').write_text(
                '{"applied":666,"tries":{"668":2}}', encoding='utf-8')
            _config, _window, _log, stopped = delivery._run_startup_case(
                profile=profile, stored='666', remote='668')
            self.assertEqual(stopped, [])
            _config, _window, _log, recovered = delivery._run_startup_case(
                profile=profile, stored='666', remote='669')
            self.assertEqual(recovered[0][0], 'install')
            self.assertEqual(recovered[0][1]['expected_note_id'], '669')


if __name__ == '__main__':
    unittest.main()
