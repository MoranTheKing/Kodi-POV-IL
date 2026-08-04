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
ok('a language whose marking was not validated here returns None',
   ag.reference_addressee_gender(u'tú eres', 'es') is None
   and ag.reference_addressee_gender(u'ты хорошая', 'ru') is None)
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

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
