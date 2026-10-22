"""Umbrella 6.7.95 moved its English strings; MoranSubs' Hebrew menus follow.

Field (22 Oct 2026): Umbrella 6.7.95 (pin moved by the release automation)
moved resources/language/English to resource.language.en_gb, and
umbrella_hebrew_ui_patcher skipped: Umbrella's menus were English for every
user on it.
"""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MS_LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'


def load(name, path, modules=None):
    with patch.dict(sys.modules, modules or {}):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))      # no newline translation, as the code writes


class MoranSubsUmbrellaLanguages(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name) / 'plugin.video.umbrella'
        self.base.mkdir()
        vfs = types.SimpleNamespace(translatePath=lambda p: str(self.base) + '/')
        self.mods = {'xbmcvfs': vfs}

    def po(self, rel, entries):
        write(self.base / rel, ''.join('msgctxt "#%s"\nmsgid "%s"\nmsgstr ""\n\n' % kv for kv in entries))

    def test_hebrew_menus_read_the_new_en_gb_folder(self):
        ui = load('ms_umb_he', MS_LIB / 'umbrella_hebrew_ui_patcher.py', self.mods)
        some = sorted(ui.HE, key=int)[:3]
        self.po('resources/language/resource.language.en_gb/strings.po', [(k, 'English %s' % k) for k in some])
        self.assertEqual(ui.ensure_patched(), 'patched')
        hebrew = (self.base / 'resources/language/resource.language.he_il/strings.po').read_text('utf-8')
        for key in some:
            self.assertIn('msgctxt "#%s"\nmsgid "English %s"' % (key, key), hebrew)
        self.assertEqual(ui.ensure_patched(), 'unchanged')

    def test_legacy_folder_still_wins_when_present(self):
        ui = load('ms_umb_he_legacy', MS_LIB / 'umbrella_hebrew_ui_patcher.py', self.mods)
        key = sorted(ui.HE, key=int)[0]
        self.po('resources/language/English/strings.po', [(key, 'Legacy')])
        self.po('resources/language/resource.language.en_gb/strings.po', [(key, 'Modern')])
        ui.ensure_patched()
        hebrew = (self.base / 'resources/language/resource.language.he_il/strings.po').read_text('utf-8')
        self.assertIn('msgid "Legacy"', hebrew)

    def test_mirror_reports_upstream_once_the_addon_ships_en_gb(self):
        mirror = load('ms_mirror', MS_LIB / 'legacy_lang_mirror.py', self.mods)
        self.assertEqual(mirror.mirror('plugin.video.umbrella'), 'no_source')     # broken install
        self.po('resources/language/resource.language.en_gb/strings.po', [('30000', 'x')])
        self.assertEqual(mirror.mirror('plugin.video.umbrella'), 'upstream')
        write(self.base / 'resources/language/resource.language.en_gb/strings.po', mirror.MARKER + 'old copy')
        self.assertEqual(mirror.mirror('plugin.video.umbrella'), 'no_source')     # ours, source gone



if __name__ == '__main__':
    unittest.main()
