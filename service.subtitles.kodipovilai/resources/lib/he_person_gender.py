# -*- coding: utf-8 -*-
"""Read the gender of the SPEAKER and the ADDRESSEE from Hebrew text.

Why this exists. Measured in a real Kodi on Gemini 3.5 Flash-Lite: with a
human Hebrew reference in the prompt for nearly every line, the model still
put "אני יודעת" in a man's mouth and "את מאזינה" to a father -- it leans to
the dominant gender of the show and overrides the per-line evidence. The
existing verification read the ADDRESSEE only, from a dozen verbs, so the
commonest error, the speaker's own first-person form, was never checked.

Deliberately narrow. A form is read only where Hebrew spells the gender
unambiguously in context:

  * speaker   -- "אני" (optionally "לא", "כל כך", "ממש"...) + a predicate
                 from the lexicon below (יודע/יודעת, מצטער/מצטערת ...);
  * addressee -- "אתה" (masculine), or "את"/"אתה" + a lexicon predicate,
                 or a second-person command/future from the lexicon
                 (תדאג/תדאגי, תירגע/תירגעי, בוא/בואי ...), or "אל ת..."
                 with/without the feminine "י".

Anything else -- past tense (עשית), suffixes spelled alike (לך, שלך),
participles spelled alike in both genders (רוצה, רואה) -- reads as unknown,
and unknown never triggers a rewrite.

Lines that hold more than one speaker ("- ...\n- ...") are read per part.
"""

import re

_WORD = re.compile(u'[א-ת]+')
_PROCLITIC = (u'וכש', u'כש', u'וש', u'ש', u'ו')

# masculine -> feminine predicates that follow "אני" / "אתה" / "את".
_PRED = {
    u'יודע': u'יודעת', u'חושב': u'חושבת', u'אוהב': u'אוהבת', u'הולך': u'הולכת',
    u'מבין': u'מבינה', u'מצטער': u'מצטערת', u'בטוח': u'בטוחה', u'צריך': u'צריכה',
    u'יכול': u'יכולה', u'מוכן': u'מוכנה', u'עייף': u'עייפה', u'שמח': u'שמחה',
    u'מתכוון': u'מתכוונת', u'מאמין': u'מאמינה', u'זוכר': u'זוכרת', u'מכיר': u'מכירה',
    u'שונא': u'שונאת', u'מפחד': u'מפחדת', u'מרגיש': u'מרגישה', u'עובד': u'עובדת',
    u'גר': u'גרה', u'נשבע': u'נשבעת', u'מבטיח': u'מבטיחה', u'צודק': u'צודקת',
    u'עסוק': u'עסוקה', u'רעב': u'רעבה', u'מאושר': u'מאושרת', u'מחבב': u'מחבבת',
    u'מדבר': u'מדברת', u'מקשיב': u'מקשיבה', u'נשוי': u'נשואה', u'חושש': u'חוששת',
    u'מודאג': u'מודאגת', u'מתרגש': u'מתרגשת', u'מבולבל': u'מבולבלת', u'כועס': u'כועסת',
    u'עצוב': u'עצובה', u'חייב': u'חייבת', u'מסוגל': u'מסוגלת', u'אשם': u'אשמה',
    u'משוגע': u'משוגעת', u'רציני': u'רצינית', u'יושב': u'יושבת', u'עומד': u'עומדת',
    u'חוזר': u'חוזרת', u'מגיע': u'מגיעה', u'נוסע': u'נוסעת', u'לוקח': u'לוקחת',
    u'נותן': u'נותנת', u'עוזב': u'עוזבת', u'מסכים': u'מסכימה', u'מתגעגע': u'מתגעגעת',
    u'מאזין': u'מאזינה', u'מנסה': None, u'רוצה': None, u'רואה': None, u'עושה': None,
    u'נראה': u'נראית', u'משקר': u'משקרת', u'צוחק': u'צוחקת',
    u'מתלוצץ': u'מתלוצצת', u'מת': u'מתה', u'בודד': u'בודדה',
    u'מקנא': u'מקנאה', u'נבוך': u'נבוכה', u'מופתע': u'מופתעת', u'בהלם': None,
    u'אחראי': u'אחראית', u'גאה': None, u'טועה': None, u'חולה': None, u'מקווה': None,
    u'נהנה': None, u'בוכה': None, u'קונה': None, u'שותה': None, u'מחכה': None,
    u'יוצא': u'יוצאת', u'נכנס': u'נכנסת', u'משחק': u'משחקת', u'מספר': u'מספרת',
    u'שואל': u'שואלת', u'מבקש': u'מבקשת', u'מודה': None, u'שוכח': u'שוכחת',
    u'מוותר': u'מוותרת', u'מתחתן': u'מתחתנת', u'בא': u'באה', u'נוהג': u'נוהגת',
    u'ישן': u'ישנה', u'ער': u'ערה', u'בסדר': None, u'לבד': None, u'מרוצה': None,
    u'מאוהב': u'מאוהבת', u'בן': u'בת', u'ילד': u'ילדה', u'חבר': u'חברה',
}
_PRED_M = {m: f for m, f in _PRED.items() if f}
# Nouns in the lexicon. After a bare "את" they are the object marker's
# object ("פגשתי את חברה שלך"), not "you are a ...".
_PERSON_NOUNS = frozenset((u'בן', u'בת', u'ילד', u'ילדה', u'חבר', u'חברה'))
_PRED_F = {f: m for m, f in _PRED_M.items()}

# Second-person commands and futures: masculine -> feminine.
_IMP = {
    u'בוא': u'בואי', u'שב': u'שבי', u'תן': u'תני', u'קח': u'קחי', u'קום': u'קומי',
    u'תקשיב': u'תקשיבי', u'תסתכל': u'תסתכלי', u'תגיד': u'תגידי', u'תעשה': u'תעשי',
    u'תראה': u'תראי', u'תחכה': u'תחכי', u'תירגע': u'תירגעי', u'תדאג': u'תדאגי',
    u'תאמין': u'תאמיני', u'תזוז': u'תזוזי', u'תפסיק': u'תפסיקי', u'תעזוב': u'תעזבי',
    u'תבוא': u'תבואי', u'תלך': u'תלכי', u'תשב': u'תשבי', u'תביא': u'תביאי',
    u'תסלח': u'תסלחי', u'תעזור': u'תעזרי', u'תחשוב': u'תחשבי', u'תזכור': u'תזכרי',
    u'תשמע': u'תשמעי', u'תרגיש': u'תרגישי', u'תהיה': u'תהיי', u'תדבר': u'תדברי',
    u'תשתוק': u'תשתקי', u'תצא': u'תצאי', u'תיכנס': u'תיכנסי', u'תעצור': u'תעצרי',
    u'תנסה': u'תנסי', u'תמשיך': u'תמשיכי', u'תספר': u'תספרי', u'תבטיח': u'תבטיחי',
    u'תוכל': u'תוכלי', u'תרצה': u'תרצי', u'תדע': u'תדעי', u'תשאל': u'תשאלי',
    u'תתקשר': u'תתקשרי', u'תחזור': u'תחזרי', u'תיזהר': u'תיזהרי', u'תשכח': u'תשכחי',
    u'תסתדר': u'תסתדרי', u'תעמוד': u'תעמדי', u'תפתח': u'תפתחי', u'תסגור': u'תסגרי',
    u'תאכל': u'תאכלי', u'תשתה': u'תשתי', u'תישן': u'תישני', u'תעשי': None,
    u'הקשב': u'הקשיבי', u'חכה': u'חכי', u'שמע': u'שמעי', u'תסמוך': u'תסמכי',
    u'תשמור': u'תשמרי', u'תדאגי': None, u'תרגע': u'תרגעי',
}
_IMP_M = {m: f for m, f in _IMP.items() if f}
_IMP_F = {f: m for m, f in _IMP_M.items()}

_FILLERS = frozenset((u'לא', u'כל', u'כך', u'ממש', u'מאוד', u'פשוט', u'רק', u'גם',
                      u'עדיין', u'כבר', u'באמת', u'די', u'נורא', u'ממש', u'בכלל',
                      u'תמיד', u'אף', u'פעם', u'קצת', u'כזה', u'כזאת', u'כנראה',
                      u'בטח', u'עכשיו', u'היום', u'שוב', u'יותר',
                      u'בהחלט', u'לגמרי', u'סתם', u'עוד', u'ממש', u'כלל'))


def _strip_clitic(word):
    for c in _PROCLITIC:
        if word.startswith(c) and len(word) > len(c) + 1:
            rest = word[len(c):]
            if (rest in (u'אני', u'אתה', u'את') or rest in _PRED_M
                    or rest in _PRED_F or rest in _IMP_M or rest in _IMP_F):
                return rest
    return word


_BIDI = re.compile(u'[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]')
_TAG = re.compile(u'<[^>]*>')
# Two speakers on ONE line ("-אתה אוהב עוגה? -מה?"), as human Hebrew subtitles
# often write them: a dash after sentence punctuation opens the next turn.
_INLINE_TURN = re.compile(u'(?<=[?!.,\u2026"])\\s+-\\s*(?=\\S)')


def _segments(text):
    """Speaker turns: a line starting with '-' opens a new turn, and so does a
    second dash inside such a line. Invisible direction marks are ignored --
    measured: a human line "\u202b-..." hid its dash and was read as one
    turn against the AI's two, so the comparison was skipped."""
    parts, cur = [], []
    for line in _TAG.sub('', _BIDI.sub('', text or '')).split('\n'):
        s = line.strip()
        pieces = _INLINE_TURN.split(s) if s.startswith('-') else [s]
        for k, piece in enumerate(pieces):
            if (piece.startswith('-') or k) and cur:
                parts.append(' '.join(cur))
                cur = []
            cur.append(piece.lstrip('- ').strip())
    if cur:
        parts.append(' '.join(cur))
    return [p for p in parts if p]


# "את" is also the object marker ("ראיתי את דני"), so on its own it proves
# nothing. Followed by one of these, or closing a clause ("מי את?"), it can
# only be the pronoun "you" (feminine).
_AT_PRONOUN_NEXT = frozenset((u'כמו', u'לא', u'באמת', u'פה', u'כאן', u'שם',
                              u'בטח', u'תמיד', u'עדיין', u'כבר', u'גם', u'בסדר',
                              u'צריכה', u'יכולה', u'חייבת', u'אמורה'))
_AT_CLAUSE_END = re.compile(u'(?<![\u05d0-\u05ea])ו?את(?=\\s*[?!.,\u2026]|\\s*$)')


def _read_turn(turn):
    """{'speaker': 'F'|'M'|None, 'addressee': 'F'|'M'|None} for one turn."""
    s_votes, a_votes = _votes(turn)
    return {'speaker': s_votes.pop() if len(s_votes) == 1 else None,
            'addressee': a_votes.pop() if len(a_votes) == 1 else None}


def _votes(turn):
    """(speaker genders, addressee genders) the lexicon reads in one turn."""
    words = [_strip_clitic(w) for w in _WORD.findall(turn)]
    s_votes, a_votes = set(), set()
    for i, w in enumerate(words):
        if w in (u'אני', u'אתה', u'את'):
            j = i + 1
            while j < len(words) and words[j] in _FILLERS and j - i <= 3:
                j += 1
            nxt = words[j] if j < len(words) else ''
            g = 'M' if nxt in _PRED_M else ('F' if nxt in _PRED_F else None)
            if w == u'אני' and g:
                s_votes.add(g)
            elif w == u'אתה':
                a_votes.add('M')
            elif w == u'את' and ((g == 'F' and nxt not in _PERSON_NOUNS)
                                 or (i + 1 < len(words)
                                     and words[i + 1] in _AT_PRONOUN_NEXT)):
                a_votes.add('F')
        elif w in _IMP_M:
            # Bare masculine commands also read as nouns or as a third-person
            # future (תגיד = "she will say" too); trust them only at the start
            # of the turn or after "אל" -- and "תהיה" only after "אל": at the
            # start it is just as often "there will be" (תהיה מסיבה מחר).
            if words[i - 1:i] == [u'אל'] or (i == 0 and w != u'תהיה'):
                a_votes.add('M')
        elif w in _IMP_F:
            a_votes.add('F')
    if _AT_CLAUSE_END.search(turn):
        a_votes.add('F')
    return s_votes, a_votes


def read(text):
    """Per-turn readings of a Hebrew subtitle text: [{'speaker','addressee'}]."""
    return [_read_turn(t) for t in _segments(text)]


def _anchors(turn):
    """[(role, pronoun, next word)] for every אני / אתה / את in one turn."""
    words = [_strip_clitic(w) for w in _WORD.findall(turn)]
    out = []
    for i, w in enumerate(words):
        if w in (u'אני', u'אתה', u'את'):
            j = i + 1
            while j < len(words) and words[j] in _FILLERS and j - i <= 3:
                j += 1
            if j < len(words):
                out.append(('speaker' if w == u'אני' else 'addressee', w, words[j]))
    return out


# A masculine word ending in a final letter keeps it only at the end:
# מתאמן / מתאמנת.
_UNFINAL = {0x05da: 0x05db, 0x05dd: 0x05de, 0x05df: 0x05e0,
            0x05e3: 0x05e4, 0x05e5: 0x05e6}


# Nouns that open with ת and take a possessive י ("תלמידי" = my students),
# which would otherwise pair like a command ("תלך" / "תלכי").
_T_NOUNS = frozenset((u'תלמיד', u'תינוק', u'תיק', u'תור', u'תפקיד', u'תחביב',
                      u'תרגיל', u'תהליך', u'תסריט', u'תקציב', u'תאריך', u'תחום',
                      u'תכשיט', u'תשלום', u'תפריט', u'תוכן', u'תמיד', u'תודה'))
# Words that may open a line in both genders' lines and take a possessive י.
_LEAD_NOUNS = frozenset((u'אח', u'אב', u'בן', u'דוד', u'חבר', u'ילד', u'סב'))


# Bare commands whose feminine is the same word + י. Only these pair: any
# other word that opens a line may meet a י-form that is a name (זיג /
# זיגי, measured), a question word (מה / מהי) or a typo (אנ / אני).
_BARE_IMP = frozenset(w.translate({0x05da: 0x05db, 0x05dd: 0x05de, 0x05df: 0x05e0,
                                   0x05e3: 0x05e4, 0x05e5: 0x05e6}) for w in (
    u'בוא', u'שב', u'קח', u'קום', u'לך', u'צא', u'רוץ', u'זוז', u'שים', u'סע',
    u'רד', u'ספר', u'שמע', u'קרא', u'תן'))

# A bare ת-form is also "she will" ("אולי תוכל" = "maybe she could"); it
# is read as a command only where a command stands -- opening a clause, or
# after one of these.
_LEAD_BEFORE = frozenset((u'אל', u'פשוט', u'רק', u'בבקשה', u'אז', u'עכשיו',
                          u'תמיד', u'לעולם', u'קדימה'))
_CLAUSE = re.compile(u'[.?!,;:\u2026]+')


def _command_words(turn):
    """{word: opens a command} for second-person futures and commands that
    mark a woman with a final י: every ת-word, and each clause's opening
    word (a bare command such as "ספר לי" / "ספרי לי")."""
    nouns = _T_NOUNS | _LEAD_NOUNS
    out = {}
    for clause in _CLAUSE.split(turn):
        words = [_strip_clitic(w) for w in _WORD.findall(clause)]
        for i, w in enumerate(words):
            if w in nouns or (w.endswith(u'י') and w[:-1] in nouns):
                continue
            key = w.translate(_UNFINAL)
            bare = key[:-1] if key.endswith(u'י') else key
            if (len(w) >= 3 and w[0] == u'ת') or (i == 0 and bare in _BARE_IMP):
                out[key] = out.get(key, False) or i == 0 or words[i - 1] in _LEAD_BEFORE
    return out


def _pairs(turn_ai, turn_ref):
    """{role: reference gender} from the human line used as the lexicon: the
    same word after the same person, once with a feminine ת/ה ending and
    once without ("אתה אוהב" / "את אוהבת", "אני מתאמן" / "אני מתאמנת"), or
    the same command with and without the feminine י ("תישאר" / "תישארי").
    An addressee pair after a pronoun needs "אתה" on one side, since a bare
    "את" may be the object marker."""
    out = {}
    commands_ai = _command_words(turn_ai)
    for wa, lead in commands_ai.items():
        for wr in _command_words(turn_ref):
            # "היית" / "הייתי" is you / I, not he / she.
            if wa.endswith(u'ת') or wr.endswith(u'ת'):
                continue
            if wa == wr + u'י':
                out.setdefault('addressee', set()).add('M')
            elif wr == wa + u'י' and lead:
                out.setdefault('addressee', set()).add('F')
    for role, pa, wa in _anchors(turn_ai):
        wa = wa.translate(_UNFINAL)
        for rrole, pr, wr in _anchors(turn_ref):
            wr = wr.translate(_UNFINAL)
            if role != rrole or (role == 'addressee' and u'אתה' not in (pa, pr)):
                continue
            if len(wr) >= 2 and wa in (wr + u'ת', wr + u'ה'):
                out.setdefault(role, set()).add('M')
            elif len(wa) >= 2 and wr in (wa + u'ת', wa + u'ה'):
                out.setdefault(role, set()).add('F')
            elif wa == wr and pa != pr and role == 'addressee':
                # The same words after "אתה" in one line and "את" in the
                # other ("אתה האבא החדש שלי?" / "את האבא החדש שלי?").
                out.setdefault(role, set()).add('M' if pr == u'אתה' else 'F')
    return {role: g.pop() for role, g in out.items() if len(g) == 1}


def _pair_agrees(turn_ai, turn_ref, role):
    """The AI turn now uses the reference's own word for that person: the
    word after the pronoun, or (addressee) the reference's own ת-command."""
    want = set(w.translate(_UNFINAL) for r, _p, w in _anchors(turn_ref) if r == role)
    have = set(w.translate(_UNFINAL) for r, _p, w in _anchors(turn_ai) if r == role)
    if role == 'addressee':
        want |= set(_command_words(turn_ref))
        have |= set(_command_words(turn_ai))
    return bool(want & have)


def _turn_pairs(sa, sr):
    """Turn pairs to compare. Same count: turn by turn. Otherwise every
    combination -- only the pair rule runs on those, and a pair is the same
    word for the same person, which places the human turn by itself
    (measured: "- היא בסדר? / - אני לא יודעת" against one human turn
    "אני לא יודע, תכף נדע")."""
    if len(sa) == len(sr):
        return list(zip(sa, sr)), True
    return [(a, r) for a in sa for r in sr], False


def conflicts(ai_text, ref_text):
    """[(role, ref_gender)] where the AI text contradicts the reference.

    Compared turn by turn when both sides have the same number of turns;
    a single-turn reference is compared against a single-turn AI line only.
    Unknown on either side is never a conflict.
    """
    sa, sr = _segments(ai_text), _segments(ref_text)
    if not sa or not sr:
        return []
    combos, aligned = _turn_pairs(sa, sr)
    out = []
    for turn_a, turn_r in combos:
        ta, tr = _read_turn(turn_a), _read_turn(turn_r)
        for role in ('speaker', 'addressee'):
            if aligned and ta[role] and tr[role] and ta[role] != tr[role]:
                out.append((role, tr[role]))
        mixed = dict(zip(('speaker', 'addressee'), _votes(turn_r)))
        for role, gender in _pairs(turn_a, turn_r).items():
            if aligned and ta[role] and tr[role]:
                continue
            if len(mixed[role] | {gender}) > 1:
                continue          # the human line itself reads both ways
            out.append((role, gender))
    # A role the comparison reads both ways is not evidence.
    roles = [r for r, _g in set(out)]
    return sorted(c for c in set(out) if roles.count(c[0]) == 1)


def fixed(ai_text, wanted, ref_text=None):
    """True when every (role, gender) in `wanted` now reads as that gender
    and nothing reads as the opposite -- the proof a repair must pass.
    With the human reference, a role also counts as proven when the line
    now carries the reference's own word for that person and no pair
    contradicts it."""
    turns = read(ai_text)
    if not turns:
        return False
    pairs_ok = {}
    if ref_text:
        sa, sr = _segments(ai_text), _segments(ref_text)
        if sa and sr:
            combos, _aligned = _turn_pairs(sa, sr)
            for role in ('speaker', 'addressee'):
                pairs_ok[role] = (
                    any(_pair_agrees(a, r, role) for a, r in combos)
                    and not any(role in _pairs(a, r) for a, r in combos))
    for role, gender in wanted:
        seen = [t[role] for t in turns if t[role]]
        if any(g != gender for g in seen):
            return False
        if not seen and not pairs_ok.get(role):
            return False
    return True
