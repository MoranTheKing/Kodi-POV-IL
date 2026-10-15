"""Nox OSD widths: patch once, never touch a neighbour, repair 0.3.30 damage."""

import importlib.util
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATCHER = (ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
           / 'nox_osd_collision_patcher.py')
NATIVE = ROOT / 'skin.povil.nox' / 'xml' / 'Includes_POVIL_NativePlayer.xml'


def width(text, bid):
    match = re.search(r'<control type="button" id="%s">(?:(?!</control>).)*?'
                      r'<width>(\d+)</width>' % bid, text, re.S)
    return match.group(1) if match else None


def old_pass(text):
    """The 0.3.30 algorithm: a width pattern that may cross controls."""
    for bid, old, new in (('70036', '220', '160'), ('70037', '220', '160'),
                          ('39517', '220', '160'), ('70038', '150', '90'),
                          ('70043', '140', '100')):
        rx = re.compile(r'(<control type="button" id="' + bid +
                        r'">.*?<width>)' + old + r'(</width>)', re.S)
        text = rx.sub(r'\g<1>' + new + r'\g<2>', text, count=1)
    return text.replace('<controls>', '<controls>\n\t\t<!-- AI_SUBS_NOX_OSD_FIX_v1 -->', 1)


class NoxOsdCollisionTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        xml_dir = os.path.join(self.home, 'addons', 'skin.povil.nox', 'xml')
        os.makedirs(xml_dir)
        self.target = os.path.join(xml_dir, 'Includes_POVIL_NativePlayer.xml')
        shutil.copyfile(NATIVE, self.target)
        vfs = types.SimpleNamespace(
            translatePath=lambda p: os.path.join(
                self.home, p.replace('special://home/', '').replace('/', os.sep)))
        with patch.dict(sys.modules, {'xbmcvfs': vfs}):
            spec = importlib.util.spec_from_file_location('nox_patcher', PATCHER)
            self.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mod)
        self.mod.xbmcvfs = vfs
        self.mod.kodi_utils = None

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def read(self):
        with open(self.target, encoding='utf-8', newline='') as handle:
            return handle.read()

    def test_first_boot_patches_and_second_boot_is_a_no_op(self):
        original = self.read()
        self.assertEqual(self.mod.ensure_patched(), 'patched')
        once = self.read()
        self.assertIn(self.mod.MARKER, once)
        for bid, new in (('70036', '160'), ('39517', '160'), ('70038', '90'),
                         ('70043', '100')):
            self.assertEqual(width(once, bid), new)
        for bid in ('70039', '700450'):
            self.assertEqual(width(once, bid), width(original, bid))
        self.assertEqual(self.mod.ensure_patched(), 'ok')
        self.assertEqual(self.read(), once)

    def test_neighbours_shrunk_by_0_3_30_are_restored(self):
        original = self.read()
        damaged = old_pass(old_pass(original))   # boots 1 and 2 of 0.3.30
        self.assertEqual(width(damaged, '70039'), '90')
        self.assertEqual(width(damaged, '700450'), '100')
        with open(self.target, 'w', encoding='utf-8', newline='') as handle:
            handle.write(damaged)
        self.assertEqual(self.mod.ensure_patched(), 'repaired')
        fixed = self.read()
        self.assertEqual(width(fixed, '70039'), width(original, '70039'))
        self.assertEqual(width(fixed, '700450'), width(original, '700450'))
        self.assertIn(self.mod.MARKER, fixed)
        self.assertEqual(self.mod.ensure_patched(), 'ok')

    def test_unrelated_layout_is_left_alone(self):
        with open(self.target, 'w', encoding='utf-8', newline='') as handle:
            handle.write('<includes><include name="x"/></includes>')
        self.assertEqual(self.mod.ensure_patched(), 'unmatched')
        self.assertNotIn(self.mod.MARKER, self.read())


if __name__ == '__main__':
    unittest.main()
