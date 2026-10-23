"""MoranSubs 0.3.51: gaps found by checking another add-on's NG adoptions
(their PR #134, 23 Oct 2026) against our own pipeline.

- A reply Gemini stopped early (RECITATION on song lyrics, SPII, LANGUAGE,
  OTHER...) is treated as a block, so the ladder isolates the line; it used to
  ship cut off, or end the whole job as a generic error when it was empty.
  SubSync's audio path keeps the partial text it always used.
- The 85% yield check counts entries that answer a requested start time, not
  paragraphs: a reply that lost every timecode is split and re-asked instead of
  leaving the whole chunk in the source language.
- An overload, a request/network error or an unexpected chunk exception keeps
  the finished AI chunks and fills the rest with Google
  (test_ng_architecture_review.GoogleFillTests).
- A release name that says machine / AI translation marks the candidate MT, so
  it is never a gender reference nor offered as human Hebrew.
- The TMDB cast is cached per episode (guest stars), an episode's own IMDb id
  resolves to its show, and a TMDB id is used when there is no IMDb id.
- A third-script letter in the Hebrew is exempt only when its source cue merely
  quotes that script; from a cue written in it (Japanese, Korean, Thai...) it is
  an untranslated leak and goes to the one-call repair.
- The NG Method B classifier is off (measured: 5 changed lines, 2 better,
  2 worse), and a foreign-script repair reply cut off at the output cap is
  asked once more with room to finish instead of leaving every line to the
  Arabic cleanup.
"""
import ast
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load(name):
    spec = importlib.util.spec_from_file_location('ng351_' + name, LIB / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
            log=lambda *a, **k: None)}):
        spec.loader.exec_module(module)
    return module


gemini = _load('gemini')
srt = _load('srt')
TRANSLATE = (LIB / 'translate.py').read_text(encoding='utf-8')
TREE = ast.parse(TRANSLATE)


def _define(names, ns):
    """Run translate.py's own (possibly nested) functions in `ns`."""
    for name in names:
        for node in ast.walk(TREE):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                node.col_offset = 0
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<%s>' % name, 'exec'), ns)
                break
        else:
            raise AssertionError('no function ' + name)
    return ns


def block(n, text):
    return '{0}\n00:00:{0:02d},000 --> 00:00:{0:02d},900\n{1}'.format(n, text)


def _reply(text, finish):
    parts = [{'text': text}] if text is not None else []
    candidate = {'content': {'parts': parts}}
    if finish is not None:
        candidate['finishReason'] = finish
    return {'candidates': [candidate]}


class StoppedEarlyReplies(unittest.TestCase):
    def test_a_normal_reply_is_returned(self):
        for finish in ('STOP', None, 'FINISH_REASON_UNSPECIFIED'):
            self.assertEqual(gemini._generated_text(_reply('שלום', finish)), 'שלום')

    def test_an_early_stop_with_text_is_a_block_that_keeps_the_text(self):
        for finish in ('RECITATION', 'SPII', 'LANGUAGE', 'OTHER'):
            with self.assertRaises(gemini.FilteredResponse) as caught:
                gemini._generated_text(_reply('1\n00:00:01,000 --> 00:00:02,000\nשורה', finish))
            self.assertIsInstance(caught.exception, gemini.StoppedEarly)
            self.assertIn('שורה', caught.exception.partial_text)

    def test_an_empty_early_stop_is_a_block_not_a_job_ending_error(self):
        for finish in ('RECITATION', 'SPII', 'LANGUAGE', 'OTHER', None):
            with self.assertRaises(gemini.FilteredResponse):
                gemini._generated_text(_reply('', finish))

    def test_an_unknown_new_finish_reason_is_not_a_block(self):
        # A harmless reason Google may add must not send every chunk down the
        # block ladder: only the named early stops are blocks.
        self.assertEqual(gemini._generated_text(_reply('שלום', 'SOMETHING_NEW')), 'שלום')

    def test_an_early_stop_isolates_the_line_without_other_references(self):
        stop = TRANSLATE.index('            except gemini.StoppedEarly:')
        self.assertLess(stop, TRANSLATE.index('            except gemini.FilteredResponse:', stop))
        self.assertIn("_translate_one(idx, ch[:mid], deadline, False)", TRANSLATE[stop:stop + 900])
        self.assertIn('(0 if isinstance(_blocked, gemini.StoppedEarly)', TRANSLATE)

    def test_an_empty_reply_at_the_token_cap_is_truncated(self):
        with self.assertRaises(gemini.TruncatedResponse):
            gemini._generated_text(_reply('', 'MAX_TOKENS'))

    def test_an_empty_stop_is_still_a_generic_error(self):
        with self.assertRaises(gemini.GeminiError) as caught:
            gemini._generated_text(_reply('', 'STOP'))
        self.assertNotIsInstance(caught.exception, gemini.FilteredResponse)

    def test_safety_blocks_are_unchanged(self):
        for finish in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST'):
            with self.assertRaises(gemini.FilteredResponse) as caught:
                gemini._generated_text(_reply('partial', finish))
            self.assertNotIsInstance(caught.exception, gemini.StoppedEarly)

    def test_the_audio_path_keeps_a_cut_off_speech_list(self):
        source = (LIB / 'gemini.py').read_text(encoding='utf-8')
        start = source.index('def generate_media(')
        body = source[start:source.index('\ndef ', start + 10)]
        self.assertIn('except StoppedEarly as e:', body)
        self.assertIn('return e.partial_text', body)


class YieldCountsAnsweredEntries(unittest.TestCase):
    def setUp(self):
        self.ns = _define(['_answered'], {'srt': srt})
        self.ch = [block(n, 'Line %d' % n) for n in range(1, 7)]

    def test_a_full_reply_answers_every_entry(self):
        reply = '\n\n'.join(block(n, 'שורה %d' % n) for n in range(1, 7))
        self.assertEqual(self.ns['_answered'](self.ch, reply), 6)

    def test_a_reply_without_timecodes_answers_none(self):
        reply = '\n\n'.join('שורה %d' % n for n in range(1, 7))
        self.assertEqual(len(srt.parse_blocks(reply)), 6)    # the old count
        self.assertEqual(self.ns['_answered'](self.ch, reply), 0)

    def test_an_invented_start_answers_nothing(self):
        reply = '\n\n'.join([block(n, 'שורה %d' % n) for n in range(1, 6)]
                            + ['6\n00:09:59,000 --> 00:10:00,000\nשורה 6'])
        self.assertEqual(self.ns['_answered'](self.ch, reply), 5)

    def test_both_yield_gates_use_it(self):
        self.assertIn('got = _answered(ch, response)', TRANSLATE)
        self.assertIn('if _answered(ch, _resp) < max(1, int(len(ch) * 0.85)):', TRANSLATE)
        self.assertNotIn('len(srt.parse_blocks(_resp)) < max(1', TRANSLATE)


class MachineTranslatedNames(unittest.TestCase):
    def setUp(self):
        source = (LIB / 'subs_engine_bridge.py').read_text(encoding='utf-8')
        start, end = source.index("_SEP = r'"), source.index('_PROVIDER_LABEL = {')
        self.ns = {'re': __import__('re')}
        exec(source[start:end], self.ns)
        self.source = source

    def test_mt_names_are_caught(self):
        for name in ('Movie.2024.1080p.WEB-DL.HebrewMachineTranslated', 'Show.S01E02.Machine.Translated.Heb',
                     'Film.2023.AI.Translated.srt', 'Film 2023 - Google Translate', 'Film.2023.GoogleTranslated',
                     'Film.2023.DeepL', 'Film.2023 (translated by ChatGPT)', 'Film.2023.auto-translated',
                     'Film.2023.MT.Hebrew', 'סרט 2023 תרגום מכונה', 'סרט - תורגם ע"י גוגל', 'תורגם אוטומטית',
                     'תרגום AI', 'תורגם בבינה מלאכותית', 'Film [AI Subs]'):
            self.assertTrue(self.ns['_looks_machine_translated'](name), name)

    def test_titles_and_human_credits_are_not(self):
        for name in ('A.I.Artificial.Intelligence.2001.1080p.BluRay', 'AI.2023.Documentary.1080p',
                     'The.Internship.2013.Google', 'Gemini.Man.2019.1080p', 'Ex.Machina.2014.1080p',
                     'Movie.2024.1080p.WEB-DL.Hebrew', 'Wizdom · 87%  —  Movie.2024.WEB-DL',
                     'Translated.By.Moshe', 'תורגם ע"י משה כהן', 'Automata.2014', 'Untranslatable.2020',
                     'A.I. בינה מלאכותית (2001)', 'בינה מלאכותית - סרט תיעודי', 'תרגום - בינה כהן',
                     'תורגם ע"י בינה כהן'):
            self.assertFalse(self.ns['_looks_machine_translated'](name), name)

    def test_the_bridge_flags_the_candidate(self):
        self.assertIn("or _looks_machine_translated(parsed['filename'], label0))", self.source)
        ag = (LIB / 'arabic_gender.py').read_text(encoding='utf-8')
        self.assertIn("if cand.get('_is_mt'):\n        return None", ag)


class CastPerEpisode(unittest.TestCase):
    def setUp(self):
        self.tmdb = _load('tmdb_helper')
        self.tmdb._get_tmdb_key = lambda: 'k'
        self.urls = []

    def test_an_episode_imdb_id_resolves_to_its_show(self):
        def get(url, params, timeout=15):
            self.urls.append(url)
            if '/find/' in url:
                return {'tv_episode_results': [{'show_id': 1416, 'season_number': 5,
                                                'episode_number': 3}]}
            return {'cast': [{'id': 1, 'name': 'A', 'character': 'Meredith', 'gender': 1}]}
        self.tmdb._get = get
        cast = self.tmdb.fetch_cast(imdb_id='tt1234567', media_type='tv')
        self.assertEqual([c['character'] for c in cast], ['Meredith'])
        self.assertTrue(self.urls[-1].endswith('/tv/1416/season/5/episode/3/credits'))

    def test_a_tmdb_id_alone_is_enough(self):
        def get(url, params, timeout=15):
            self.urls.append(url)
            return {'cast': [{'id': 1, 'name': 'A', 'character': 'Rory', 'gender': 1}]}
        self.tmdb._get = get
        cast = self.tmdb.fetch_cast(tmdb_id='4586', media_type='tv', season='2', episode='7')
        self.assertEqual([c['character'] for c in cast], ['Rory'])
        self.assertEqual(self.urls, [self.tmdb.API_BASE + '/tv/4586/season/2/episode/7/credits'])

    def test_the_cache_key_is_per_episode(self):
        self.assertIn("meta_key = '{0}_S{1}E{2}'.format(meta_key, season, episode)", TRANSLATE)
        self.assertIn('imdb_id=imdb_id or None, tmdb_id=_cast_tmdb or None,', TRANSLATE)
        self.assertNotIn('cache.metadata_path(imdb_id)', TRANSLATE)

    def test_a_library_episode_tmdb_id_is_not_taken_for_its_show(self):
        self.assertIn("str(info.get('dbid') or '').strip() not in ('', '-1', '0')", TRANSLATE)
        ku = (LIB / 'kodi_utils.py').read_text(encoding='utf-8')
        self.assertIn("info['dbid']     = gi('VideoPlayer.DBID')", ku)


class SourceScriptLeaks(unittest.TestCase):
    def setUp(self):
        self.sr = _load('script_residual')

    def test_a_leak_from_a_cue_written_in_that_script_is_selected(self):
        src = [block(1, '私は大丈夫'), block(2, '괜찮아요'), block(3, 'ฉันสบายดี'), block(4, 'Я в порядке')]
        out = [block(1, 'אני 大丈夫'), block(2, '괜찮아요 אני'), block(3, 'ฉัน בסדר'), block(4, 'אני в порядке')]
        self.assertEqual([i for i, _, _ in self.sr.candidates(src, out)], [0, 1, 2, 3])

    def test_a_quoted_word_stays_exempt(self):
        src = [block(1, 'Moscow, Москва.'), block(2, 'The sign says 出口, the exit.')]
        out = [block(1, '.מוסקבה, Москва'), block(2, 'השלט אומר 出口, היציאה.')]
        self.assertEqual(self.sr.candidates(src, out), [])


class MeasuredInKodi(unittest.TestCase):
    def test_the_classifier_is_off(self):
        for node in TREE.body:
            if (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == '_GENDER_CLASSIFIER'):
                self.assertIs(ast.literal_eval(node.value), False)
                break
        else:
            self.fail('no _GENDER_CLASSIFIER')

    def test_a_cut_off_foreign_script_repair_is_asked_again_with_room(self):
        start = TRANSLATE.index("and 'Truncated' in (_script_counts['error'] or '')):")
        block = TRANSLATE[start:start + 700]
        self.assertIn('_residual_request(text, output_cap=12288)', block)
        self.assertIn('def _residual_request(prompt_text, temperature=0.0, output_cap=4096):', TRANSLATE)
        self.assertIn('max_output_tokens=min(max_output_tokens, output_cap)', TRANSLATE)


if __name__ == '__main__':
    unittest.main()
