"""Exercise the shipped skin search buttons against copied real XML files."""

import shutil
import sys
import tempfile
import unittest
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'service.subtitles.kodipovilai'
sys.path.insert(0, str(ADDON))
from resources.lib import fentastic_search_patcher as patcher  # noqa: E402
from resources.lib import search_provider  # noqa: E402


class _VFS:
    def __init__(self, home):
        self.home = Path(home)

    def translatePath(self, path):
        return str(self.home / path.removeprefix('special://home/').replace('/', '\\'))

    @staticmethod
    def exists(path):
        return Path(path).exists()

    @staticmethod
    def File(path, mode='r'):
        return open(path, mode, encoding='utf-8')


class SearchSkinTests(unittest.TestCase):
    def test_service_repairs_search_before_first_picker_click(self):
        service = ast.parse((ADDON / 'service.py').read_text('utf-8'))
        main = next(node for node in service.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'main')
        calls = [node.func.id for node in ast.walk(main)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertIn('_maybe_patch_hub_search', calls)

    def test_provider_round_trip_all_three_hub_skins(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            targets = (
                ('skin.fentastic', 'Home.xml'),
                ('skin.estuary', 'Home.xml'),
                ('skin.povil.nox', 'Home_nox.xml'),
                ('skin.povil.nox', 'Custom_nox_main_menu.xml'),
            )
            for skin, filename in targets:
                dst = home / 'addons' / skin / 'xml' / filename
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / skin / 'xml' / filename, dst)
            original_vfs = patcher.xbmcvfs
            original_current = search_provider.current
            patcher.xbmcvfs = _VFS(home)
            try:
                for provider in ('umbrella', 'pov', 'umbrella'):
                    search_provider.current = lambda value=provider: value
                    self.assertEqual(patcher.ensure_patched(), 'patched')
                    target = search_provider.HUB_ONCLICK[provider]
                    for skin, filename in targets[:3]:
                        contents = (home / 'addons' / skin / 'xml' / filename).read_text('utf-8')
                        self.assertIn(target, contents, skin)
                    nox_menu = (home / 'addons' / targets[3][0] / 'xml' /
                                targets[3][1]).read_text('utf-8')
                    self.assertIn(search_provider.HUB_PATH[provider], nox_menu)
                    self.assertEqual(patcher.ensure_patched(), 'unchanged')
            finally:
                patcher.xbmcvfs = original_vfs
                search_provider.current = original_current


if __name__ == '__main__':
    unittest.main()
