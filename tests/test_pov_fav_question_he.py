"""Wizard 0.5.47: POV's question on its own favourites, and its buttons, in Hebrew.

The owner, Nov 2026, from a screen in the QA Kodi: "Add To POV מועדפים?" with "Cancel" / "OK" -- POV's sentence
'%s POV %s?' with only the word "favourites" in Hebrew. Now "להוסיף למועדפים של POV?" / "להסיר מהמועדפים של POV?",
and every yes/no question of POV says "אישור" / "ביטול" (its strings 32839 / 32840).
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
IDS = ('pov_fav_question_he_add', 'pov_fav_question_he_remove', 'wizard_fav_refresh_dialog')
ENTRIES = [next(e for e in CONFIG if e['id'] == i) for i in IDS]
LABELS = runpy.run_path(str(WIZARD / 'resources/libs/patches/pov_ui_labels.py'))

# POV 6.11's favorites_choice, as it is (its text lines are the anchors)
FUNCTION = (
    "def favorites_choice(params):\n"
    "\tfrom indexers.local_api import local_favorites, add_to_sync, remove_from_sync\n"
    "\tmediatype, tmdb_id, title = params['mediatype'], params['tmdb_id'], params['title']\n"
    "\tcurrent_favorites = local_favorites(None, mediatype, 'all')\n"
    "\tif str(tmdb_id) in {i['tmdb_id'] for i in current_favorites}:\n"
    "\t\taction, refresh = remove_from_sync, True\n"
    "\t\ttext = '%s[CR][CR]%s POV %s?' % (title, ls(32603), ls(32453))\n"
    "\telse:\n"
    "\t\taction, refresh = add_to_sync, False\n"
    "\t\ttext = '%s[CR][CR]%s POV %s?' % (title, ls(32602), ls(32453))\n"
    "\tif not ku.confirm_dialog(text=text): return\n"
    "\tku.notify_success() if action('favorites', mediatype, tmdb_id, title) else ku.notify_error()\n"
    "\tif refresh: ku.container_refresh()\n")


class FavouritesQuestionInHebrew(unittest.TestCase):
    def patched(self):
        xbmc = types.SimpleNamespace(LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
        logger = types.SimpleNamespace(log=Mock())
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {
                'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace(),
                'resources.libs.common': types.SimpleNamespace(logging=logger)}):
            spec = importlib.util.spec_from_file_location('fav_question_engine', ENGINE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            root = Path(tmp)
            target = root / ENTRIES[0]['target_file']
            target.parent.mkdir(parents=True)
            target.write_text(FUNCTION, encoding='utf-8')

            class Engine(module.PatchEngine):
                @staticmethod
                def _resolve_paths(_aid, filename):
                    return str(root), str(root / filename)

                def _is_patch_enabled(self, entry):
                    return True
            first = Engine([dict(e) for e in ENTRIES]).run()
            second = Engine([dict(e) for e in ENTRIES]).run()
            return first, second, target.read_text(encoding='utf-8')

    def ask(self, text, in_favourites):
        """Run the patched favorites_choice; the question it asks."""
        asked = []
        ku = types.SimpleNamespace(confirm_dialog=lambda text: asked.append(text) and False,
                                   notify_success=Mock(), notify_error=Mock(), container_refresh=Mock())
        local_api = types.ModuleType('indexers.local_api')
        local_api.local_favorites = lambda *a: [{'tmdb_id': '7'}] if in_favourites else []
        local_api.add_to_sync = local_api.remove_from_sync = Mock()
        indexers = types.ModuleType('indexers')
        indexers.local_api = local_api
        scope = {'ku': ku, 'ls': lambda n: {32602: 'Add To', 32603: 'Remove From', 32453: 'מועדפים'}[n],
                 '__import__': __import__}
        xbmcgui = types.SimpleNamespace(Window=lambda n: types.SimpleNamespace(setProperty=lambda *a: None))
        xbmc = types.SimpleNamespace(getInfoLabel=lambda name: '')
        with patch.dict(sys.modules, {'indexers': indexers, 'indexers.local_api': local_api,
                                      'xbmcgui': xbmcgui, 'xbmc': xbmc}):
            exec(compile(text, 'dialogs.py', 'exec'), scope)
            scope['favorites_choice']({'mediatype': 'movie', 'tmdb_id': '7', 'title': 'Guarding Stars'})
        return asked[0]

    def test_patched_once(self):
        first, second, text = self.patched()
        self.assertEqual((first['applied'], first['anchor_missing']), (3, 0))
        self.assertEqual((second['applied'], second['skipped_current']), (0, 3))
        for e in ENTRIES:
            self.assertEqual(text.count(e['marker']), 1)

    def test_the_question_in_hebrew(self):
        _f, _s, text = self.patched()
        self.assertEqual(self.ask(text, False), 'Guarding Stars[CR][CR]להוסיף למועדפים של POV?')
        self.assertEqual(self.ask(text, True), 'Guarding Stars[CR][CR]להסיר מהמועדפים של POV?')

    def test_ok_and_cancel_in_hebrew(self):
        self.assertEqual(LABELS['hebrew_label'](32839), 'אישור')
        self.assertEqual(LABELS['hebrew_label'](32840), 'ביטול')
        self.assertEqual(LABELS['hebrew_label']('32453'), 'מועדפים')      # as before


if __name__ == '__main__':
    unittest.main()
