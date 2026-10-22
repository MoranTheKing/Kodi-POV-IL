# -*- coding: utf-8 -*-
"""Extra backstops for the Hebrew gender repair, and the Spanish/Portuguese
addressee reader.

Ported from SRT AI Translator NG (MIT, Akila3 -- see LICENSE.txt), Round 19A:
the repair reply is a single Gemini rewrite of a line the reference says has
the wrong gender. Before it replaces the line it must also

  * not create a "you" that disagrees with its own verb (אתה חושבת, את חושב)
    -- mixed_address();
  * not flip a word on a role nobody asked about (an addressee fix that also
    turned the speaker's "אני מתכוון" into "מתכוונת") -- put_back_unrequested()
    puts such a word back before the other checks run;
  * not bring in a letter of another script or a backslash the line did not
    have ("אה" -> "אه") -- adds_stray_characters();

and a speaker correction is not asked for on a cue where two people speak
(two_speakers()): the speaker read off the whole cue can be the other person.

Everything reads through invisible direction marks (U+202B and friends).
Pure functions, no Kodi imports; never raise.
"""
import re

_HE = u'א-ת'
_DIRECTION_MARKS = re.compile(u'[\u200e\u200f\u202a-\u202e\u2066-\u2069\u061c\ufeff]')


def visible(text):
    """The text without invisible direction marks."""
    return _DIRECTION_MARKS.sub(u'', text or u'')


# ---- the speaker reader's lexicon (only the parts the guards need) --------

_PRESENT_SG = {
    'M': frozenset(u'הולך יכול אומר יודע בא צריך עובד מדבר חושב מרגיש מוכן בטוח עייף גדול קטן '
                   u'שמח מצטער נשאר יושב עומד זוכר מבין מת אוהב חייב נותן לוקח מבקש חוזר קולט '
                   u'מעביר'.split()),
    'F': frozenset(u'הולכת יכולה אומרת יודעת באה צריכה עובדת מדברת חושבת מרגישה מוכנה בטוחה '
                   u'עייפה גדולה קטנה שמחה מצטערת נשארת יושבת עומדת זוכרת מבינה מתה אוהבת חייבת '
                   u'נותנת לוקחת מבקשת חוזרת קולטת מעבירה'.split()),
}
# Final-heh present verbs shared by both genders, and invariant adjectives.
_AMBIGUOUS = frozenset(u'רוצה עושה רואה קונה שותה בונה פונה יפה מחכה מנסה'.split())

_INTENSIFIERS = u'(?:(?:כל\\s+כך|מאוד|ממש|ודאי|בטעות|כבר|עדיין|לא|באמת|פשוט|גם)\\s+){0,3}'
# The feminine predicates of arabic_gender._HE_AT_PREDICATE without the
# forms both genders share (רוצה, יפה, טועה).
_FEM_PREDICATE = frozenset(u'מוכנה מבהילה מפחידה מעמידה יודעת חוזרת צריכה יכולה חייבת בטוחה '
                           u'עייפה צודקת מבינה מקשיבה מדברת הולכת נראית'.split())
# Reviewed second-person feminine futures. A shape test (ת..י) also matches
# masculine words such as תלוי and תורכי, so only listed verbs count.
_2FS_FUTURE = frozenset(u'תוכלי תלכי תגידי תעשי תבואי תראי תהיי תצטרכי תרצי תחזרי תשבי תקחי '
                        u'תתני תשמעי תדברי תחשבי תזכרי תביני תגיעי תישארי תעזבי תאמרי תכתבי '
                        u'תאכלי תשתי תספרי תבקשי תנסי תעזרי תפסיקי תחכי תדאגי תסלחי תשכחי תצאי '
                        u'תיכנסי'.split())
_MASC_THEN_WORD = re.compile(
    u'(?<![' + _HE + u'])(?:ו|ש|כש|וש|וכש)?אתה\\s+' + _INTENSIFIERS + u'([' + _HE + u']+)')
_CLAUSE_FEM_THEN_WORD = re.compile(
    u'(?:(?:^|[.!?\\n,:;\u2014-])\\s*(?:ו)?|(?<![' + _HE + u'])(?:ש|כש|וש|וכש))את\\s+'
    + _INTENSIFIERS + u'([' + _HE + u']+)')
# What makes את an object marker (arabic_gender._HE_AT_OBJ).
_AT_OBJ = re.compile(
    u'\\s+(?:זה|זאת|זו|אלה|אלו|כל(?!\\s+כך)|מה|מי|עצמ|אות|כך|של|'
    u'ה(?!ולכת\\s+(?:בלי|איתי)(?![' + _HE + u']))[' + _HE + u'])')


def _gendered_present(word, gender):
    return word not in _AMBIGUOUS and word in _PRESENT_SG[gender]


def mixed_address(text):
    """True when the line holds a "you" whose own predicate is the other
    gender: אתה חושבת, אתה תוכלי, or a clause את חושב. A repair that creates
    one is ungrammatical whatever the requested role reads."""
    try:
        t = visible(text)
        for m in _MASC_THEN_WORD.finditer(t):
            w = m.group(1)
            if _gendered_present(w, 'F') or w in _FEM_PREDICATE or w in _2FS_FUTURE:
                return True
        for m in _CLAUSE_FEM_THEN_WORD.finditer(t):
            tail = t[m.start() + m.group(0).index(u'את') + 2:]
            if not _AT_OBJ.match(tail) and _gendered_present(m.group(1), 'M'):
                return True
    except Exception:
        pass
    return False


# ---- clause axes and the put-back of unrequested flips ---------------------

_FIRST_PERSON = frozenset((u'אני', u'אנחנו', u'אנו', u'הייתי'))
_OTHER_SUBJECT = frozenset(u'הוא היא הם הן זה זאת זו אחד אחת מישהו מישהי כולם אתה אתם אתן'.split())
_SECOND_PERSON = frozenset((u'אתה', u'את', u'אתם', u'אתן'))
_THIRD_SUBJECT = _OTHER_SUBJECT - _SECOND_PERSON
_PRONOUN_DROPPED = frozenset((u'יודע', u'יודעת', u'מצטער', u'מצטערת'))
_KNOW = frozenset((u'יודע', u'יודעת'))
_WHAT_NEXT = re.compile(u'^\\s*מה(?![' + _HE + u'])')
_COPULA = frozenset((u'הוא', u'היא', u'זה', u'זו', u'זאת'))
_SUBJECT_PROCLITIC = re.compile(u'^(?:וכש|כש|וש|ש|ו)')
# A Hebrew word, an ellipsis, a clause end, a dialogue dash at a line start, or a comma.
_CLAUSE_TOKENS = re.compile(u"[" + _HE + u"\u05f3\u05f4']+|\\.{2,}|\u2026|[.!?;:]|(?:^|\\n)[ \\t]*-|,")


def clause_words(text):
    """[(word, offset, axis)] for every Hebrew word of a line: whose clause
    it is in -- 'speaker' ("I ..."), 'addressee' ("you ...") or None. Offsets
    index the text as given (direction marks are not tokens)."""
    t = text or u''
    words = []
    open_axis = None
    sentence_start = True
    after_anchor = False
    for m in _CLAUSE_TOKENS.finditer(t):
        tok = m.group(0)
        at = m.start()
        if tok == u'\u2026' or tok.startswith(u'..'):
            continue
        if tok == u',':
            after_anchor = False
            continue
        if not (u'א' <= tok[0] <= u'ת'):
            open_axis = None
            sentence_start = True
            after_anchor = False
            continue
        bare = _SUBJECT_PROCLITIC.sub(u'', tok)
        dropped = sentence_start and tok in _PRONOUN_DROPPED
        sentence_start = sentence_start and tok == u'לא'
        if tok in _FIRST_PERSON or bare in _FIRST_PERSON:
            open_axis = 'speaker'
            after_anchor = True
            words.append((tok, at, None))
        elif after_anchor and tok in _COPULA:
            words.append((tok, at, None))
        elif bare in _SECOND_PERSON and not (
                bare == u'את' and _AT_OBJ.match(visible(t[at + len(tok):]))):
            open_axis = 'addressee'
            after_anchor = False
            words.append((tok, at, 'addressee'))
        elif tok in _THIRD_SUBJECT or bare in _THIRD_SUBJECT:
            open_axis = None
            after_anchor = False
            words.append((tok, at, None))
        else:
            after_anchor = False
            if dropped and tok in _KNOW and _WHAT_NEXT.match(visible(t[at + len(tok):])):
                words.append((tok, at, 'addressee'))   # "יודעת מה? ..." = you know what
            else:
                words.append((tok, at, 'speaker' if dropped else open_axis))
    return words


_FINALS = {u'ך': u'כ', u'ם': u'מ', u'ן': u'נ', u'ף': u'פ', u'ץ': u'צ'}
_SECOND_PERSON_PRONOUN = re.compile(u'^(?:ו|ש|כש|וש|וכש)?(?:אתה|את)$')
_SON_DAUGHTER = re.compile(u'^(?:ו|ש|ה|וה|כש)?(?:בן|בת)$')


def _normal_final(word):
    return u''.join(_FINALS.get(c, c) for c in word)


def _flip_axis(a, b, clause):
    """The role a one-word gender change belongs to; '' when the change is not
    a gender flip. A +י form and the pronoun itself are the addressee's;
    anything else takes the role of the clause it is in (None: no clause)."""
    def proclitic(w):
        return re.sub(u'(?:אתה|את)$', u'', w)
    if (_SECOND_PERSON_PRONOUN.match(a) and _SECOND_PERSON_PRONOUN.match(b)
            and proclitic(a) == proclitic(b)):
        return 'addressee'
    if _SON_DAUGHTER.match(a) and _SON_DAUGHTER.match(b) and a[:-2] == b[:-2]:
        return clause
    x, y = _normal_final(a), _normal_final(b)
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    if long_.startswith(short):
        tail = long_[len(short):]
        if tail == u'י':
            return 'addressee'
        if tail in (u'ת', u'ה', u'ית'):
            return clause
    if (len(x) == len(y) and x[:-2] == y[:-2]
            and sorted((x[-2:], y[-2:])) == [u'ות', u'ימ']):
        return clause
    return ''


def put_back_unrequested(old_body, body, requested_roles):
    """(body, count): every one-word gender flip on a role the cue did not ask
    for is put back to the old word. Compared word by word; when the Hebrew
    word counts differ nothing is put back and the other checks decide."""
    try:
        before = clause_words(old_body)
        after = clause_words(body)
        if len(before) != len(after):
            return body, 0
        text = body
        count = 0
        for i in range(len(after) - 1, -1, -1):
            o_word, _o_at, o_axis = before[i]
            n_word, n_at, n_axis = after[i]
            if o_word == n_word:
                continue
            axis = _flip_axis(o_word, n_word, o_axis or n_axis)
            if not axis or axis in requested_roles:
                continue
            text = text[:n_at] + o_word + text[n_at + len(n_word):]
            count += 1
        return (text, count) if count else (body, 0)
    except Exception:
        return body, 0


def _foreign_letters(text):
    return set(c for c in text if c.isalpha() and not (u'\u0590' <= c <= u'\u05ff'))


def adds_stray_characters(old_body, body):
    """A letter of another script the old line did not hold, or an added
    backslash."""
    try:
        if _foreign_letters(body) - _foreign_letters(old_body):
            return True
        return body.count(u'\\') > old_body.count(u'\\')
    except Exception:
        return False


# A dialogue dash that opens a later speaker: at the start of any line but the
# first, or after a sentence end on the same line.
_LATER_SPEAKER = re.compile(
    u'\\n[ \\t]*(?:<[^>\\n]*>[ \\t]*)*[-\u2010\u2011\u2013\u2014][ \\t]*\\S'
    u'|[.!?\u2026]["\'\u201d\u2019)\\]]*(?:<[^>\\n]*>)*[ \\t]+[-\u2010\u2011\u2013\u2014][ \\t]+\\S')


def two_speakers(text):
    """True when a second person speaks in the cue."""
    try:
        return bool(_LATER_SPEAKER.search(visible(text).replace(u'\r\n', u'\n').strip()))
    except Exception:
        return False


# ---- the whole vetting of one repair reply ---------------------------------

# Negation (with attached conjunctions) and numbers: a gender change never
# touches them (translate.py's repair, unchanged).
_INVARIANT = re.compile(u'(?<![א-ת])(?:ו?(?:ש|כש)?(?:לא|אין|אל)|ו?ללא|ו?בלי)(?![א-ת])|[0-9]+')


def vet_repair(old_lines, new_lines, roles, proven, looks_hebrew):
    """(lines, '') when a repair reply may replace the old cue text, else
    (None, reason). reason: 'unchanged' | 'unrequested' | 'unproven' |
    'not_hebrew' | 'shape' | 'similarity' | 'invariant' | 'stray' | 'mixed'.

    old_lines / new_lines: the non-empty text lines. roles: [(role, 'F'|'M')]
    asked for. proven(body) -> bool is the person-gender proof
    (arabic_gender.person_roles_fixed); looks_hebrew(body) -> bool is
    srt.looks_hebrew(body, min_alpha=1).
    """
    from difflib import SequenceMatcher
    old_body = u'\n'.join(old_lines)
    # A model-escaped quote is a quote, unless the line really had backslashes.
    if u'\\' not in old_body:
        new_lines = [l.replace(u'\\"', u'"') for l in new_lines]
    body = u'\n'.join(new_lines).strip()
    if not body:
        return None, 'unproven'
    # A flip on a role nobody asked about goes back before anything is judged.
    body, put_back = put_back_unrequested(old_body, body, set(r for r, _g in roles))
    if put_back:
        if visible(body) == visible(old_body):
            return None, 'unrequested'
        new_lines = [l for l in body.split(u'\n') if l.strip()]
        body = u'\n'.join(new_lines).strip()
    if body == old_body.strip():
        return None, 'unchanged'
    if not proven(body):
        return None, 'unproven'
    # Explicit Hebrew characters, not looks_hebrew alone: that one counts only
    # Hebrew and Latin, so an Arabic reply would read as "too little to judge".
    if not any(u'֐' <= c <= u'׿' for c in body) or not looks_hebrew(body):
        return None, 'not_hebrew'
    if len(new_lines) != len(old_lines):
        return None, 'shape'
    if SequenceMatcher(None, old_body, body, autojunk=False).ratio() < 0.60:
        return None, 'similarity'
    if _INVARIANT.findall(old_body) != _INVARIANT.findall(body):
        return None, 'invariant'
    if adds_stray_characters(old_body, body):
        return None, 'stray'
    if mixed_address(body) and not mixed_address(old_body):
        return None, 'mixed'
    return new_lines, ''


# ---- Method B: a blind classifier for lines the readers cannot read --------

# NG's Feature 17 Method B prompt, verbatim. It sees only the Hebrew lines,
# never the reference; its labels that contradict the reference go through
# the same guarded repair.
CLASSIFIER_PROMPT = (
    'You are a Hebrew grammar analyst. For each Hebrew subtitle line determine, on two\n'
    'independent axes, the grammatical gender expressed:\n'
    '- "speaker": 1st-person gender from verb/adjective forms (M/F/NA)\n'
    '- "addressee": 2nd-person gender from pronouns/verbs (M/F/NA)\n'
    'Judge EACH line independently. Use NA when no gender-bearing form is present on that axis.\n'
    'For plural or mixed-gender "you", use NA (only M, F, or NA are allowed - never other labels).\n'
    'Return ONLY valid JSON, no prose, no code fences:\n'
    '{"lines":[{"i":<index>,"speaker":"M|F|NA","addressee":"M|F|NA"}...]} for EVERY index.\n'
    '\n'
    'Lines (index<TAB>Hebrew):\n')


def classifier_prompt(lines):
    """lines: [(number, hebrew text)] -> the request, or '' when empty. A
    multi-line cue is sent on one line (' / ' between its lines)."""
    rows = []
    for num, text in lines:
        flat = u' / '.join(l.strip() for l in visible(text).split(u'\n') if l.strip())
        if flat:
            rows.append(u'%d\t%s' % (num, flat))
    return CLASSIFIER_PROMPT + u'\n'.join(rows) if rows else u''


def _first_json_object(text):
    import json
    t = (text or u'').strip()
    if t.startswith(u'```'):
        t = re.sub(u'^```(?:json)?\\s*', u'', t, flags=re.I)
        t = re.sub(u'\\s*```$', u'', t)
    start = t.find(u'{')
    if start < 0:
        raise ValueError('no JSON object')
    depth, in_str, esc = 0, False, False
    for p in range(start, len(t)):
        ch = t[p]
        if in_str:
            if esc:
                esc = False
            elif ch == u'\\':
                esc = True
            elif ch == u'"':
                in_str = False
        elif ch == u'"':
            in_str = True
        elif ch == u'{':
            depth += 1
        elif ch == u'}':
            depth -= 1
            if depth == 0:
                return json.loads(t[start:p + 1])
    raise ValueError('unbalanced JSON object')


_SRT_ENTRY_RE = re.compile(
    u'^\\s*(\\d+)\\s*\\n\\s*\\d{1,2}:\\d{2}:\\d{2}[,.]\\d{1,3}\\s*-->\\s*'
    u'\\d{1,2}:\\d{2}:\\d{2}[,.]\\d{1,3}[^\\n]*\\n(.+)$', re.S)
_JSON_TEXT_KEYS = (u'corrected_hebrew', u'hebrew', u'text', u'current_hebrew',
                   u'new_hebrew', u'corrected', u'output', u'he')


def _json_values(text):
    """Every JSON value the reply holds: one fenced or bare array/object, or
    several fenced blocks. [] when there is none."""
    import json
    found = []
    t = (text or u'').strip()
    for body in (re.findall(u'```(?:json)?[ \\t]*\\r?\\n(.*?)```', t, flags=re.I | re.S) or [t]):
        body = body.strip()
        start = min([i for i in (body.find(u'['), body.find(u'{')) if i >= 0] or [-1])
        if start < 0:
            continue
        try:
            found.append(json.JSONDecoder().raw_decode(body[start:])[0])
        except ValueError:
            continue
    return found


def reply_entries(text):
    """SRT entries ("index\\ntimecode\\ntext") in a gender-repair reply.

    The request asks for SRT entries but carries its evidence as JSON, and
    flash-lite sometimes answers in that JSON shape instead: NG measured 3 of
    ~22 repair replies lost to it ("JSON repair parsing was mandatory for
    Flash-Lite", gender-reference 7.2), and a QA run here lost all 15 entries
    of one title twice over ("answered none"). A plain SRT reply is read as
    before. Only when it holds no numbered entry is it read as JSON: a string
    that is itself a whole SRT entry, or an object with an integer index and
    one text field. Everything still goes through vet_repair, so a misread
    answer can only be refused, never applied blindly."""
    blocks = [b for b in _parse_srt_blocks(text) if b.split(u'\n', 1)[0].strip().isdigit()]
    if blocks:
        return blocks
    out = []

    def walk(value):
        if isinstance(value, str):
            m = _SRT_ENTRY_RE.match(value.replace(u'\r\n', u'\n'))
            if m:
                out.append(value.replace(u'\r\n', u'\n').strip())
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            index = value.get(u'index', value.get(u'id', value.get(u'num')))
            texts = [value.get(k) for k in _JSON_TEXT_KEYS if isinstance(value.get(k), str)]
            if isinstance(index, (int, str)) and str(index).strip().isdigit() and texts:
                body = texts[0].replace(u'\r\n', u'\n').strip()
                m = _SRT_ENTRY_RE.match(body)
                if m:
                    if int(m.group(1)) == int(str(index).strip()):
                        out.append(body)
                    return
                if body:
                    out.append(u'%d\n00:00:00,000 --> 00:00:00,000\n%s' % (int(str(index).strip()), body))
                return
            for item in value.values():
                walk(item)
    for value in _json_values(text):
        walk(value)
    return out


def _parse_srt_blocks(text):
    """The same split srt.parse_blocks does, without importing it here."""
    t = (text or u'').replace(u'\r\n', u'\n').strip()
    return [b.strip(u'\n') for b in re.split(u'\n\\s*\n', t) if b.strip()]


def parse_classifier(reply, asked):
    """{number: {'speaker': 'M'|'F'|None, 'addressee': ...}} for every number
    in `asked`, or None when the reply is malformed or leaves one out -- then
    the classifier abstains whole."""
    try:
        rows = _first_json_object(reply).get('lines')
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    asked = set(asked)
    out = {}

    def label(v):
        s = (u'%s' % (v if v is not None else u'NA')).strip().upper()
        return s if s in (u'M', u'F') else None
    for row in rows:
        if not isinstance(row, dict):
            continue
        i = row.get('i')
        if isinstance(i, str) and i.strip().isdigit():
            i = int(i.strip())
        if not isinstance(i, int) or isinstance(i, bool) or i not in asked or i in out:
            continue
        out[i] = {'speaker': label(row.get('speaker')), 'addressee': label(row.get('addressee'))}
    return out if len(out) == len(asked) else None


# ---- Spanish / Portuguese addressee (a short reviewed predicate list) ------

_ES_FORMS = {
    'F': frozenset(u'cansada preparada lista segura loca equivocada preocupada asustada sola casada '
                   u'enamorada muerta viva ocupada'.split()),
    'M': frozenset(u'cansado preparado listo seguro loco equivocado preocupado asustado casado '
                   u'enamorado muerto vivo ocupado'.split()),
}
_PT_FORMS = {
    'F': frozenset(u'cansada pronta certa errada preocupada assustada sozinha casada apaixonada morta '
                   u'viva ocupada louca obrigada'.split()),
    'M': frozenset(u'cansado pronto certo errado preocupado assustado sozinho casado apaixonado morto '
                   u'vivo ocupado louco obrigado'.split()),
}
_ES_PREDICATE = re.compile(
    u'(?<!\\w)(?:(?:tú|vos)\\s+)?(?:estás|eres|pareces|te\\s+sientes)\\s+'
    u'(?:(?:muy|tan|bastante|realmente)\\s+)?(\\w+)(?!\\w)', re.I | re.U)
_PT_PREDICATE = re.compile(
    u'(?<!\\w)(?:(?:você)\\s+(?:está|é|parece|se\\s+sente)|(?:tu\\s+)?(?:estás|és|pareces|te\\s+sentes))\\s+'
    u'(?:(?:muito|tão|bastante|realmente)\\s+)?(\\w+)(?!\\w)', re.I | re.U)


def romance_addressee(text, lang):
    """'F'/'M' from a second-person predicate adjective in a Spanish ('es') or
    Portuguese ('pt') line, from a short reviewed list; None otherwise (also
    when both genders appear). "eres una estrella" reads nothing: only the
    listed adjectives right after the verb count."""
    try:
        matcher, forms = (_ES_PREDICATE, _ES_FORMS) if lang == 'es' else (
            (_PT_PREDICATE, _PT_FORMS) if lang == 'pt' else (None, None))
        if matcher is None:
            return None
        votes = set()
        for m in matcher.finditer(visible(text)):
            word = m.group(1).lower()
            for g in ('F', 'M'):
                if word in forms[g]:
                    votes.add(g)
        return votes.pop() if len(votes) == 1 else None
    except Exception:
        return None
