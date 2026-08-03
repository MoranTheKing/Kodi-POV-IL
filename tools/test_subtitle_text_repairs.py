"""Text repairs applied to an AI Hebrew translation before it ships.

Four defects were measured on a real 1,957-cue file a user reported, and each
one has a repair here. The point of this file is the SAFETY of those repairs:
every one of them edits Hebrew a viewer is about to read, so what matters is
not only that the defect goes but that nothing else moves.

The invariants, checked directly below:
  * no cue is removed, no line is removed, no line loses its Hebrew
  * cue timings and entry counts are never touched by a text repair
  * a repair anchored to the source can only fire where the source licenses it
  * nothing raises: these run on every translation

Run: python3 tools/test_subtitle_text_repairs.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')

_spec = importlib.util.spec_from_file_location(
    'srt_under_test', os.path.join(LIB, 'srt.py'))
srt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srt)

FAILED = []


def check(name, got, want):
    if got == want:
        print('  ok  - %s' % name)
    else:
        print('  FAIL- %s\n        got  %r\n        want %r' % (name, got, want))
        FAILED.append(name)


def ok(name, cond):
    check(name, bool(cond), True)


def entries(text):
    """[(index, timecode, [text lines])] -- a deliberately independent parse,
    so a bug in srt.py's own parser cannot hide a bug in a repair."""
    out = []
    for blk in text.replace('\r\n', '\n').strip().split('\n\n'):
        lines = [l for l in blk.split('\n') if l.strip()]
        if len(lines) >= 2 and lines[0].strip().isdigit():
            out.append((lines[0].strip(), lines[1].strip(), lines[2:]))
    return out


def has_hebrew(s):
    return any(u'֐' <= c <= u'׿' for c in s)


# ---------------------------------------------------------------------------
print('== translated speaker tag: removed only where the SOURCE had one ==')

SRC = (
    "1\n00:00:01,000 --> 00:00:02,000\n- That's everything.\n- IAN: No, no.\n"
    "\n"
    "2\n00:00:03,000 --> 00:00:04,000\nLook: I don't know.\n"
    "\n"
    "3\n00:00:05,000 --> 00:00:06,000\nBEAR: I should have known.\n"
)
HE = (
    u"1\n00:00:01,000 --> 00:00:02,000\n- זה הכל.\n"
    u"- איאן: לא, לא.\n"
    u"\n"
    u"2\n00:00:03,000 --> 00:00:04,000\nתראה: "
    u"אני לא יודע.\n"
    u"\n"
    u"3\n00:00:05,000 --> 00:00:06,000\nדוב: "
    u"הייתי צריך לדעת.\n"
)
out = srt.strip_hebrew_speaker_prefix(HE, SRC)
e = entries(out)
check('tagged line loses the tag, keeps the dialogue dash',
      e[0][2][1], u'- לא, לא.')
check('untagged line with a colon is UNTOUCHED',
      e[1][2][0], u'תראה: אני לא יודע.')
check('tag with no dash is removed too',
      e[2][2][0], u'הייתי צריך לדעת.')
check('entry count unchanged', len(e), len(entries(HE)))
check('timecodes unchanged', [x[1] for x in e], [x[1] for x in entries(HE)])
check('line counts unchanged', [len(x[2]) for x in e],
      [len(x[2]) for x in entries(HE)])

# The positional anchor: source line 0 has the tag, source line 1 does not.
SRC2 = ("7\n00:00:01,000 --> 00:00:02,000\n- IAN: No.\n"
        "- Look: I don't know.\n")
HE2 = (u"7\n00:00:01,000 --> 00:00:02,000\n- איאן: "
       u"לא.\n- תראה: אני "
       u"לא יודע.\n")
e2 = entries(srt.strip_hebrew_speaker_prefix(HE2, SRC2))
check('position 0 stripped', e2[0][2][0], u'- לא.')
check('position 1 kept (source had no tag there)', e2[0][2][1],
      u'- תראה: אני לא יודע.')

# A "tag" that is the WHOLE line must never empty a cue.
SRC3 = "9\n00:00:01,000 --> 00:00:02,000\nIAN: Hey.\n"
HE3 = u"9\n00:00:01,000 --> 00:00:02,000\nאיאן:\n"
check('a line that is only a tag is left alone (never empty a cue)',
      srt.strip_hebrew_speaker_prefix(HE3, SRC3), HE3)

ok('no source text -> no change',
   srt.strip_hebrew_speaker_prefix(HE, '') == HE)
ok('empty input survives', srt.strip_hebrew_speaker_prefix('', SRC) == '')
ok('None survives', srt.strip_hebrew_speaker_prefix(None, SRC) is None)
ok('CRLF preserved byte for byte',
   srt.strip_hebrew_speaker_prefix(HE.replace('\n', '\r\n'), SRC)
   .count('\r\n') == HE.replace('\n', '\r\n').count('\r\n'))
ok('source with no tags at all -> identity',
   srt.strip_hebrew_speaker_prefix(HE, "1\n00:00:01,000 --> 00:00:02,000\nhi\n")
   == HE)
ok('garbage input does not raise',
   isinstance(srt.strip_hebrew_speaker_prefix('not an srt', 'neither'), str))

# --- the three ways an anchor can point at the wrong line -------------------
# Each of these shipped once. They are here because the positional anchor is
# the ONLY thing standing between this function and real dialogue, and each
# one was a different way of losing track of which line a position names.

# 1. The model merges two source lines into one. Positions then mean
#    different things on the two sides, so NOTHING may be licensed.
MERGE_SRC = ("1\n00:00:01,000 --> 00:00:02,000\nLook, I don't know.\n"
             "IAN: Stop it, now.\n")
MERGE_HE = (u"1\n00:00:01,000 --> 00:00:02,000\nתראה: "
            u"אני לא יודע, תפסיק עכשיו.\n")
check('merged lines license NOTHING (real dialogue survives)',
      srt.strip_hebrew_speaker_prefix(MERGE_HE, MERGE_SRC), MERGE_HE)

# ...including when it is a blank line mid-entry that makes the counts differ
BLANK_SRC = ("1\n00:00:01,000 --> 00:00:02,000\nLook, I don't know.\n\n\n"
             "IAN: Stop.\n")
BLANK_HE = (u"1\n00:00:01,000 --> 00:00:02,000\nתראה: "
            u"אני לא יודע.\n")
check('a blank line mid-entry licenses nothing either',
      srt.strip_hebrew_speaker_prefix(BLANK_HE, BLANK_SRC), BLANK_HE)

# 2. Two blocks share an index number: the untagged one must not spend the
#    tagged one's licence.
DUP_SRC = ("1\n00:00:01,000 --> 00:00:02,000\nIAN: Hello there.\n\n"
           "1\n00:00:05,000 --> 00:00:06,000\nLook, I don't know.\n")
DUP_HE = (u"1\n00:00:01,000 --> 00:00:02,000\nאיאן: "
          u"שלום.\n\n"
          u"1\n00:00:05,000 --> 00:00:06,000\nתראה: "
          u"אני לא יודע.\n")
check('a duplicated index number licenses nothing at all',
      srt.strip_hebrew_speaker_prefix(DUP_HE, DUP_SRC), DUP_HE)

# 3. A line of dialogue that is only digits is NOT an entry boundary. Every
#    index from 1 upward is in use in a real file, so a "2024" or a score
#    would otherwise inherit some unrelated entry's licence.
NUM_SRC = ("1\n00:00:01,000 --> 00:00:02,000\nIAN: Hello there, friend.\n\n"
           "5\n00:00:10,000 --> 00:00:12,000\nOne.\nLook, I don't know.\n")
NUM_HE = (u"1\n00:00:01,000 --> 00:00:02,000\nאיאן: "
          u"שלום, ידיד.\n\n"
          u"5\n00:00:10,000 --> 00:00:12,000\n1\nתראה: "
          u"אני לא יודע.\n")
res_num = srt.strip_hebrew_speaker_prefix(NUM_HE, NUM_SRC)
check('a digits-only DIALOGUE line is not an entry boundary',
      entries(res_num)[1][2], [u'1', u'תראה: אני לא יודע.'])
check('...and the real tag on entry 1 is still removed',
      entries(res_num)[0][2], [u'שלום, ידיד.'])

# ---------------------------------------------------------------------------
print('== wrong-alphabet slip: spelled back, not deleted ==')

CASES = [
    # (leaked, repaired) -- all six are lines measured in real model output
    (u'לעצمي', u'לעצמי'),
    (u'אوه,', u'אוה,'),
    (u'אותي,', u'אותי,'),
    (u'טوب.', u'טוב.'),
    (u'באשمتך.', u'באשמתך.'),
]
for bad, good in CASES:
    line = u'אני ' + bad          # "אני <word>"
    check('glued run transliterated: %s' % bad,
          srt.strip_leaked_arabic(line), u'אני ' + good)

# the space that _ARABIC_RUN_RE swallows must survive
check('the space after a glued run is kept',
      srt.strip_leaked_arabic(u'זוכرة '
                              u'כשהיית'),
      u'זוכרה כשהיית')

# a standalone Arabic word is still DELETED, not transliterated
check('standalone Arabic word still deleted',
      srt.strip_leaked_arabic(u'יש 50 دولار '
                              u'היום'),
      u'יש 50 היום')
# an Arabic PHRASE (spaces / punctuation inside) never reaches transliteration
long_ar = u'אوه، لا، يا لقد'
ok('an Arabic phrase is not spelled into Hebrew gibberish',
   u'לקד' not in srt.strip_leaked_arabic(long_ar))
ok('an all-Arabic line is left alone entirely',
   srt.strip_leaked_arabic(u'مرحبا بك')
   == u'مرحبا بك')
ok('Arabic-Indic digits are not a leak',
   srt.strip_leaked_arabic(u'השעה ١٢')
   == u'השעה ١٢')

print('== the same slip in Cyrillic / Greek / Armenian ==')
check('Cyrillic em inside a Hebrew word',
      srt.fold_foreign_in_hebrew_word(u'אמм...'),
      u'אמם...')
check('Armenian + Cyrillic inside a Hebrew word',
      srt.fold_foreign_in_hebrew_word(u'מպаצחת.'),
      u'מפאצחת.')
ok('a standalone Cyrillic phrase is NEVER touched',
   srt.fold_foreign_in_hebrew_word(u'הוא קרא '
                                   u'Война и '
                                   u'мир')
   == u'הוא קרא Война '
      u'и мир')
# The cap has to hold on the RUN, not on each regex match. A '{1,3}' pattern
# caps the match, so a six-letter word glued to Hebrew came back split in two
# and half-transliterated -- one word in two scripts, worse than either
# leaving it or converting it whole.
_RU = u'Привет'                       # a real 6-letter Russian word
check('a long run glued on BOTH sides is left alone',
      srt.fold_foreign_in_hebrew_word(u'שלום' + _RU + u'שלום'),
      u'שלום' + _RU + u'שלום')
check('a long run glued on ONE side is left alone (no half-conversion)',
      srt.fold_foreign_in_hebrew_word(u'שלום' + _RU + u' שלום'),
      u'שלום' + _RU + u' שלום')
ok('a run of exactly the cap length is still repaired',
   srt.fold_foreign_in_hebrew_word(u'א' + u'мир')
   == u'אמיר')
ok('Latin is not folded (English in a Hebrew subtitle is legitimate)',
   srt.fold_foreign_in_hebrew_word(u'שלום Hello')
   == u'שלום Hello')
ok('standalone Greek (maths) untouched',
   srt.fold_foreign_in_hebrew_word(u'הנוסחה '
                                   u'α + β')
   == u'הנוסחה α + β')
ok('fold never raises on odd input',
   srt.fold_foreign_in_hebrew_word(None) is None
   and srt.fold_foreign_in_hebrew_word('') == '')

# ---------------------------------------------------------------------------
print('== niqqud: points go, punctuation stays ==')
check('vocalised word unpointed',
      srt.strip_niqqud(u'בְּסֵדֶר.'),
      u'בסדר.')
check('gershayim survives', srt.strip_niqqud(u'צה״ל'),
      u'צה״ל')
check('geresh survives', srt.strip_niqqud(u'ג׳ורג׳'),
      u'ג׳ורג׳')
check('maqaf survives', srt.strip_niqqud(u'בֵּית'
                                         u'־הַסֵּ'
                                         u'פֶר'),
      u'בית־הספר')
ok('unpointed text is untouched',
   srt.strip_niqqud(u'שלום') == u'שלום')
ok('niqqud strip never raises',
   srt.strip_niqqud(None) is None and srt.strip_niqqud('') == '')

# ---------------------------------------------------------------------------
print('== orphan dash: the dash of a removed sound cue does not ship ==')
SDH = ("1\n00:00:01,000 --> 00:00:02,000\n- You work so hard.\n- (laughs)\n"
       "\n"
       "2\n00:00:03,000 --> 00:00:04,000\n- (indistinct chatter)\n"
       "- (door creaking)\n"
       "\n"
       "3\n00:00:05,000 --> 00:00:06,000\n-\n"
       "\n"
       "4\n00:00:07,000 --> 00:00:08,000\nIAN: Hello.\n")
cleaned = srt.strip_hi_annotations(SDH, keep_speaker_prefixes=True)
ce = entries(cleaned)
check('the cue with speech keeps ONLY the speech', ce[0][2],
      ['- You work so hard.'])
check('a cue that was nothing but sound cues is dropped entirely',
      [x[0] for x in ce], ['1', '3', '4'])
check('a dash the SOURCE wrote alone is left as it was', ce[1][2], ['-'])
check('speaker prefixes are still kept for the gender hint', ce[2][2],
      ['IAN: Hello.'])
ok('no orphan dash anywhere in the result',
   not any(l.strip() in ('-', '--')
           for _n, _tc, b in ce for l in b if _n != '3'))

# ---------------------------------------------------------------------------
print('== invariants over the repair chain as translate.py applies it ==')


def chain(text, source):
    text = srt.strip_leaked_speaker_prefix(text, hebrew_only=True)
    text = srt.strip_hebrew_speaker_prefix(text, source)
    text = srt.strip_leaked_arabic(text)
    text = srt.strip_source_echo(text)
    text = srt.fold_foreign_in_hebrew_word(text)
    text = srt.strip_niqqud(text)
    return srt.normalize_glyphs(text)


def chain_lossless(text, source):
    """The same chain WITHOUT strip_source_echo.

    Every other stage promises to preserve the line structure exactly, and
    that promise is what the fuzz below checks. strip_source_echo does not
    make it and must not: its whole job is to DROP a cue's leading non-Hebrew
    lines, which is how the model stacking the English above its Hebrew gets
    repaired. Including it here would mean asserting an invariant one member
    of the chain is designed to break, which tests the assertion rather than
    the code. It has its own coverage elsewhere.
    """
    text = srt.strip_leaked_speaker_prefix(text, hebrew_only=True)
    text = srt.strip_hebrew_speaker_prefix(text, source)
    text = srt.strip_leaked_arabic(text)
    text = srt.fold_foreign_in_hebrew_word(text)
    text = srt.strip_niqqud(text)
    return srt.normalize_glyphs(text)


MIXED = (
    u"1\n00:00:01,000 --> 00:00:02,000\n- איאן: "
    u"לא, לא.\n- אמм...\n"
    u"\n"
    u"2\n00:00:03,000 --> 00:00:04,000\nלעצمي "
    u"אמרתי.\n"
    u"\n"
    u"3\n00:00:05,000 --> 00:00:06,000\nבְּסֵ"
    u"דֶר.\n"
    u"\n"
    u"4\n00:00:07,000 --> 00:00:08,000\nمرحبا\n"
)
MIXED_SRC = ("1\n00:00:01,000 --> 00:00:02,000\n- IAN: No, no.\n- Umm...\n"
             "\n2\n00:00:03,000 --> 00:00:04,000\nI told myself.\n"
             "\n3\n00:00:05,000 --> 00:00:06,000\nOkay.\n"
             "\n4\n00:00:07,000 --> 00:00:08,000\nHello\n")
res = chain(MIXED, MIXED_SRC)
before, after = entries(MIXED), entries(res)
check('A: no cue removed', len(after), len(before))
check('C: every timecode identical', [x[1] for x in after],
      [x[1] for x in before])
check('A: no line removed', [len(x[2]) for x in after],
      [len(x[2]) for x in before])
ok('A: no line that had Hebrew lost it',
   all(has_hebrew(''.join(b[2])) for a, b in zip(before, after)
       if has_hebrew(''.join(a[2]))))
ok('the all-Arabic cue is still there, untouched',
   after[3][2] == [u'مرحبا'])
check('every defect in the sample is gone', after[0][2] + after[1][2] + after[2][2],
      [u'- לא, לא.', u'- אמם...',
       u'לעצמי אמרתי.',
       u'בסדר.'])
ok('the chain is idempotent', chain(res, MIXED_SRC) == res)

# ---------------------------------------------------------------------------
print('== malformed input: every repair returns, none raises ==')
JUNK = ['', None, 'x', '1\n', '1\n00:00:01,000 --> 00:00:02,000\n',
        '\n\n\n', 'a\nb\nc', u'1\nשלום',
        '1\n00:00:01,000 --> 00:00:02,000\nhi\n\n1\n'
        '00:00:03,000 --> 00:00:04,000\nagain\n']
for fn_name in ('strip_hebrew_speaker_prefix', 'strip_niqqud',
                'strip_leaked_arabic', 'fold_foreign_in_hebrew_word',
                'strip_hi_annotations'):
    fn = getattr(srt, fn_name)
    bad = None
    for j in JUNK:
        try:
            fn(j, SRC) if fn_name == 'strip_hebrew_speaker_prefix' else fn(j)
        except Exception as exc:                     # noqa: BLE001
            bad = '%r -> %s' % (j, exc)
            break
    ok('%s survives malformed input' % fn_name, bad is None)

# ---------------------------------------------------------------------------
print('== the Google rung: rescues, or leaves the English line whole ==')

# translate.py cannot be imported (it needs a live Kodi), which is why the rest
# of the suite around it reads it as source. _google_rescue is self-contained,
# so lift just that function out and run it against a stubbed engine -- the
# real code, not a copy of it.
import ast                                                     # noqa: E402
import types                                                   # noqa: E402

_tsrc = open(os.path.join(LIB, 'translate.py'), encoding='utf-8').read()
_fn = next(n for n in ast.parse(_tsrc).body
           if isinstance(n, ast.FunctionDef) and n.name == '_google_rescue')
_pkg = types.ModuleType('_povil_stub')
_pkg.__path__ = []
_engine = types.ModuleType('_povil_stub.google_translate')
sys.modules['_povil_stub'] = _pkg
sys.modules['_povil_stub.google_translate'] = _engine
_log = types.ModuleType('_povil_stub.kodi_utils')
_log.log = lambda *a, **k: None
_ns = {'srt': srt, 'kodi_utils': _log,
       '__package__': '_povil_stub', '__name__': '_povil_stub.t'}
exec(compile(ast.Module(body=[_fn], type_ignores=[]), '<rescue>', 'exec'), _ns)
rescue = _ns['_google_rescue']

BLOCK = ['5\n00:00:09,000 --> 00:00:10,500\n- No, no.\n- Stop it.']

_engine.translate_lines = lambda lines, lang: [u'- לא, לא.',
                                               u'- תפסיק.']
got = rescue(BLOCK, 'en')
check('rescued block keeps its index and timecode',
      got[0].split('\n')[:2], ['5', '00:00:09,000 --> 00:00:10,500'])
check('rescued block is Hebrew', got[0].split('\n')[2:],
      [u'- לא, לא.', u'- תפסיק.'])
check('block count unchanged', len(got), len(BLOCK))

_engine.translate_lines = lambda lines, lang: None
ok('engine failure -> None, so the caller keeps the English',
   rescue(BLOCK, 'en') is None)

_engine.translate_lines = lambda lines, lang: [u'- לא, לא.']
ok('a reply with FEWER lines than the cue is refused',
   rescue(BLOCK, 'en') is None)

_engine.translate_lines = lambda lines, lang: [u'א', u'ב', u'ג']
ok('a reply with MORE lines than the cue is refused',
   rescue(BLOCK, 'en') is None)

_engine.translate_lines = lambda lines, lang: ['- No, no.', '- Stop it.']
ok('a reply that is still English is refused',
   rescue(BLOCK, 'en') is None)

_engine.translate_lines = lambda lines, lang: ['   ', '  ']
ok('a blank reply is refused (never blank out a cue)',
   rescue(BLOCK, 'en') is None)

_engine.translate_lines = lambda lines, lang: ['...', '???']
ok('a punctuation-only reply is refused',
   rescue(BLOCK, 'en') is None)


def _boom(lines, lang):
    raise RuntimeError('network down')


_engine.translate_lines = _boom
try:
    ok('D: an engine that RAISES does not take the English line down with it',
       rescue(BLOCK, 'en') is None)
except Exception as exc:                                        # noqa: BLE001
    ok('D: an engine that RAISES does not take the English line down with it',
       False)
    print('        raised: %s' % exc)

ok('a malformed block (no text lines) is refused',
   rescue(['5\n00:00:09,000 --> 00:00:10,500'], 'en') is None)

# ---------------------------------------------------------------------------
print('== seeded fuzz: the invariants hold on shapes nobody thought of ==')

import random                                                   # noqa: E402

_rng = random.Random(20260803)          # fixed: a failure here reproduces
_PIECES = [u'שלום', u'לא, לא.', u'- כן.', u'אמм', u'לעצمي',
           u'בְּסֵדֶר', u'איאן: לא', u'תראה: אני לא יודע', u'♪♪',
           u'مرحبا', u'Привет', u'<i>כן</i>', u'- (laughs)', u'-',
           u'12', u'2024', u'א' * 40, u'', u'טוב.  טוב', u'שלום Hello']
_SPIECES = ['Hello.', '- IAN: No.', 'Look: I do not know.', '[cough]',
            '- (door creaking)', 'MABEL: Hi.', 'One.', '2024', 'x' * 40, '']

_bad = []
for _trial in range(400):
    _n = _rng.randint(1, 6)
    _he, _sr = [], []
    for _k in range(1, _n + 1):
        _tc = '00:00:%02d,000 --> 00:00:%02d,000' % (_k, _k + 1)
        _idx = str(_k if _rng.random() > 0.12 else _rng.randint(1, _n))
        _he.append('\n'.join([_idx, _tc] + [_rng.choice(_PIECES)
                                            for _ in range(_rng.randint(1, 3))]))
        _sr.append('\n'.join([_idx, _tc] + [_rng.choice(_SPIECES)
                                            for _ in range(_rng.randint(1, 3))]))
    _htext, _stext = '\n\n'.join(_he), '\n\n'.join(_sr)
    if _rng.random() > 0.7:
        _htext = _htext.replace('\n', '\r\n')
    try:
        _got = chain_lossless(_htext, _stext)
    except Exception as _exc:                                   # noqa: BLE001
        _bad.append(('raised', _exc, _htext))
        continue
    _a, _b = entries(_htext), entries(_got)
    if len(_a) != len(_b):
        _bad.append(('cue count', len(_a), len(_b), _htext))
    elif [x[1] for x in _a] != [x[1] for x in _b]:
        _bad.append(('timecode moved', _htext))
    elif [len(x[2]) for x in _a] != [len(x[2]) for x in _b]:
        _bad.append(('line count', _htext))
    else:
        for _x, _y in zip(_a, _b):
            if has_hebrew(''.join(_x[2])) and not has_hebrew(''.join(_y[2])):
                _bad.append(('lost all Hebrew', _x, _y))
                break
    if _got != chain_lossless(_got, _stext):
        _bad.append(('not idempotent', _htext))

ok('400 randomised SRTs: no cue, line, timecode or Hebrew lost, all '
   'idempotent', not _bad)
if _bad:
    for _b1 in _bad[:3]:
        print('        %r' % (_b1,))

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
