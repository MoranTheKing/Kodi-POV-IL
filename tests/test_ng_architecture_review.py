"""What MoranSubs took from NG's ARCHITECTURE.md and decision records (Oct 2026).

- A gender-repair reply written as JSON is read, not dropped as "answered none".
- No speaker fix on a cue whose reference holds two speakers.
- The 24 000-character repair request takes addressee fixes first and skips an
  entry that does not fit instead of ending the list there.
- A quota or rate-limit abort keeps the chunks Gemini finished; a Google
  fallback in the cache is translated with AI again once AI is available, and
  stays on screen if that AI run fails. Since 0.3.51 an overload, a request /
  network error or an unexpected chunk exception does the same (an invalid key
  still surfaces).
- OpenSubtitles downloads walk distinct keys and tell a quota 406 apart; a
  subtitle archive far too large to be subtitles is not unpacked.
"""
import ast
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
TRANSLATE = (LIB / 'translate.py').read_text(encoding='utf-8')
TREE = ast.parse(TRANSLATE)
OS_PATH = LIB / 'subs_engine' / 'sources' / 'opensubtitles.py'
OS_TREE = ast.parse(OS_PATH.read_text(encoding='utf-8'))


def _load(name):
    spec = importlib.util.spec_from_file_location('ngr_' + name, LIB / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
            log=lambda *a, **k: None)}):
        spec.loader.exec_module(module)
    return module


gg = _load('gender_guard')
srt = _load('srt')
gemini = _load('gemini')
ag = _load('arabic_gender')
gq = _load('gemini_quota')


def _constants(tree, names, ns):
    """translate.py's own module-level literal constants into `ns`."""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in names):
            ns[node.targets[0].id] = ast.literal_eval(node.value)
    missing = [n for n in names if n not in ns]
    if missing:
        raise AssertionError('no constant ' + ', '.join(missing))
    return ns


def _define(tree, names, ns):
    """Run translate.py's own (possibly nested) functions in `ns`."""
    for name in names:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                node.col_offset = 0
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<%s>' % name, 'exec'), ns)
                break
        else:
            raise AssertionError('no function ' + name)
    return ns


def _package(name, **modules):
    """A stand-in for `from . import x` inside functions run by _define."""
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    for key, value in modules.items():
        setattr(pkg, key, value)
    return pkg


def block(n, text, start=None):
    s = n if start is None else start
    return '%d\n00:%02d:%02d,000 --> 00:%02d:%02d,900\n%s' % (n, s // 60, s % 60, s // 60, s % 60, text)


# ---- gender repair ---------------------------------------------------------

def regender(blocks, wanted, src_blocks, ref_map, ref_lang, replies):
    sent, logs = [], []

    def generate(**kw):
        sent.append(kw['prompt'])
        return replies.pop(0) if replies else ''
    ns = dict(srt=srt, gender_guard=gg, arabic_gender=ag,
              gemini=types.SimpleNamespace(REQUEST_TIMEOUT=60),
              kodi_utils=types.SimpleNamespace(log=lambda m, **k: logs.append(m)),
              src_text='\n\n'.join(src_blocks), _ar_map=ref_map, _ref_lang=ref_lang,
              _gemini_rate_gate=lambda x: None, _rpm_interval=0, _repair_generate=generate,
              api_key='k', model='m', max_output_tokens=1024, top_p=1.0,
              thinking_budget=None, thinking_level=None, gemini_timeout=None)
    out = _define(TREE, ['_regender_unguarded'], ns)['_regender_unguarded'](blocks, wanted)
    return out, sent, logs


def evidence_of(prompt):
    return [item['index'] for item in json.loads(prompt[prompt.index('\n\n[') + 2:])]


class JsonRepairReplyTests(unittest.TestCase):
    ENTRY = '13\n00:00:03,000 --> 00:00:04,000\nבואי'

    def test_reply_shapes(self):
        self.assertEqual(gg.reply_entries('12\n00:00:01,000 --> 00:00:02,000\nאת צודקת\n\n' + self.ENTRY),
                         ['12\n00:00:01,000 --> 00:00:02,000\nאת צודקת', self.ENTRY])
        fenced = '```json\n' + json.dumps([{'index': 12, 'corrected_hebrew': 'את צודקת'},
                                           {'index': '13', 'current_hebrew': self.ENTRY}],
                                          ensure_ascii=False) + '\n```'
        self.assertEqual(gg.reply_entries(fenced),
                         ['12\n00:00:00,000 --> 00:00:00,000\nאת צודקת', self.ENTRY])
        self.assertEqual(gg.reply_entries(json.dumps([self.ENTRY], ensure_ascii=False)), [self.ENTRY])
        self.assertEqual(gg.reply_entries(json.dumps({'entries': [{'id': 5, 'text': 'שלום'}]},
                                                     ensure_ascii=False)),
                         ['5\n00:00:00,000 --> 00:00:00,000\nשלום'])

    def test_what_is_not_an_answer(self):
        # an entry filed under another number, prose, a broken fence
        self.assertEqual(gg.reply_entries(json.dumps([{'index': 14, 'current_hebrew': self.ENTRY}],
                                                     ensure_ascii=False)), [])
        self.assertEqual(gg.reply_entries('I kept every line.'), [])
        self.assertEqual(gg.reply_entries('```json\n[{"index": 3, \n```'), [])
        self.assertEqual(gg.reply_entries(''), [])

    def test_a_json_reply_is_applied_after_one_request(self):
        src = [block(1, 'Hi.'), block(2, "You're right."), block(3, 'Bye.')]
        cur = [block(1, 'היי.'), block(2, 'אתה צודק.'), block(3, 'ביי.')]
        reply = '```json\n' + json.dumps([{'index': 2, 'corrected_hebrew': 'את צודקת.'}],
                                         ensure_ascii=False) + '\n```'
        out, sent, logs = regender(cur, {2: [('addressee', 'F')]}, src,
                                   {2: 'את צודקת.'}, 'he', [reply])
        self.assertEqual(len(sent), 1)
        self.assertEqual(out[1], block(2, 'את צודקת.'))   # timecode from the source
        self.assertEqual(out[0], cur[0])
        self.assertTrue(any('reply read as JSON (1 entries)' in m for m in logs), logs)
        self.assertFalse(any('answered none' in m for m in logs), logs)


class TwoSpeakerReferenceTests(unittest.TestCase):
    SRC = [block(1, 'Hello.'), block(2, "I'm sure."), block(3, 'Okay.')]
    CUR = [block(1, 'שלום.'), block(2, 'אני בטוח.'), block(3, 'בסדר.')]

    def test_a_speaker_fix_is_asked(self):
        # Any reference language: NG only measured Hebrew, and dropping the
        # others measured worse here (QA Kodi, no-Hebrew mode: 45 conflicts
        # against 39), so the chain keeps them.
        for lang, ref in (('he', 'אני בטוחה.'), ('ar', 'أنا متأكدة.'), ('es', 'Estoy segura.')):
            out, sent, _ = regender(list(self.CUR), {2: [('speaker', 'F')]}, self.SRC,
                                    {2: ref}, lang, [''])
            self.assertEqual(evidence_of(sent[0]), [2], lang)

    def test_not_when_the_reference_cue_has_two_speakers(self):
        out, sent, logs = regender(list(self.CUR), {2: [('speaker', 'F')]}, self.SRC,
                                   {2: '- אני בטוחה.\n- גם אני.'}, 'he', ['should not be asked'])
        self.assertEqual(sent, [])
        self.assertEqual(out, self.CUR)

    def test_the_addressee_stays_on_such_a_cue(self):
        src = [block(1, 'Hi.'), block(2, "You're right. I'm sure."), block(3, 'Bye.')]
        cur = [block(1, 'היי.'), block(2, 'אתה צודק. אני בטוח.'), block(3, 'ביי.')]
        out, sent, _ = regender(cur, {2: [('addressee', 'F'), ('speaker', 'F')]}, src,
                                {2: '- את צודקת.\n- אני בטוחה.'}, 'he', [''])
        self.assertNotIn('"role": "speaker"', sent[0])
        self.assertIn('"role": "addressee"', sent[0])


class ReferenceProvenanceTests(unittest.TestCase):
    def test_the_log_names_the_provider(self):
        for label, provider in (('[AR] OpenSubtitles · 87%  —  Movie.2006.srt', 'OpenSubtitles'),
                                ('Wizdom · 100%  —  Show.S01E01', 'Wizdom'),
                                ('[תרגום מכונה] Ktuvit · 50%', 'Ktuvit'),
                                ('', '?')):
            self.assertEqual(ag._provider_of({'filename': label}), provider)
        self.assertIn('_provider_of(cand)', (LIB / 'arabic_gender.py').read_text(encoding='utf-8'))


class RepairSizeCapTests(unittest.TestCase):
    def test_addressee_first_and_an_oversized_entry_is_skipped(self):
        big = {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 18, 19, 20, 21, 22}
        src, cur, ref = [], [], {}
        for n in range(1, 41):
            fat = n in big
            src.append(block(n, ('You are right. ' * 126)[:1890] if fat else "You're right."))
            cur.append(block(n, ('אתה צודק. ' * 189)[:1890] if fat else 'אתה צודק.'))
            ref[n] = ('את צודקת. ' * 189)[:1890] if fat else 'את צודקת.'
        # 5 is speaker-only and huge; 10 and 20 are huge addressee fixes, 30 small.
        wanted = {5: [('speaker', 'F')], 10: [('addressee', 'F')],
                  20: [('addressee', 'F')], 30: [('addressee', 'F')]}
        out, sent, logs = regender(cur, wanted, src, ref, 'he', ['', ''])
        self.assertEqual(evidence_of(sent[0]), [10, 30])
        self.assertTrue(any('2 over the size cap' in m for m in logs), logs)


# ---- quota fallback --------------------------------------------------------

class FakeCache(object):
    @staticmethod
    def save_text(path, text):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)


class GoogleFillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'he.srt')
        self.notes, self.whole, self.sent = [], [], []
        self.reply = None

        def translate_srt(text, lang):
            self.sent.append(text)
            return self.reply(text) if callable(self.reply) else self.reply
        sys.modules['ngfill'] = _package('ngfill', google_translate=types.SimpleNamespace(
            translate_srt=translate_srt))
        self.ns = dict(__package__='ngfill', os=os, srt=srt, cache=FakeCache,
                       kodi_utils=types.SimpleNamespace(
                           log=lambda *a, **k: None,
                           notify=lambda m, **k: self.notes.append(m)),
                       _reapply_rtl_fix_in_place=lambda p: None,
                       _google_translate_and_save=lambda *a, **k: self.whole.append(a) or 'whole')
        _constants(TREE, ['_GOOGLE_FALLBACK_WHY'], self.ns)
        _define(TREE, ['_preview_clean', '_google_fill_and_save', '_is_mostly_hebrew'], self.ns)

    def tearDown(self):
        sys.modules.pop('ngfill', None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def chunks(self):
        return [[block(n, 'Line %d' % n) for n in (1, 2)],
                [block(n, 'Line %d' % n) for n in (3, 4)],
                [block(n, 'Line %d' % n) for n in (5, 6)]]

    def fill(self, done, google_chunks=None):
        src = '\n\n'.join(b for ch in self.chunks() for b in ch)
        return self.ns['_google_fill_and_save'](self.chunks(), done, src, 'en', self.path,
                                                {}, reason='quota', google_chunks=google_chunks)

    def saved(self):
        with open(self.path, encoding='utf-8') as f:
            return f.read()

    def test_finished_chunks_are_kept(self):
        self.reply = lambda text: text.replace('Line', 'גוגל שורה')
        done = {1: [block(1, 'שורה ראשונה'),
                    block(2, 'שורה שנייה\n(Rory speaking to Lorelai, female addressee)')],
                3: [block(5, 'שורה חמישית'), block(6, 'שורה שישית')]}
        self.assertEqual(self.fill(done), self.path)
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn('Line 1', self.sent[0])
        self.assertIn('Line 3', self.sent[0])
        self.assertIn('Line 4', self.sent[0])
        text = self.saved()
        for word in ('שורה ראשונה', 'גוגל שורה 3', 'גוגל שורה 4', 'שורה שישית'):
            self.assertIn(word, text)
        self.assertEqual(len(srt.parse_blocks(text)), 6)
        self.assertNotIn('speaking to', text)   # the final pass's note cleanup
        self.assertTrue(os.path.isfile(self.path + '.google'))   # never pooled
        self.assertEqual(self.notes, ['מכסת ה-AI היומית נגמרה — 2 מתוך 3 חלקים תורגמו ב-AI, השאר ב-Google Translate'])
        self.assertEqual(self.whole, [])

    def test_overload_and_errors_keep_finished_chunks_too(self):
        # 0.3.51: an overload that outlasts the backoff, a request/network error
        # that keeps failing, or an unexpected chunk exception used to drop
        # every finished chunk and deliver nothing.
        aborts = _constants(TREE, ['_GOOGLE_FILL_ABORTS'], {})['_GOOGLE_FILL_ABORTS']
        for reason in ('quota', 'ratelimit', 'overload', 'error', 'crash'):
            self.assertIn(reason, aborts)
        for reason in ('cancelled', 'invalid_key'):
            self.assertNotIn(reason, aborts)
        self.reply = lambda text: text.replace('Line', 'גוגל שורה')
        done = {1: [block(1, 'שורה ראשונה'), block(2, 'שורה שנייה')]}
        src = '\n\n'.join(b for ch in self.chunks() for b in ch)
        self.assertEqual(self.ns['_google_fill_and_save'](
            self.chunks(), done, src, 'en', self.path, {}, reason='overload'), self.path)
        self.assertIn('שורה ראשונה', self.saved())
        self.assertTrue(os.path.isfile(self.path + '.google'))
        self.assertEqual(self.notes, ['Gemini עמוס — 1 מתוך 3 חלקים תורגמו ב-AI, השאר ב-Google Translate'])
        abort = TRANSLATE.index('if abort_reason in _GOOGLE_FILL_ABORTS:')
        self.assertIn("gemini_quota.note_exhausted(model)", TRANSLATE[abort:abort + 700])
        self.assertIn("if abort_reason == 'quota':", TRANSLATE[abort:abort + 500])
        # an error the user can fix (retired model, API not enabled) still says why
        self.assertIn("if abort_reason in ('error', 'crash'):\n", TRANSLATE[abort:abort + 200])
        self.assertIn('kodi_utils.notify(abort_msg, time_ms=5000)', TRANSLATE[abort:abort + 400])

    def test_replacing_a_cached_google_file_reuses_its_hebrew(self):
        cached = [[block(n, 'גוגל ישן %d' % n) for n in (1, 2)],
                  [block(n, 'גוגל ישן %d' % n) for n in (3, 4)],
                  [block(n, 'גוגל ישן %d' % n) for n in (5, 6)]]
        done = {1: [block(1, 'שורה ראשונה'), block(2, 'שורה שנייה')]}
        self.assertEqual(self.fill(done, google_chunks=cached), self.path)
        self.assertEqual(self.sent, [])                # no second Google request
        text = self.saved()
        self.assertIn('שורה ראשונה', text)
        self.assertIn('גוגל ישן 6', text)
        self.assertNotIn('גוגל ישן 1', text)

    def test_ai_cleaners_touch_only_the_ai_part(self):
        # An Arabic quote in a Google line is the film's text; in an AI line
        # it is a leak from the gender reference.
        self.reply = lambda text: text.replace('Line 3', 'הוא אמר مرحبا').replace('Line', 'גוגל')
        done = {1: [block(1, 'שלום مرحبا'), block(2, 'שורה שנייה')],
                3: [block(5, 'שורה חמישית'), block(6, 'שורה שישית')]}
        self.assertEqual(self.fill(done), self.path)
        entries = {b.split('\n')[0]: b for b in srt.parse_blocks(self.saved())}
        self.assertIn('مرحبا', entries['3'])
        self.assertNotIn('مرحبا', entries['1'])

    def test_a_failure_inside_goes_whole_file(self):
        self.reply = lambda text: text.replace('Line', 'גוגל')

        def boom(*a):
            raise ValueError('x')
        self.ns['_preview_clean'] = boom
        self.assertEqual(self.fill({1: [block(1, 'א'), block(2, 'ב')]}), 'whole')

    def test_a_reply_that_does_not_line_up_goes_whole_file(self):
        self.reply = lambda text: block(3, 'גוגל')
        self.assertEqual(self.fill({1: [block(1, 'א'), block(2, 'ב')]}), 'whole')
        self.assertFalse(os.path.isfile(self.path))

    def test_nothing_finished_goes_whole_file(self):
        self.reply = lambda text: text
        self.assertEqual(self.fill({}), 'whole')
        self.assertEqual(self.sent, [])

    def test_the_preview_folds_a_stray_latin_letter(self):
        out = self.ns['_preview_clean']([block(1, 'בואi, מתוקה')], block(1, 'Come, sweetie'))
        self.assertIn('בואי', out)


class GoogleCacheUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'he.srt')
        open(self.path, 'w').close()
        open(self.path + '.google', 'w').close()
        self.settings = {'translation_mode': 'ai', 'api_key': 'k', 'model': 'gemini-3.5-flash-lite'}
        self.exhausted = False
        quota = types.SimpleNamespace(exhausted_today=lambda model: self.exhausted)
        sys.modules['ngup'] = _package('ngup', gemini_quota=quota)
        self.ns = dict(__package__='ngup', os=os,
                       _is_google_translated=lambda p: os.path.isfile(p + '.google'),
                       kodi_utils=types.SimpleNamespace(
                           get_setting=lambda k, d='': self.settings.get(k, d),
                           get_bool=lambda k, d=False: self.settings.get(k, d)))
        _define(TREE, ['_google_cache_upgradeable', '_clear_google_marker'], self.ns)
        self.up = lambda: self.ns['_google_cache_upgradeable'](self.path)

    def tearDown(self):
        sys.modules.pop('ngup', None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_google_fallback_is_translated_again(self):
        self.assertTrue(self.up())

    def test_not_while_the_quota_is_gone_or_without_ai(self):
        self.exhausted = True
        self.assertFalse(self.up())
        self.settings['ai_paid_mode'] = True    # paid keys have no daily cap
        self.assertTrue(self.up())
        self.settings.update(ai_paid_mode=False, api_key='')
        self.exhausted = False
        self.assertFalse(self.up())
        self.settings.update(api_key='k', translation_mode='google')
        self.assertFalse(self.up())

    def test_an_ai_file_is_a_plain_cache_hit(self):
        self.ns['_clear_google_marker'](self.path)
        self.assertFalse(os.path.isfile(self.path + '.google'))
        self.assertFalse(self.up())
        self.ns['_clear_google_marker'](self.path)   # no marker: no error

    def keep(self, replacing):
        done = []
        ns = dict(os=os, _replacing_google=replacing,
                  _is_google_translated=lambda p: os.path.isfile(p + '.google'),
                  kodi_utils=types.SimpleNamespace(log=lambda *a, **k: None),
                  _deliver=lambda p: 'delivered:' + os.path.basename(p),
                  progressive_cb=lambda kind, d: done.append((kind, d)),
                  _progressive_source_id='sid', _src_release='rel')
        return _define(TREE, ['_keep_replaced_google'], ns)['_keep_replaced_google']('overload'), done

    def test_a_failed_upgrade_still_shows_the_google_file(self):
        kept, done = self.keep(self.path)
        self.assertEqual(kept, 'delivered:he.srt')
        self.assertEqual(done, [('done', {'success': True, 'source_id': 'sid',
                                          'release': 'rel', 'path': 'delivered:he.srt'})])
        self.assertEqual(self.keep(None), (None, []))
        os.remove(self.path + '.google')        # an AI file now: nothing to keep
        self.assertEqual(self.keep(self.path), (None, []))

    def test_wiring(self):
        # only a caller with a live preview waits for the AI; the others get
        # the cached file at once, as before
        self.assertIn('if (progressive_cb is not None and local_source\n'
                      '                and os.path.isfile(local_source)\n'
                      '                and _google_cache_upgradeable(translated)):', TRANSLATE)
        self.assertIn('if (progressive_cb is not None\n'
                      '                and _google_cache_upgradeable(translated_by_content)):', TRANSLATE)
        default = (LIB.parent.parent / 'default.py').read_text(encoding='utf-8')
        # the fast path hands the file on only where resolve() looks for it
        self.assertIn("_upgrade = (translate._google_cache_upgradeable(cached)\n"
                      "                        and not kodi_utils.get_bool('gender_ref_arabic', False))\n"
                      "            if os.path.isfile(cached) and not _upgrade:", default)
        # the Google Hebrew goes on screen right after first_ready, before the
        # reference download and the first AI chunk
        placeholder = TRANSLATE.index("'merged_text': _google_prev,")
        self.assertLess(TRANSLATE.index("progressive_cb('first_ready', {"), placeholder)
        self.assertLess(placeholder, TRANSLATE.index("'No cache hit. Starting translation."))
        self.assertIn('google_chunks=_google_chunks)', TRANSLATE)
        # an abort with no AI chunk keeps the cached file, no second request
        abort = TRANSLATE.index("if abort_reason in _GOOGLE_FILL_ABORTS:")
        self.assertIn('gpath = (None if out_blocks_by_index or not _google_chunks\n'
                      '                     else _keep_replaced_google(abort_reason))',
                      TRANSLATE[abort:abort + 900])
        # every failure while replacing hands the Google file back
        self.assertIn("_kept = _keep_replaced_google('not_hebrew')", TRANSLATE)
        missing = TRANSLATE.index("'מקור הכתוביות לא נמצא — בחר שוב'")
        self.assertIn('return _deliver(_replacing_google)', TRANSLATE[missing - 200:missing])
        # other aborts: the reason is shown, then the cached file is delivered
        self.assertIn('        kodi_utils.notify(abort_msg, time_ms=5000)\n'
                      '        _kept = _keep_replaced_google(abort_reason)', TRANSLATE)
        self.assertIn('                kodi_utils.notify(abort_msg, time_ms=5000)\n'
                      "                _emit(False, 'abort:' + str(abort_reason)", TRANSLATE)
        self.assertIn("_kept = _keep_replaced_google('partial')", TRANSLATE)
        self.assertEqual(TRANSLATE.count('_replacing_google = translated'), 2)
        # while the AI works, the viewer keeps the Google Hebrew, not English
        self.assertIn("'fallback_text': (_google_prev\n", TRANSLATE)
        self.assertIn('_merged_blocks.extend(_google_chunks[_i])', TRANSLATE)
        self.assertIn('if len(_gblocks) == sum(len(_c) for _c in chunks):', TRANSLATE)
        # an AI file saved in another slot removes the Google file it replaces
        stale = TRANSLATE.index("if _replacing_google and os.path.isfile(_replacing_google + '.google'):")
        self.assertLess(TRANSLATE.index('_clear_google_marker(_content_slot)'), stale)
        self.assertIn("for _suffix in ('', '.google', '.release'):", TRANSLATE[stale:stale + 200])
        for slot in ('translated', 'translated_by_content'):
            check = TRANSLATE.index('_google_cache_upgradeable(%s)' % slot)
            self.assertLess(check, TRANSLATE.index("'Cache hit (", check))
        self.assertNotIn('UnusableReply', TRANSLATE)   # measured and dropped
        self.assertTrue('cache.save_text(translated, final)\n    _clear_google_marker(translated)' in TRANSLATE)
        self.assertIn('_clear_google_marker(_content_slot)', TRANSLATE)
        abort = TRANSLATE.index("if abort_reason in _GOOGLE_FILL_ABORTS:")
        self.assertIn('gemini_quota.note_exhausted(model)', TRANSLATE[abort:abort + 600])
        self.assertIn('_google_fill_and_save(chunks, dict(out_blocks_by_index)', TRANSLATE[abort:abort + 1400])
        self.assertIn('_merged_text = _preview_clean(_merged_blocks, src_text)', TRANSLATE)
        self.assertIn('body = srt.fold_stray_latin_letter(body)', TRANSLATE)


class QuotaExhaustedDayTests(unittest.TestCase):
    def test_the_day_and_model_are_remembered(self):
        store = {}
        fake = types.SimpleNamespace(set_setting=store.__setitem__,
                                     get_setting=lambda k, d='': store.get(k, d))
        with patch.object(gq, 'kodi_utils', fake), \
                patch.object(gq, '_today_utc', lambda *a: '2026-10-22'):
            self.assertFalse(gq.exhausted_today('gemini-3.5-flash-lite'))
            gq.note_exhausted('gemini-3.5-flash-lite')
            self.assertTrue(gq.exhausted_today('gemini-3.5-flash-lite'))
            self.assertFalse(gq.exhausted_today('gemini-3-flash'))
        with patch.object(gq, 'kodi_utils', fake), \
                patch.object(gq, '_today_utc', lambda *a: '2026-10-23'):
            self.assertFalse(gq.exhausted_today('gemini-3.5-flash-lite'))   # a new Pacific day

    def test_the_setting_is_declared(self):
        # Kodi drops setSetting for an id settings.xml does not declare.
        settings = (LIB.parent / 'settings.xml').read_text(encoding='utf-8')
        self.assertIn('<setting id="%s" type="string"' % gq.SETTING_EXHAUSTED, settings)


# ---- OpenSubtitles keys ----------------------------------------------------

class Reply406(object):
    def __init__(self, text):
        self.text = text


class OpenSubtitlesKeyTests(unittest.TestCase):
    def setUp(self):
        self.keys = [('k%d' % i, 'v%d' % i) for i in range(6)]
        self.ns = dict(_EXHAUSTED_KEYS=set(),
                       get_api_keys=lambda shuffle_keys=False: list(self.keys))
        _define(OS_TREE, ['_download_key_order', '_is_quota_406'], self.ns)

    def test_exhausted_keys_go_last(self):
        self.ns['_EXHAUSTED_KEYS'].update({'k0', 'k3'})
        order = [name for name, _v in self.ns['_download_key_order']()]
        self.assertEqual(sorted(order), sorted(k for k, _v in self.keys))
        self.assertEqual(order[-2:], ['k0', 'k3'])

    def test_quota_406(self):
        quota = self.ns['_is_quota_406']
        self.assertTrue(quota(Reply406('{"message": "You have downloaded your allowed 100 '
                                       'subtitles for 24h. Your quota will be renewed in 3 hours"}')))
        self.assertTrue(quota(Reply406('')))
        self.assertFalse(quota(Reply406('{"message": "Invalid file_id"}')))

    def test_wiring(self):
        text = OS_PATH.read_text(encoding='utf-8')
        self.assertIn('_keys[(api_key_attempt_number - 1) % len(_keys)]', text)
        self.assertNotIn('DownloadSubtitles result: {repr(response_json)}', text)
        self.assertNotIn('repr(http_err)', text)   # its text holds the tokenized link
        self.assertIn('raise RuntimeError("OpenSubtitles DownloadSubtitles %s" % '
                      'type(req_err).__name__) from None', text)
        self.assertIn("remaining={response_json.get('remaining')!r}", text)


class ArchiveCapTests(unittest.TestCase):
    def setUp(self):
        import zipfile
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, 'subs')
        os.makedirs(self.out)
        self.warnings = []
        self.ns = dict(zipfile=zipfile, os=os, exts=['.srt'], convert_to_utf=lambda p: None,
                       log=types.SimpleNamespace(warning=self.warnings.append),
                       xbmcvfs=types.SimpleNamespace(listdir=lambda d: ([], os.listdir(d))),
                       MAX_UNPACKED_BYTES=1000, MAX_ENTRIES=2)
        tree = ast.parse((LIB / 'subs_engine' / 'extract_sub.py').read_text(encoding='utf-8'))
        _define(tree, ['extract'], self.ns)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def archive(self, files):
        import zipfile
        path = os.path.join(self.tmp, 'a.zip')
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, body in files.items():
                z.writestr(name, body)
        return path

    def test_a_subtitle_archive_is_extracted(self):
        path = self.archive({'he.srt': block(1, 'שלום')})
        self.assertEqual(self.ns['extract'](path, self.out), os.path.join(self.out, 'he.srt'))
        self.assertFalse(os.path.exists(path))

    def test_too_much_unpacked_or_too_many_entries_is_skipped(self):
        for files in ({'he.srt': 'x' * 2000}, {'a.srt': '1', 'b.srt': '2', 'c.srt': '3'}):
            path = self.archive(files)
            self.assertEqual(self.ns['extract'](path, self.out), '0')
            self.assertEqual(os.listdir(self.out), [])
            self.assertFalse(os.path.exists(path))
        self.assertEqual(len(self.warnings), 2)


class AudioCueOrderTests(unittest.TestCase):
    def test_cues_are_sorted_on_the_way_out_and_in(self):
        text = (LIB / 'subsync.py').read_text(encoding='utf-8')
        self.assertIn("prior = sorted(ent.get('cues') or [], key=lambda c: c['start'])", text)
        self.assertIn("cues = [c for c in sorted(cues, key=lambda c: c['start'])", text)


if __name__ == '__main__':
    unittest.main()
