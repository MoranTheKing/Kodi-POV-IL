"""A dialogue dash written without its space stays on the right (srt.py).

Field report (update 756), a phone on the 'reverse' punctuation mode: the
model writes "-להתראות." the way the English source had it, and the reverse
fix took the bare dash for part of the sentence -- it moved only the period,
".-להתראות", which shows the dash on the left beside the period. Verified in
the QA Kodi: that text renders exactly like the screenshot, and the shapes
below render with the dash on the right.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
spec = importlib.util.spec_from_file_location('srt_dash', LIB / 'srt.py')
srt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srt)

RLE, PDF = '‫', '‬'
BYE = 'להתראות'


def render(text, mode):
    out = srt.fix_rtl_punctuation('1\n00:00:01,000 --> 00:00:02,000\n' + text + '\n',
                                  mode=mode)
    return out.split('\n')[2:-1]


class ReverseMode(unittest.TestCase):

    def test_bare_dash_goes_to_the_end(self):
        self.assertEqual(render('-%s.\n-%s.' % (BYE, BYE), 'reverse'),
                         ['.%s -' % BYE, '.%s -' % BYE])
        self.assertEqual(render('-<i>%s?</i>' % BYE, 'reverse'), ['<i>?%s</i> -' % BYE])

    def test_the_old_shape_is_repaired_and_the_fix_is_stable(self):
        self.assertEqual(render('.-%s' % BYE, 'reverse'), ['.%s -' % BYE])
        once = render('-%s.' % BYE, 'reverse')
        self.assertEqual(render('\n'.join(once), 'reverse'), once)

    def test_a_dash_inside_the_opening_tag_or_before_a_quote(self):
        # review of 0.3.57: these still came out ".-X" on a fresh translation
        for text, out in (('<i>-%s.</i>' % BYE, '<i>.%s</i> -' % BYE),
                          ('-"%s".' % BYE, '."%s" -' % BYE),
                          # a mark after a leading ellipsis is dropped, as before
                          ('-...%s.' % BYE, '...%s -' % BYE)):
            once = render(text, 'reverse')
            self.assertEqual(once, [out], text)
            self.assertEqual(render(once[0], 'reverse'), once, text)
        # and the shapes the old fix left in caches
        self.assertEqual(render('.-<i>%s</i>' % BYE, 'reverse'), ['<i>.%s</i> -' % BYE])
        self.assertEqual(render('.-"%s"' % BYE, 'reverse'), ['."%s" -' % BYE])

    def test_a_spaced_dash_and_a_minus_sign_are_as_before(self):
        self.assertEqual(render('- %s.' % BYE, 'reverse'), ['.%s -' % BYE])
        self.assertFalse(render('-5 מעלות.', 'reverse')[0].endswith(' -'))


class RtlBaseMode(unittest.TestCase):

    def test_logical_text_is_wrapped_as_it_is(self):
        self.assertEqual(render('-%s.' % BYE, 'rtl_base'), [RLE + '-%s.' % BYE + PDF])

    def test_reverse_cached_text_comes_back_logical(self):
        # the old reverse shape (pooled by a phone on that mode) ...
        self.assertEqual(render('.-%s' % BYE, 'rtl_base'), [RLE + '-%s.' % BYE + PDF])
        # ... and the fixed one
        self.assertEqual(render('.%s -' % BYE, 'rtl_base'), [RLE + '- %s.' % BYE + PDF])
        tagged = render('<i>.-%s</i>' % BYE, 'rtl_base')[0]
        self.assertEqual(tagged.replace(RLE, '').replace(PDF, ''), '<i>-%s.</i>' % BYE)
        # the old shape of "-<i>X.</i>" renders like that line itself
        self.assertEqual(render('.-<i>%s</i>' % BYE, 'rtl_base'),
                         render('-<i>%s.</i>' % BYE, 'rtl_base'))
        self.assertEqual(render('.-"%s"' % BYE, 'rtl_base'), [RLE + '-"%s".' % BYE + PDF])


if __name__ == '__main__':
    unittest.main()
