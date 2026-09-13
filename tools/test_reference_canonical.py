"""Reference analysis uses canonical text; player rendering remains separate."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ADDON = Path(__file__).resolve().parents[1] / 'addons/service.subtitles.kodipovilai'
sys.path.insert(0, str(ADDON))
from resources.lib import arabic_gender, subs_engine_bridge, translate

class ReferenceDownload(unittest.TestCase):
    def test_reference_reads_original_while_delivery_still_renders(self):
        with tempfile.TemporaryDirectory() as td:
            canonical = Path(td) / 'source.srt'
            text = '1\n00:00:01,000 --> 00:00:02,000\n- את מוכנה?\n'
            canonical.write_text(text, encoding='utf-8')
            rendered = subs_engine_bridge._render_hebrew_rtl_copy(str(canonical))
            self.assertNotEqual(Path(rendered).read_text(encoding='utf-8'), text)
            calls = []
            def download(payload, for_delivery=True):
                calls.append(for_delivery)
                return rendered if for_delivery else str(canonical)
            link = translate._encode_link(dict(source='fixture', language='Hebrew'))
            with patch.object(subs_engine_bridge, 'download', side_effect=download):
                self.assertEqual(arabic_gender._download_candidate({'link': link}), text)
            self.assertEqual(calls, [False])
            self.assertEqual(canonical.read_text(encoding='utf-8'), text)
            self.assertTrue(Path(rendered).is_file())

    def test_missing_reference_keeps_existing_fallback(self):
        link = translate._encode_link(dict(source='fixture'))
        with patch.object(subs_engine_bridge, 'download', return_value=None):
            self.assertIsNone(arabic_gender._download_candidate({'link': link}))

    def test_invalid_link_never_downloads(self):
        with patch.object(subs_engine_bridge, 'download') as download:
            self.assertIsNone(arabic_gender._download_candidate({'link': 'invalid'}))
            download.assert_not_called()

if __name__ == '__main__':
    unittest.main()
