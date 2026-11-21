"""MoranSubs 0.3.108: in the "Google Translate" mode the automatic subtitle needs no Gemini key.

A viewer on "Google Translate" with no key, Nov 2026: "it tries to extract [the video's own subtitle] and fails --
fine -- but it stops there; there are other subtitles, OpenSubtitles, and it does not go on. I had to open the list
and pick one that is not the embedded one, and it translated." The embedded translation is listed among the Hebrew
rows and was tried; the translation of the provider's English subtitle waited for a Gemini key that Google
Translate never needs.
"""
import unittest

from test_autosub_ai_when_no_hebrew import EMB, ENG, HUMAN, run_autosub


class GoogleNeedsNoKey(unittest.TestCase):

    def test_after_a_failed_extraction_the_providers_subtitle_is_translated(self):
        r = run_autosub('auto', key='', translation='google', rows=[EMB, ENG], fail={'emb-1'})
        self.assertEqual(r['resolved'], ['emb-1', 'ai-1'])
        self.assertEqual(r['applied'], ['ai-1.he.srt'])

    def test_with_no_embedded_track_too(self):
        r = run_autosub('auto', key='', translation='google', rows=[ENG])
        self.assertEqual((r['resolved'], r['applied']), (['ai-1'], ['ai-1.he.srt']))

    def test_ask_asks_once_and_a_yes_translates(self):
        r = run_autosub('ask', answer=True, key='', translation='google', rows=[ENG])
        self.assertEqual(len(r['asked']), 1)
        self.assertEqual(r['resolved'], ['ai-1'])

    def test_a_real_hebrew_subtitle_still_goes_first(self):
        r = run_autosub('auto', key='', translation='google', rows=[HUMAN, EMB, ENG])
        self.assertEqual(r['resolved'], ['he-1'])

    def test_the_ai_mode_without_a_key_is_unchanged(self):
        # no key, AI chosen: nothing to translate with -- the provider's subtitle is not tried, as before
        r = run_autosub('auto', key='', translation='ai', rows=[EMB, ENG], fail={'emb-1'})
        self.assertEqual(r['resolved'], ['emb-1'])
        self.assertEqual(r['applied'], [])

    def test_the_overlay_names_google_not_ai(self):
        r = run_autosub('auto', key='', translation='google', rows=[ENG])
        self.assertTrue(any('מתרגם ב-Google Translate' in o for o in r['overlays']), r['overlays'])
        self.assertFalse(any('AI' in o for o in r['overlays']), r['overlays'])
        r = run_autosub('manual', key='', translation='google', rows=[EMB, ENG])
        self.assertTrue(any('תרגום Google זמין ברשימת הכתוביות' in o for o in r['overlays']), r['overlays'])

    def test_no_translation_chosen_translates_nothing(self):
        r = run_autosub('auto', key='', translation='none', rows=[ENG])
        self.assertEqual(r['resolved'], [])


if __name__ == '__main__':
    unittest.main()
