"""The favourites-refresh hook fits both shapes of POV 6.10.06's dialogs.py.

POV 6.10.06 was republished under the same version with dialogs.py importing
`kodi_utils as ku`. The hook's anchor was missing there, and a fresh install
stopped with "Fresh source patches are incomplete" (field log, Oct 2026).
"""
import importlib.util
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
ENGINE = WIZARD / 'resources/libs/patch_engine.py'
CONFIG = runpy.run_path(str(WIZARD / 'resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
ENTRY = next(e for e in CONFIG if e['id'] == 'wizard_fav_refresh_dialog')

FUNCTION = (
    "def favorites_choice(params):\n"
    "\tif str(tmdb_id) in ids:\n"
    "\t\taction, refresh = remove_from_sync, True\n"
    "\telse:\n"
    "\t\taction, refresh = add_to_sync, False\n"
    "\t%s.notify_success() if action() else %s.notify_error()\n"
    "\tif refresh: %scontainer_refresh()\n")


class FavRefreshAnchor(unittest.TestCase):
    def run_engine(self, text):
        xbmc = types.SimpleNamespace(LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
        logger = types.SimpleNamespace(log=Mock())
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {
                'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(),
                'xbmcvfs': types.SimpleNamespace(),
                'resources.libs.common': types.SimpleNamespace(logging=logger)}):
            spec = importlib.util.spec_from_file_location('fav_anchor_engine', ENGINE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            root = Path(tmp)
            target = root / ENTRY['target_file']
            target.parent.mkdir(parents=True)
            target.write_text(text, encoding='utf-8')

            class Engine(module.PatchEngine):
                @staticmethod
                def _resolve_paths(_aid, filename):
                    return str(root), str(root / filename)

                def _is_patch_enabled(self, entry):
                    return True
            first = Engine([dict(ENTRY)]).run()
            second = Engine([dict(ENTRY)]).run()
            return first, second, target.read_text(encoding='utf-8')

    def test_both_dialogs_shapes(self):
        for prefix, mod in (('', 'kodi_utils'), ('ku.', 'ku')):
            with self.subTest(prefix=prefix):
                first, second, text = self.run_engine(FUNCTION % (mod, mod, prefix))
                self.assertEqual(first['anchor_missing'], 0)
                self.assertEqual(first['applied'], 1)
                self.assertEqual(second['applied'], 0)
                self.assertEqual(second['skipped_current'], 1)
                self.assertIn(ENTRY['marker'], text)
                # the hook sits right before the refresh line
                hook_at = text.index("refresh = 'search' not in")
                self.assertLess(hook_at, text.index('if refresh: %scontainer_refresh()' % prefix))
                compile(text, 'dialogs.py', 'exec')


if __name__ == '__main__':
    unittest.main()
