"""FENtastic's simple player: one change-source button, never two (the skin carries its own since the build's
FENtastic; the patcher's copy had the same id and the remote's right key stood still on the pair -- QA Kodi)."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'qa_simpleplayer_source', ROOT / 'service.subtitles.kodipovilai/resources/lib/fentastic_simpleplayer_source_patcher.py')
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

SKIN = (ROOT / 'skin.fentastic/xml/Includes_VideoOsd3.xml').read_text(encoding='utf-8')


class SimplePlayerSourceTests(unittest.TestCase):
    def run_on(self, content):
        files = {'f': content}
        with patch.object(patcher, 'xbmcvfs', object()), \
                patch.object(patcher, '_exists', return_value=True), \
                patch.object(patcher, '_read', side_effect=lambda path: files['f']), \
                patch.object(patcher, '_write', side_effect=lambda path, text: files.__setitem__('f', text)):
            status = patcher.ensure_patched()
        return status, files['f']

    def test_the_skin_has_its_own_button_and_nothing_is_added(self):
        self.assertEqual(SKIN.count('id="700460"'), 1)
        status, after = self.run_on(SKIN)
        self.assertEqual(status, 'native')
        self.assertEqual(after, SKIN)

    def test_a_copy_added_before_is_taken_out_again(self):
        line = '\t\t\t\t\t' + patcher.BUTTON + '\n'
        at = SKIN.index(patcher.ANCHOR)
        start = SKIN.rfind('\n', 0, at) + 1
        installed = SKIN[:start] + line + SKIN[start:]
        self.assertEqual(installed.count('id="700460"'), 2)
        status, after = self.run_on(installed)
        self.assertEqual(status, 'removed_duplicate')
        self.assertEqual(after, SKIN, 'exactly the skin as it ships')
        self.assertEqual(self.run_on(after)[0], 'native')

    def test_an_older_skin_without_the_button_still_gets_one(self):
        start = SKIN.index('<control type="radiobutton" id="700460">')
        end = SKIN.index('</control>', start) + len('</control>')
        older = SKIN[:start] + SKIN[end:]
        status, after = self.run_on(older)
        self.assertEqual(status, 'patched')
        self.assertEqual(after.count('id="700460"'), 1)
        self.assertIn(patcher.MARKER, after)
        self.assertEqual(self.run_on(after)[0], 'already_patched')


if __name__ == '__main__':
    unittest.main()
