"""RTL formatting must not split Hebrew phrases into separate bidi runs."""
import importlib.util
from pathlib import Path
import re
import unittest

LIB=Path(__file__).resolve().parents[1]/'addons/service.subtitles.kodipovilai/resources/lib/srt.py'
spec=importlib.util.spec_from_file_location('srt_rtl_test',LIB)
srt=importlib.util.module_from_spec(spec);spec.loader.exec_module(srt)
RLE='\u202b';PDF='\u202c'

class StyledRTL(unittest.TestCase):
    def repair(self, value):
        result=srt._wrap_rtl_base_line(value)
        self.assertEqual(srt._wrap_rtl_base_line(result),result)
        visible=lambda x: re.sub('<[^>]+>','',x).replace(RLE,'').replace(PDF,'')
        self.assertEqual(visible(result),visible(value))
        return result

    def test_whole_italic_embeddings_inside_style(self):
        self.assertEqual(self.repair('<i>שלום,</i>'),RLE+'<i>'+RLE+'שלום,'+PDF+'</i>'+PDF)

    def test_music_and_dash_share_the_italic_run(self):
        for value in ('♪ <i>שלום,</i> ♪','- <i>שלום,</i>'):
            out=self.repair(value)
            self.assertTrue(out.startswith(RLE+'<i>'+RLE))
            self.assertTrue(out.endswith(PDF+'</i>'+PDF))

    def test_mixed_phrases_drop_emphasis_preserving_logical_words(self):
        self.assertEqual(self.repair('בוא <i>לכאן</i> עכשיו.'),RLE+'בוא לכאן עכשיו.'+PDF)
        self.assertEqual(self.repair('<i>שלום</i> <b>עולם!</b>'),RLE+'שלום עולם!'+PDF)

    def test_sibling_styles_do_not_become_crossed_tags(self):
        for value, plain in (('<i></i><b>שלום</b>', 'שלום'),
                             ('<i>♪</i><b>שלום</b>', '♪שלום')):
            self.assertEqual(self.repair(value), RLE + plain + PDF)
        self.assertEqual(self.repair('<b><i>שלום,</i></b>'),
                         RLE + '<b><i>' + RLE + 'שלום,' + PDF + '</i></b>' + PDF)

    def test_old_outside_embedding_repaired(self):
        self.assertEqual(self.repair(RLE+'<i>שלום,</i>'+PDF),self.repair('<i>שלום,</i>'))

    def test_nested_and_cross_line_styles_remain_idempotent(self):
        for value in ('<b><i>שלום,</i></b>','<i>שלום,','שלום,</i>'):
            self.repair(value)

    def test_plain_hebrew_and_latin_controls(self):
        self.assertEqual(self.repair('שלום, עולם!'),RLE+'שלום, עולם!'+PDF)
        self.assertEqual(srt._wrap_rtl_base_line('<i>Hello, world!</i>'),'<i>Hello, world!</i>')

if __name__=='__main__':unittest.main()
