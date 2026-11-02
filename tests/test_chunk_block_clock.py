"""A chunk's 120 s budget runs from its first content block (0.3.69).

Field, 2 Nov 2026 (Frasier S11E13, MoranSubs 0.3.68): chunks with no block at
all passed 120 s on a slow evening Gemini; 18 lines went out without the
Arabic reference and 7 the reply skipped stayed in English. A whole-subtitle
request passed the budget on almost every run (203 of 422 lines without the
reference, 8 in English). The clock now starts at the chunk's first block (an
output-check rejection is no block); a chunk that never blocks has a slow cap
in time and in requests instead. Entries every Gemini rung left out get
Google Translate before they stay in English.

These run translate.py's own chunk functions (_translate_one,
_english_only_safe, _top_up_missing) with a scripted Gemini and a fake clock.
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
TRANSLATE = (LIB / 'translate.py').read_text(encoding='utf-8')
TREE = ast.parse(TRANSLATE)


def _load(name):
    spec = importlib.util.spec_from_file_location('bc_' + name, LIB / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
            log=lambda *a, **k: None)}):
        spec.loader.exec_module(module)
    return module


srt = _load('srt')
gemini = _load('gemini')


def _define(names, ns):
    """translate.py's own (possibly nested) functions and classes, run in `ns`."""
    for name in names:
        for node in ast.walk(TREE):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
                node.col_offset = 0
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<%s>' % name, 'exec'), ns)
                break
        else:
            raise AssertionError('no ' + name)
    return ns


def _assigned(name):
    """A literal assigned anywhere in translate.py (nested constants too)."""
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            return ast.literal_eval(node.value)
    raise AssertionError('no constant ' + name)


def block(n, text):
    return '%d\n00:%02d:%02d,000 --> 00:%02d:%02d,900\n%s' % (n, n // 60, n % 60, n // 60, n % 60, text)


def hebrew(blocks):
    return '\n\n'.join(b.replace('Line', 'שורה') for b in blocks)


class _Abort(Exception):
    pass


CONSTANTS = ('_CHUNK_BLOCK_BUDGET', '_CHUNK_SLOW_CAP', '_CHUNK_SLOW_PER_LINE', '_CHUNK_MAX_CALLS',
             '_CHUNK_LINES_PER_CALL', '_EO_GRACE', '_TOPUP_ROUNDS')


class Chunk(object):
    """The chunk translator's closure around a scripted Gemini and clock."""

    def __init__(self, script, google=None):
        self.now = [1000.0]
        self.calls = []
        self.stat = {}
        self.script = script          # (blocks, level) -> reply text, or raise
        self.google = google          # text -> Hebrew SRT text, or None
        clock = types.SimpleNamespace(monotonic=lambda: self.now[0], time=lambda: self.now[0])

        def call(idx, ch, ref_level=0, he_context=None):
            self.calls.append((len(ch), ref_level))
            return self.script(ch, ref_level)

        def count(kind, n=1):
            self.stat[kind] = self.stat.get(kind, 0) + n

        gt = types.SimpleNamespace(translate_srt=lambda text, lang: (
            self.google(text) if self.google else None))
        self.pkg = types.ModuleType('bcpkg')
        self.pkg.__path__ = []
        self.pkg.google_translate = gt
        self.ns = dict(
            __package__='bcpkg', time=clock, srt=srt, gemini=gemini,
            kodi_utils=types.SimpleNamespace(log=lambda *a, **k: None),
            _call_gemini=call, _count=count, _ref_ensure=lambda lvl: False,
            _ref_stack=[('ar', {})], _accepted_before=lambda *a, **k: None,
            _google_rescue=lambda blocks, lang: None, _AbortTranslation=_Abort,
            source_lang='en', NO_REF=-1, _MAX_ALT_LEVELS=5)
        for name in CONSTANTS:
            self.ns[name] = _assigned(name)
        _define(['_answered', '_google_fill_missing', '_IntegrityRejected', '_BlockClock', '_gem',
                 '_english_only_safe', '_top_up_missing', '_translate_one'], self.ns)

    def clock(self, max_calls=100):
        return self.ns['_BlockClock'](_assigned('_CHUNK_BLOCK_BUDGET'), 600, max_calls)

    def __call__(self, name, *args):
        with patch.dict(sys.modules, {'bcpkg': self.pkg, 'bcpkg.google_translate': self.pkg.google_translate}):
            return self.ns[name](*args)

    def run(self, ch):
        return self('_translate_one', 1, ch)


CH = [block(n, 'Line %d' % n) for n in range(1, 51)]
GOOGLE = staticmethod(lambda text: text.replace('Line', 'גוגל'))


class Clock(unittest.TestCase):

    def test_a_slow_chunk_with_no_block_keeps_its_reference(self):
        # the Frasier run: a first reply slow and short, a bisect, both halves
        # answered after the old 120 s
        def script(ch, level):
            c.now[0] += 70
            if len(ch) == 50:
                return hebrew(ch[:30])          # low yield -> bisect
            return hebrew(ch)
        c = Chunk(script)
        out = c.run(CH)
        self.assertEqual(c.stat, {'ar': 50})
        self.assertNotIn(-1, [lvl for _n, lvl in c.calls])
        self.assertEqual(len(srt.parse_blocks(out)), 50)
        self.assertNotIn('Line', out)

    def test_a_whole_subtitle_request_is_topped_up_after_four_minutes(self):
        # one 422-line request (whole_subtitle_request): the reply after 250 s,
        # 20 entries short -- on the old clock its top-up was refused and they
        # stayed in English
        whole = [block(n, 'Line %d' % n) for n in range(1, 423)]

        def script(ch, level):
            c.now[0] += 250 if len(ch) == 422 else 30
            return hebrew(ch[:400]) if len(ch) == 422 else hebrew(ch)
        c = Chunk(script, google=lambda text: self.fail('no Google while Gemini answers'))
        out = c.run(whole)
        self.assertEqual(c.calls, [(422, 0), (22, 0)])
        self.assertEqual(c.stat, {'ar': 422})
        self.assertNotIn('Line', out)
        cap, per = _assigned('_CHUNK_SLOW_CAP'), _assigned('_CHUNK_SLOW_PER_LINE')
        self.assertGreater(per * 422, cap)            # its time cap grows with it

    def test_after_a_block_the_budget_still_applies(self):
        state = {'blocked': 0}

        def script(ch, level):
            c.now[0] += 40
            if level == 0 and 'Line 7\n' in '\n'.join(ch) + '\n' and len(ch) > 1:
                state['blocked'] += 1
                raise gemini.FilteredResponse('PROHIBITED_CONTENT')
            return hebrew(ch)
        c = Chunk(script)
        out = c.run(CH)
        self.assertGreater(state['blocked'], 0)
        self.assertGreater(c.stat.get('noar', 0), 0)          # the remainder English-only
        self.assertIn(-1, [lvl for _n, lvl in c.calls])
        self.assertEqual(len(srt.parse_blocks(out)), 50)

    def test_every_kind_of_block_starts_it(self):
        # a stop (RECITATION...), a block at one line, a block in a top-up
        stop = Chunk(lambda ch, level: (_ for _ in ()).throw(gemini.StoppedEarly('RECITATION'))
                     if level == 0 and len(ch) > 1 else hebrew(ch))
        clock = stop.clock()
        stop('_translate_one', 1, CH[:4], clock)
        self.assertEqual(clock.until, 1000.0 + _assigned('_CHUNK_BLOCK_BUDGET'))
        one = Chunk(lambda ch, level: (_ for _ in ()).throw(gemini.FilteredResponse('x'))
                    if level == 0 else hebrew(ch))
        one.ns['_ref_stack'] = [('ar', {})]
        clock = one.clock()
        one('_translate_one', 1, CH[:1], clock)
        self.assertIsNotNone(clock.until)
        up = Chunk(lambda ch, level: (_ for _ in ()).throw(gemini.FilteredResponse('x'))
                   if level == 0 else hebrew(ch))
        clock = up.clock()
        out, _kept = up('_top_up_missing', 1, CH[:10], hebrew(CH[:7]), clock)
        self.assertIsNotNone(clock.until)
        self.assertEqual(len(srt.parse_blocks(out)), 10)

    def test_an_output_check_rejection_is_no_block(self):
        # an echoed source cue, a self-edit...: retried, but the budget does
        # not start -- on a slow evening that was the 0.3.68 symptom again
        state = {'n': 0}

        def script(ch, level):
            state['n'] += 1
            c.now[0] += 130
            if state['n'] == 1:
                raise c.ns['_IntegrityRejected']('generated-output integrity violation')
            return hebrew(ch[2:]) if state['n'] == 2 else hebrew(ch)
        c = Chunk(script, google=lambda text: self.fail('no Google while Gemini answers'))
        clock = c.clock()
        out = c('_translate_one', 1, CH[:20], clock)
        self.assertIsNone(clock.until)
        self.assertEqual(c.stat.get('noar', 0) + c.stat.get('src', 0), 0, c.stat)
        self.assertNotIn('Line', out)
        self.assertIn("raise _IntegrityRejected(\n                        'generated-output integrity violation')",
                      TRANSLATE.replace('\r\n', '\n'))

    def test_the_slow_cap_still_bounds_a_chunk_that_never_blocks(self):
        # every reply half short: a bisect storm with no block, slow
        def script(ch, level):
            c.now[0] += 130
            if level == -1:
                return hebrew(ch)
            return hebrew(ch[:len(ch) // 2]) if len(ch) > 1 else hebrew(ch)
        c = Chunk(script, google=GOOGLE)
        out = c.run(CH)
        cap, grace = _assigned('_CHUNK_SLOW_CAP'), _assigned('_EO_GRACE')
        # past the cap: English-only, and past its grace Google with no more
        # Gemini calls -- the same breaker a block storm has
        self.assertIn(-1, [lvl for _n, lvl in c.calls])
        self.assertEqual(c.stat.get('src', 0), 0)
        self.assertEqual(sum(c.stat.values()), 50)
        self.assertLess(len(c.calls), 20)
        self.assertLessEqual(c.now[0] - 1000.0, cap + grace + 130)
        self.assertEqual(len(srt.parse_blocks(out)), 50)
        self.assertNotIn('Line', out)

    def test_and_a_request_ceiling_bounds_a_fast_one(self):
        # the same storm at 1 s a request (a paid key, no pacing): the time cap
        # never trips; requests do (review: 81 for 50 lines without it)
        def script(ch, level):
            c.now[0] += 1
            return hebrew(ch[:len(ch) // 2]) if len(ch) > 1 else hebrew(ch)
        c = Chunk(script, google=GOOGLE)
        out = c.run(CH)
        ceiling = _assigned('_CHUNK_MAX_CALLS') + 50 // _assigned('_CHUNK_LINES_PER_CALL')
        self.assertLessEqual(len(c.calls), ceiling + ceiling // 2 + 2, len(c.calls))
        self.assertEqual(c.stat.get('src', 0), 0)
        self.assertEqual(sum(c.stat.values()), 50)
        self.assertEqual(len(srt.parse_blocks(out)), 50)
        self.assertNotIn('Line', out)


class Ceiling(unittest.TestCase):
    """The request ceiling, and its half again in the grace."""

    def test_before_a_block_it_counts(self):
        c = Chunk(None)
        clock = c.clock(max_calls=10)
        clock.calls = 10
        self.assertFalse(clock.spent())
        clock.calls = 11
        self.assertTrue(clock.spent())
        self.assertFalse(clock.spent(_assigned('_EO_GRACE')))      # half again
        clock.calls = 16
        self.assertTrue(clock.spent(_assigned('_EO_GRACE')))

    def test_a_block_fight_has_its_time_alone(self):
        # review: a fast paid key fighting 2-3 blocked lines ran out of
        # requests long before 120 s and sent ~30 lines out English-only
        c = Chunk(None)
        clock = c.clock(max_calls=10)
        clock.block()
        clock.calls = 60
        self.assertFalse(clock.spent())
        c.now[0] += _assigned('_CHUNK_BLOCK_BUDGET') + 1
        self.assertTrue(clock.spent())

    def test_a_fast_fight_against_two_blocked_lines(self):
        def script(ch, level):
            c.now[0] += 1
            if level >= 0 and any(('Line %d\n' % n) in '\n'.join(ch) + '\n' for n in (13, 31)):
                raise gemini.FilteredResponse('PROHIBITED_CONTENT')
            return hebrew(ch)
        c = Chunk(script, google=GOOGLE)
        c.ns['_ref_stack'] = [('ar', {})]
        out = c.run(CH)
        self.assertEqual(c.stat.get('noar', 0), 2, c.stat)       # only the two lines
        self.assertEqual(c.stat.get('ar', 0), 48, c.stat)
        self.assertNotIn('Line', out)


class Missing(unittest.TestCase):
    """Entries a reply left out once no more Gemini calls are allowed."""

    def english_only(self, google, reply_from=3):
        # the budget spent after a block; the English-only reply leaves out
        # 3 of 25 (within the 85% yield, so no bisect)
        c = Chunk(lambda ch, level: hebrew(ch[reply_from:]), google=google)
        clock = c.clock()
        clock.block()
        c.now[0] += 130
        return c, c('_english_only_safe', 1, CH[:25], clock)

    def test_they_get_google_translate(self):
        c, out = self.english_only(GOOGLE)
        self.assertEqual(c.calls, [(25, -1)])
        self.assertEqual(c.stat, {'noar': 25, 'src': 0})
        self.assertNotIn('Line', out)
        self.assertEqual(len(srt.parse_blocks(out)), 25)
        self.assertIn('גוגל 1\r\n', out)

    def test_source_only_when_google_fails_too(self):
        c, out = self.english_only(lambda text: None)
        self.assertEqual(c.stat, {'noar': 22, 'src': 3})
        self.assertIn('Line 1\r\n', out)
        self.assertEqual(len(srt.parse_blocks(out)), 25)

    def test_a_google_reply_without_hebrew_is_no_fill(self):
        c, out = self.english_only(lambda text: text)
        self.assertEqual(c.stat, {'noar': 22, 'src': 3})

    def test_past_the_grace_google_without_a_gemini_call(self):
        c = Chunk(lambda ch, level: self.fail('no Gemini call past the grace'), google=GOOGLE)
        clock = c.clock()
        clock.block()
        c.now[0] += 120 + _assigned('_EO_GRACE') + 1
        out = c('_english_only_safe', 1, CH[:5], clock)
        self.assertEqual(c.stat, {'noar': 5, 'src': 0})
        self.assertNotIn('Line', out)
        c = Chunk(lambda ch, level: self.fail('no Gemini call'), google=lambda text: None)
        clock = c.clock()
        clock.block()
        c.now[0] += 300
        self.assertEqual(c('_english_only_safe', 1, CH[:5], clock), '\n\n'.join(CH[:5]))
        self.assertEqual(c.stat, {'noar': 0, 'src': 5})


class TopUp(unittest.TestCase):

    def test_a_slow_reply_with_no_block_is_topped_up(self):
        # Frasier: the first reply came after the old 120 s, 3 entries short
        def script(ch, level):
            c.now[0] += 130
            return hebrew(ch[3:]) if len(ch) == 20 else hebrew(ch)
        c = Chunk(script, google=lambda text: self.fail('no Google while Gemini may answer'))
        out = c.run(CH[:20])
        self.assertEqual(c.calls, [(20, 0), (3, 0)])
        self.assertEqual(c.stat, {'ar': 20})
        self.assertNotIn('Line', out)

    def test_past_the_budget_after_a_block_google_fills_the_top_up(self):
        state = {'n': 0}

        def script(ch, level):
            state['n'] += 1
            if state['n'] == 1:
                c.now[0] += 10
                raise gemini.FilteredResponse('PROHIBITED_CONTENT')
            c.now[0] += 130
            return hebrew(ch[3:])
        c = Chunk(script, google=GOOGLE)
        c.ns['_ref_ensure'] = lambda lvl: lvl == 1
        c.ns['_ref_stack'] = [('ar', {}), ('es', {})]
        out = c.run(CH[:20])
        self.assertEqual(c.calls, [(20, 0), (20, 1)])
        self.assertEqual(c.stat, {'blocks': 1, 'noar': 3, 'src': 0, 'alt': 17})
        self.assertNotIn('Line', out)
        self.assertEqual(len(srt.parse_blocks(out)), 20)


if __name__ == '__main__':
    unittest.main()
