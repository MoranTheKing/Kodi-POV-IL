"""The shortcut-folder fanart hook must land in the folder CONTENTS builder.

POV 6.10 repeats one setArt line in three builders.  The old one-line anchor
matched the first of them, shortcut_folders(), where the hook's ``item_get``
is undefined; POV's bare ``except: pass`` then dropped every shortcut folder.
"""

import ast
import importlib.util
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
T = '\t'
SET_ART = (T * 5 + "listitem.setArt({'icon': icon, 'poster': icon, "
           "'thumb': icon, 'fanart': fanart, 'banner': icon})")

# Timing-free shape of POV 6.10's navigator: the same setArt line in the
# shortcut-folder LIST, the folder CONTENTS and the main-menu builders.
NAVIGATOR = '\n'.join([
    'class Navigator:',
    T + 'def shortcut_folders(self):',
    T * 2 + 'def _builder():',
    T * 3 + 'for i in folders:',
    T * 4 + 'try:',
    T * 5 + "name, icon = i[0], 'folder.png'",
    SET_ART,
    T * 5 + 'yield (url, listitem, True)',
    T * 4 + 'except: pass',
    T + 'def build_shortcut_folder_list(self):',
    T * 2 + 'def _process():',
    T * 3 + 'for item_position, item in enumerate(contents):',
    T * 4 + 'try:',
    T * 5 + 'item_get = item.get',
    T * 5 + "icon = '%s%s' % (icon_path, item_get('iconImage'))",
    SET_ART,
    T * 5 + 'yield (url, listitem, isFolder)',
    T * 4 + 'except: pass',
    T + 'def main(self):',
    T * 2 + 'def build_main_lists():',
    T * 3 + 'for item_position, item in enumerate(contents):',
    T * 4 + 'try:',
    T * 5 + 'item_get = item.get',
    SET_ART,
    T * 5 + 'yield (build_url(item), listitem, isFolder)',
    T * 4 + 'except: pass',
    '',
])


def _engine():
    xbmc = types.ModuleType('xbmc')
    for index, name in enumerate(('LOGDEBUG', 'LOGINFO', 'LOGWARNING', 'LOGERROR')):
        setattr(xbmc, name, index)
    modules = {
        'xbmc': xbmc,
        'xbmcaddon': types.SimpleNamespace(
            Addon=lambda: types.SimpleNamespace(getSetting=lambda key: '')),
        'xbmcvfs': types.SimpleNamespace(translatePath=lambda path: path),
        'resources.libs.common': types.SimpleNamespace(
            logging=types.SimpleNamespace(log=lambda *a, **k: None)),
    }
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            'fanart_engine', WIZARD / 'resources/libs/patch_engine.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    engine = module.PatchEngine.__new__(module.PatchEngine)
    engine._stats = {}
    return engine


def _section(text, start, end):
    return text[text.find(start):text.find(end)]


class ShortcutFanartPatchTests(unittest.TestCase):
    def setUp(self):
        config = runpy.run_path(
            str(WIZARD / 'resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
        self.entry = dict(next(p for p in config
                               if p['id'] == 'pov_shortcut_fanart_shadow'),
                          enabled=True)
        self.engine = _engine()

    def apply(self, content, entry):
        return self.engine._apply_single_patch(content, entry, '\n')

    def test_hook_lands_only_in_the_folder_contents_builder(self):
        patched, changed, status = self.apply(NAVIGATOR, self.entry)
        self.assertTrue(changed)
        self.assertEqual(status, 'applied')
        ast.parse(patched)
        for start, end in (('def shortcut_folders(', 'def build_shortcut_folder_list('),
                           ('def main(', '\x00')):
            self.assertEqual(_section(patched, start, end),
                             _section(NAVIGATOR, start, end))
        contents = _section(patched, 'def build_shortcut_folder_list(', 'def main(')
        self.assertIn(self.entry['marker'], contents)
        # The hook must only use names defined wherever it can land.
        block = contents[contents.find(self.entry['marker']):]
        self.assertNotIn('item_get(', block.split('yield')[0])

    def test_broken_v3_block_is_moved_out_of_shortcut_folders(self):
        old = dict(self.entry, marker='# WIZARD_POV_FANART_SHADOW_v3',
                   anchor=SET_ART,
                   hook=(T * 5 + '# WIZARD: Sequential property override\n'
                         + T * 5 + "if 'genres/' in str(item_get('iconImage') or ''):\n"
                         + T * 6 + "listitem.setArt({'fanart': icon})\n"))
        broken, _changed, _status = self.apply(NAVIGATOR, old)
        self.assertIn('FANART_SHADOW_v3', _section(
            broken, 'def shortcut_folders(', 'def build_shortcut_folder_list('))
        repaired, changed, status = self.apply(broken, self.entry)
        self.assertEqual(status, 'upgraded')
        self.assertNotIn('FANART_SHADOW_v3', repaired)
        self.assertEqual(repaired, self.apply(NAVIGATOR, self.entry)[0])
        self.assertEqual(self.apply(repaired, self.entry)[2], 'skipped_current')


    def test_older_block_inside_the_anchor_still_upgrades(self):
        # A previous version sitting BETWEEN the anchor's two lines must not
        # hide the anchor: the engine judges the host without its old block.
        current, _changed, _status = self.apply(NAVIGATOR, self.entry)
        stale = current.replace(self.entry['marker'], '# WIZARD_POV_FANART_SHADOW_v3')
        upgraded, changed, status = self.apply(stale, self.entry)
        self.assertEqual(status, 'upgraded')
        self.assertTrue(changed)
        self.assertEqual(upgraded, current)


if __name__ == '__main__':
    unittest.main()
