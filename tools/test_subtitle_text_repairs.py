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

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
