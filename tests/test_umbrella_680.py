"""Umbrella 6.8.00 (bot issue #432) and MoranSubs 0.3.73.

6.8.00 backs out of the source list quietly itself: its sourceSelect resolves
offscreen whatever enable_playnext says, and the `else: control.cancelPlayback()`
our quiet cancel replaced is gone. The prewarm still goes in; the missing cancel
branch is no longer a warning on every start. 6.8.00 also adds three strings a
viewer sees (the kind beside a combined search result, the Download Manager).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'
TRANSLATE_SRC = (ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import umbrella_hebrew_ui_patcher, umbrella_source_ux_patcher
        finally:
            sys.path.remove(str(ADDON))
    return umbrella_source_ux_patcher, umbrella_hebrew_ui_patcher


ux, he = _load()

HEAD = ('class Sources:\n'
        '\tdef getSources_dialog(self, title, year, imdb, tvdb, season, episode, tvshowtitle, premiered, timeout=90):\n'
        '\t\ttry:\n'
        '\t\t\tpass\n'
        '\t\texcept:\n'
        '\t\t\tpass\n\n'
        '\tdef sourceSelect(self, action):\n'
        '\t\ttry:\n'
        '\t\t\tif action == "play_Item":\n'
        '\t\t\t\treturn 1\n')
# 6.7.99's shape: the offscreen resolve is there too, but only for playnext
OLD_TAIL = ('\t\t\telif self.enable_playnext:\n'
            '\t\t\t\tcontrol.playlist.clear()\n'
            '\t\t\t\ttry: control.player.stop()\n'
            '\t\t\t\texcept: pass\n'
            '\t\t\t\tfrom sys import argv\n'
            '\t\t\t\tcontrol.resolve(int(argv[1]), True, control.item(offscreen=True))\n'
            '\t\t\t\tcontrol.closeOk()\n'
            '\t\t\telse:\n'
            '\t\t\t\tcontrol.cancelPlayback()\n'
            '\t\texcept:\n'
            '\t\t\tcontrol.cancelPlayback()\n')
NEW_TAIL = ('\t\t\telse:\n'
            '\t\t\t\tcontrol.playlist.clear()\n'
            '\t\t\t\tif self.enable_playnext:\n'
            '\t\t\t\t\ttry: control.player.stop()\n'
            '\t\t\t\t\texcept: pass\n'
            '\t\t\t\tfrom sys import argv\n'
            '\t\t\t\tcontrol.resolve(int(argv[1]), True, control.item(offscreen=True))\n'
            '\t\t\t\tcontrol.closeOk()\n'
            '\t\texcept:\n'
            '\t\t\tcontrol.cancelPlayback()\n')


class QuietCancel(unittest.TestCase):

    def run_on(self, text):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'sources.py')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        logs = []
        ku = mock.MagicMock()
        ku.log = lambda msg, level='INFO': logs.append((level, msg))
        with mock.patch.object(ux, '_sources_path', lambda: path), mock.patch.object(ux, 'kodi_utils', ku):
            status = ux.ensure_patched()
            again = ux.ensure_patched()
        with open(path, encoding='utf-8', newline='') as f:
            out = f.read()
        return status, again, out, logs

    def test_umbrella_680_gets_the_prewarm_and_no_warning(self):
        status, again, out, logs = self.run_on(HEAD + NEW_TAIL)
        self.assertEqual(status, 'patched')
        self.assertEqual(again, 'unchanged')
        self.assertIn(ux.PREWARM_MARKER, out)
        self.assertNotIn(ux.CANCEL_MARKER, out)
        self.assertFalse([m for lv, m in logs if lv == 'WARNING'], logs)
        self.assertTrue(any('backs out quietly itself' in m for lv, m in logs if lv == 'INFO'), logs)
        self.assertTrue(any('prewarm injected' in m for _, m in logs), logs)

    def test_older_umbrella_still_gets_the_quiet_cancel(self):
        status, again, out, logs = self.run_on(HEAD + OLD_TAIL)
        self.assertEqual(status, 'patched')
        self.assertEqual(again, 'unchanged')
        self.assertIn(ux.CANCEL_MARKER, out)
        self.assertTrue(any('prewarm + quiet cancel injected' in m for _, m in logs), logs)

    def test_a_branch_neither_way_still_warns(self):
        status, _, out, logs = self.run_on(HEAD + '\t\texcept:\n\t\t\tcontrol.cancelPlayback()\n')
        self.assertEqual(status, 'patched')
        self.assertTrue(any('cancel branch not found' in m for lv, m in logs if lv == 'WARNING'), logs)

    def test_an_older_umbrella_with_a_reshaped_cancel_warns(self):
        # the offscreen resolve of the playnext branch is not 6.8.00's shape
        for tail in (OLD_TAIL.replace('\t\t\telse:\n\t\t\t\tcontrol.cancelPlayback()\n',
                                      '\t\t\telse: control.cancelPlayback()\n'),
                     OLD_TAIL.replace('\t\t\t\tcontrol.cancelPlayback()\n\t\texcept',
                                      '\t\t\t\tlog_utils.log("x")\n\t\t\t\tcontrol.cancelPlayback()\n\t\texcept')):
            self.assertNotEqual(tail, OLD_TAIL)
            status, _, out, logs = self.run_on(HEAD + tail)
            self.assertEqual(status, 'patched')
            self.assertNotIn(ux.CANCEL_MARKER, out)
            self.assertTrue(any('cancel branch not found' in m for lv, m in logs if lv == 'WARNING'), logs)


class Hebrew(unittest.TestCase):

    def test_the_three_new_strings(self):
        self.assertEqual(he.HE['40865'], 'סרט')
        self.assertEqual(he.HE['40866'], 'סדרה')
        self.assertEqual(he.HE['40867'], 'מנהל הורדות')
        self.assertNotIn('40868', he.HE)     # settings help: English by design


class ReOffer(unittest.TestCase):

    def test_a_stored_proofread_after_a_hebrew_reference_is_not_offered_again(self):
        i = TRANSLATE_SRC.index('        # Proofread here before, its pool upload never went through')
        block = TRANSLATE_SRC[i:i + 700]
        self.assertIn('and not _gp_hebrew_ref(path, info if _gp_ref_tier(path, pooled_hash)', block)


if __name__ == '__main__':
    unittest.main()
