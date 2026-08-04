"""The two halves of getting per-line gender right.

FINDING one. The oracle only helps if it is actually reached. The search is
bounded by an active-work deadline that downloads dominate, so the ORDER the
candidates are tried in decides which languages get a turn at all.

CHECKING it. A reference is a hint in a prompt, and a prompt is an
instruction rather than a guarantee. Measured on a full film with a perfectly
aligned Arabic oracle, 51 of 52 scorable lines came back right and the one
that did not had an unambiguous feminine marker in its own prompt -- so the
last points are compliance, and they close by verifying the output.

Run: python3 tools/test_gender_verification.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai')
sys.path.insert(0, ADDON)

_spec = importlib.util.spec_from_file_location(
    'ag_under_test', os.path.join(ADDON, 'resources', 'lib',
                                  'arabic_gender.py'))
ag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ag)

FAILED = []


def check(name, got, want):
    if got == want:
        print('  ok  - %s' % name)
    else:
        print('  FAIL- %s\n        got  %r\n        want %r' % (name, got, want))
        FAILED.append(name)


def ok(name, cond):
    check(name, bool(cond), True)


def order(by_lang):
    """The ordering begin() builds, extracted so it can be checked directly."""
    depth = max([len(v) for v in by_lang.values()] or [0])
    return [(lang, by_lang[lang][i])
            for i in range(depth)
            for lang in ag._REF_CHAIN
            if i < len(by_lang.get(lang, ()))]


# ---------------------------------------------------------------------------
print('== candidate order: every language gets a turn before any gets two ==')

FULL = {'he': ['he%d' % i for i in range(1, 11)],
        'ar': ['ar%d' % i for i in range(1, 11)],
        'es': ['es1', 'es2'],
        'ru': ['ru1']}
o = order(FULL)
check('the best Hebrew candidate is still first', o[0], ('he', 'he1'))
check('Arabic is reached on the SECOND attempt, not the eleventh',
      next(i for i, (l, _c) in enumerate(o) if l == 'ar') + 1, 2)
check('round 0 is the best of each language, in chain order',
      [c for _l, c in o[:4]], ['he1', 'ar1', 'es1', 'ru1'])
check('round 1 follows, same order', [c for _l, c in o[4:7]],
      ['he2', 'ar2', 'es2'])
# Nothing may be lost or duplicated by the reordering -- it is a permutation.
flat = [(l, c) for l in ag._REF_CHAIN for c in FULL.get(l, [])]
check('same candidates, nothing dropped or repeated',
      sorted(o), sorted(flat))
check('same total attempts', len(o), len(flat))

check('a single language still works', order({'ar': ['a', 'b']}),
      [('ar', 'a'), ('ar', 'b')])
check('no candidates -> empty', order({}), [])
ok('a language not in the chain contributes nothing',
   order({'zz': ['x']}) == [])
# The deep case the reorder exists for: ten Hebrew candidates that all fail.
ONLY_DEEP = {'he': ['he%d' % i for i in range(1, 11)], 'ar': ['ar1']}
check('with 10 Hebrew and 1 Arabic, Arabic is attempt 2 (was 11)',
      next(i for i, (l, _c) in enumerate(order(ONLY_DEEP)) if l == 'ar') + 1, 2)

# ---------------------------------------------------------------------------
print('== reading the addressee gender off a reference ==')

check('Arabic feminine kasra', ag.reference_addressee_gender(
    u'أنتِ تخيفينني حقاً.', 'ar'), 'F')
check('Arabic masculine fatha', ag.reference_addressee_gender(
    u'أنتَ رجل طيب', 'ar'), 'M')
check('Arabic with no marker -> unknown', ag.reference_addressee_gender(
    u'مرحبا بك', 'ar'), None)
check('both markers on one line -> unknown', ag.reference_addressee_gender(
    u'أنتِ و أنتَ', 'ar'), None)
check('Hebrew reference, feminine', ag.reference_addressee_gender(
    u'את יפה מאוד', 'he'), 'F')
check('Hebrew reference, masculine', ag.reference_addressee_gender(
    u'אתה טוב מאוד', 'he'), 'M')
check('Hebrew object marker is NOT an addressee',
      ag.reference_addressee_gender(u'ראיתי את הספר', 'he'), None)

# Every other chain language whose ADDRESSEE marking is a verb ending. Each
# is checked against BOTH genders and against a first/third-person sentence
# that must not match -- a wrong 'F' here rewrites a line that was correct.
for _lang, _text, _want in (
        ('ru', u'ты была права', 'F'),
        ('ru', u'ты был прав', 'M'),
        ('ru', u'она сказала это', None),
        ('ru', u'ты знаешь', None),
        ('uk', u'ти була права', 'F'),
        ('uk', u'ти був правий', 'M'),
        ('uk', u'вона сказала', None),
        ('bg', u'ти беше уморена', 'F'),
        ('bg', u'ти беше уморен', 'M'),
        ('bg', u'той каза', None),
        ('pl', u'zrobiłaś to', 'F'),
        ('pl', u'zrobiłeś to', 'M'),
        ('pl', u'zrobiłem to', None),
        ('cs', u'byla jsi tam', 'F'),
        ('cs', u'byl jsi tam', 'M'),
        ('cs', u'byl jsem tam', None),
        ('sk', u'bola si tam', 'F'),
        ('sk', u'bol si tam', 'M'),
        ('sk', u'bol som tam', None),
        ('sr', u'ti si bila tamo', 'F'),
        ('sr', u'ti si bio tamo', 'M'),
        ('sr', u'ti si rekla to', 'F'),
        ('sr', u'ti si rekao to', 'M'),
        ('sr', u'ona je bila tamo', None),
        ('hr', u'ti si bila tamo', 'F'),
        ('hr', u'ti si bio tamo', 'M'),
        ('hi', u'तुम अच्छी हो', 'F'),
        ('hi', u'तुम अच्छे हो', 'M'),
        ('hi', u'मैं अच्छा हूँ', None),
):
    check('%s: %s' % (_lang, _text),
          ag.reference_addressee_gender(_text, _lang), _want)

# The languages left out on purpose. Adjective agreement is not separable from
# a feminine noun's ending without parsing ("eres una estrella"), Dutch marks
# only referent gender, and Urdu uses Indic morphology rather than the Arabic
# diacritics -- so each returns None and the verification simply does not fire.
for _lang, _text in (('es', u'estás cansada'), ('it', u'sei stanca'),
                     ('pt', u'estás cansada'), ('fr', u'tu es fatiguée'),
                     ('ro', u'ești obosită'), ('el', u'είσαι κουρασμένη'),
                     ('nl', u'zij is moe'), ('ur', u'تم اچھی ہو')):
    ok('%s is deliberately not verified' % _lang,
       ag.reference_addressee_gender(_text, _lang) is None)

ok('an unknown language code returns None',
   ag.reference_addressee_gender(u'whatever', 'zz') is None)
ok('empty / None never raise',
   ag.reference_addressee_gender('', 'ar') is None
   and ag.reference_addressee_gender(None, 'he') is None)

# ---------------------------------------------------------------------------
print('== which entries are provably wrong ==')

BLOCKS = [
    # 1: Hebrew says "אתה", the Arabic says feminine -> provably wrong
    u'1\n00:00:01,000 --> 00:00:02,000\nאתה ממש מבהיל אותי.',
    # 2: Hebrew already feminine -> fine
    u'2\n00:00:03,000 --> 00:00:04,000\nאת ממש מבהילה אותי.',
    # 3: Arabic says MASCULINE and the Hebrew has "את" -- but that "את" is the
    #    object marker, so the mirror check would be a false positive. Not
    #    reported, deliberately.
    u'3\n00:00:05,000 --> 00:00:06,000\nראיתי את דן אתמול.',
    # 4: no reference for this entry
    u'4\n00:00:07,000 --> 00:00:08,000\nאתה בסדר?',
    # 5: reference has no gender marker
    u'5\n00:00:09,000 --> 00:00:10,000\nאתה בסדר?',
]
REF = {1: u'أنتِ تخيفينني حقاً.',
       2: u'أنتِ تخيفينني حقاً.',
       3: u'رأيتَ دان أمس.',
       5: u'مرحبا بك'}

check('exactly the provable one is reported',
      ag.wrong_gender_entries(BLOCKS, REF, 'ar'), [1])
check('a Hebrew reference works the same way',
      ag.wrong_gender_entries(
          [u'1\n00:00:01,000 --> 00:00:02,000\nאתה ממש מבהיל אותי.'],
          {1: u'את מבהילה אותי'}, 'he'), [1])
check('an unvalidated reference language reports nothing',
      ag.wrong_gender_entries(BLOCKS, REF, 'es'), [])
check('no reference map -> nothing', ag.wrong_gender_entries(BLOCKS, {}, 'ar'),
      [])
ok('malformed blocks never raise',
   ag.wrong_gender_entries(['', 'x', '1\n', None or '1\n2\n3'], REF, 'ar')
   is not None)

check('addresses_male sees the masculine pronoun',
      ag.addresses_male(u'אתה ממש מבהיל אותי.'), True)
check('...and not the feminine one',
      ag.addresses_male(u'את ממש מבהילה אותי.'), False)
check('...and not a word that merely contains it',
      ag.addresses_male(u'אתהלך בגן'), False)
ok('addresses_male never raises',
   ag.addresses_male(None) is False and ag.addresses_male('') is False)

# ---------------------------------------------------------------------------
print('== the repair pass accepts only a rewrite that actually repaired ==')

# The acceptance rules live in translate.py's _regender_blocks. They are
# transcribed here as a predicate so each one is pinned by name; the same four
# conditions are applied in that function, in that order.


def accepts(new_body, old_lines):
    new_lines = [l for l in new_body.split('\n') if l.strip()]
    body = '\n'.join(new_lines)
    if not body or ag.addresses_male(body):
        return False
    if not any(u'֐' <= c <= u'׿' for c in body):
        return False
    return len(new_lines) == len(old_lines)


OLD = [u'אתה ממש מבהיל אותי.']
ok('a correct feminine rewrite is accepted',
   accepts(u'את ממש מבהילה אותי.', OLD))
ok('a reply that ignored the instruction is refused',
   not accepts(u'אתה ממש מבהיל אותי.', OLD))
ok('an empty reply is refused', not accepts('', OLD))
ok('a reply that is not Hebrew is refused',
   not accepts('You are freaking me out.', OLD))
ok('a reply that changed the line count is refused',
   not accepts(u'את ממש\nמבהילה אותי.', OLD))

# ---------------------------------------------------------------------------
print('== the repair pass, run for real against a stubbed engine ==')

# translate.py cannot be imported (it needs a live Kodi), so lift the two
# functions out with ast and run them -- the real code, not a copy.
import ast                                                      # noqa: E402
import types                                                     # noqa: E402

TSRC = open(os.path.join(ADDON, 'resources', 'lib', 'translate.py'),
            encoding='utf-8').read()
_tree = ast.parse(TSRC)
_wanted_fns = ('_regender_blocks', '_regender_unguarded')
_defs = [n for n in ast.walk(_tree)
         if isinstance(n, ast.FunctionDef) and n.name in _wanted_fns]
assert len(_defs) == 2, 'expected both repair functions in translate.py'

_engine = types.SimpleNamespace(REQUEST_TIMEOUT=60, calls=[])
_log = types.SimpleNamespace(log=lambda *a, **k: None)
_ns = {'gemini': _engine, 'srt': None, 'kodi_utils': _log,
       'arabic_gender': ag, 'api_key': 'k', 'model': 'm',
       'max_output_tokens': 1024, 'top_p': 1.0, 'thinking_budget': None,
       'thinking_level': None, 'gemini_timeout': None, '_rpm_interval': 0.0,
       '_gemini_rate_gate': lambda _i: None}

_sspec = importlib.util.spec_from_file_location(
    'srt_for_gender', os.path.join(ADDON, 'resources', 'lib', 'srt.py'))
_srt = importlib.util.module_from_spec(_sspec)
_sspec.loader.exec_module(_srt)
_ns['srt'] = _srt

for _d in sorted(_defs, key=lambda n: n.name):
    _d.col_offset = 0
    exec(compile(ast.Module(body=[_d], type_ignores=[]), '<x>', 'exec'), _ns)
regender = _ns['_regender_blocks']


def reply_with(text):
    _engine.calls = []

    def generate(**kw):
        _engine.calls.append(kw)
        return text
    _engine.generate = generate


ONE = [u'1\n00:00:01,000 --> 00:00:02,000\nאתה ממש מבהיל אותי.']

reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nאת ממש מבהילה אותי.')
check('a correct rewrite is spliced in', regender(ONE, [1]),
      [u'1\n00:00:01,000 --> 00:00:02,000\nאת ממש מבהילה אותי.'])
check('exactly one request, however many entries', len(_engine.calls), 1)

# BLOCKER 1: a duplicate index number must not let one cue overwrite another.
DUP = [u'1\n00:00:01,000 --> 00:00:02,000\nאתה יפה מאוד.',
       u'5\n00:00:10,000 --> 00:00:11,000\nAAAA first five.',
       u'3\n00:00:05,000 --> 00:00:06,000\nמשהו אחר.',
       u'5\n00:00:20,000 --> 00:00:21,000\nBBBB second five.']
reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nאת יפה מאוד.')
got = regender(DUP, [1])
check('the flagged entry is still repaired', got[0],
      u'1\n00:00:01,000 --> 00:00:02,000\nאת יפה מאוד.')
check('the duplicated index is left completely alone',
      [got[1], got[3]], [DUP[1], DUP[3]])
check('no cue is lost or duplicated', len(got), len(DUP))
# ...and a repair asked for ON a duplicated index is refused outright
reply_with(u'5\n00:00:20,000 --> 00:00:21,000\nשונה לגמרי.')
check('a duplicated index is not eligible for repair',
      regender(DUP, [5]), DUP)

# BLOCKER 2: a reply in another script, or with no letters, must be refused.
for label, bad in (
        ('Arabic', u'1\n00:00:01,000 --> 00:00:02,000\nأنتِ تخيفينني حقاً.'),
        ('punctuation only', u'1\n00:00:01,000 --> 00:00:02,000\n...'),
        ('English', '1\n00:00:01,000 --> 00:00:02,000\nYou scare me.'),
        ('empty text', u'1\n00:00:01,000 --> 00:00:02,000\n'),
        ('nothing at all', ''),
):
    reply_with(bad)
    check('a reply that is %s is refused' % label, regender(ONE, [1]), ONE)

# BLOCKER 3: a "repair" that still addresses a man, via a glued prefix.
reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nואתה ממש מבהיל אותי.')
check('a still-masculine rewrite behind a glued ו is refused',
      regender(ONE, [1]), ONE)
reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nכשאתה מבהיל אותי.')
check('...and behind a glued כש', regender(ONE, [1]), ONE)

# the rest of the acceptance rules
reply_with(u'9\n00:00:01,000 --> 00:00:02,000\nאת ממש מבהילה אותי.')
check('a reply about an entry we did not ask about is ignored',
      regender(ONE, [1]), ONE)
reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nאת ממש\nמבהילה אותי.')
check('a reply that changed the line count is refused',
      regender(ONE, [1]), ONE)
reply_with(u'1\n99:99:99,999 --> 88:88:88,888\nאת ממש מבהילה אותי.')
check('a reply that moved the cue keeps the SOURCE timecode',
      regender(ONE, [1])[0].split('\n')[1], '00:00:01,000 --> 00:00:02,000')
reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nאת ממש מבהילה אותי.\n\n'
           u'1\n00:00:01,000 --> 00:00:02,000\nאת נורא מבהילה אותי.')
check('a repeated entry in the reply takes the first, not the last',
      regender(ONE, [1])[0].split('\n')[2], u'את ממש מבהילה אותי.')


def _boom(**kw):
    raise RuntimeError('network down')


_engine.generate = _boom
check('an engine that raises leaves every line alone', regender(ONE, [1]), ONE)
reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nאת ממש מבהילה אותי.')
ok('hostile input does not raise into the caller',
   regender(None, [1]) is None and regender([], [1]) == []
   and regender(['x', '', '1\n'], [1]) == ['x', '', '1\n'])
reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nאת ממש מבהילה אותי.')
check('nothing flagged -> no request at all', regender(ONE, []), ONE)
check('...and no request was made', len(_engine.calls), 0)
reply_with(u'1\n00:00:01,000 --> 00:00:02,000\nאת ממש מבהילה אותי.')
check('a malformed block costs no request either',
      regender(['1\n'], [1]), ['1\n'])
check('...confirmed', len(_engine.calls), 0)

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
