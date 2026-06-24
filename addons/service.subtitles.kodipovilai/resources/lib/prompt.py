# The translation prompt. Centralised here so we can iterate on it
# without touching the orchestration code.
#
# The cast block is the secret sauce: Hebrew has heavy gendering on
# verbs/adjectives and the AI needs to know who's speaking and who
# they're addressing to pick the right form.

LANG_NAME = {
    'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
    'pt': 'Portuguese', 'it': 'Italian', 'ru': 'Russian', 'ar': 'Arabic',
    'tr': 'Turkish', 'pl': 'Polish', 'nl': 'Dutch', 'el': 'Greek',
    'fa': 'Persian', 'hi': 'Hindi', 'ja': 'Japanese', 'ko': 'Korean',
    'zh': 'Chinese', 'cs': 'Czech', 'ro': 'Romanian', 'sv': 'Swedish',
    'da': 'Danish', 'fi': 'Finnish', 'no': 'Norwegian', 'hu': 'Hungarian',
    'uk': 'Ukrainian', 'bg': 'Bulgarian', 'hr': 'Croatian', 'sr': 'Serbian',
    'th': 'Thai', 'id': 'Indonesian', 'vi': 'Vietnamese',
}


def build(source_lang, title, year, cast, is_episode=False,
          tvshow='', season='', episode=''):
    """Return the system+user prompt as a single string."""

    src_name = LANG_NAME.get(source_lang, source_lang or 'English')

    if is_episode and tvshow:
        context_line = '"{0}", Season {1} Episode {2}'.format(
            tvshow, season or '?', episode or '?')
        if title:
            context_line += ' ("{0}")'.format(title)
        if year:
            context_line += ' ({0})'.format(year)
    elif title:
        context_line = '"{0}"'.format(title)
        if year:
            context_line += ' ({0})'.format(year)
    else:
        context_line = 'an unknown title'

    if cast:
        lines = []
        for c in cast:
            name = c.get('name') or ''
            char = c.get('character') or ''
            gender = c.get('gender') or 'unknown'
            if not name and not char:
                continue
            if char and gender in ('male', 'female'):
                lines.append('- {0} ({1}, played by {2})'.format(char, gender, name))
            elif char:
                lines.append('- {0} (gender unknown, played by {1})'.format(char, name))
            elif gender in ('male', 'female'):
                lines.append('- {0} ({1})'.format(name, gender))
            else:
                lines.append('- {0}'.format(name))
        cast_block = (
            'Cast (use these to choose correct Hebrew gender forms):\n'
            + '\n'.join(lines)
        )
    else:
        cast_block = (
            'Cast information was not available. Infer character '
            'gender from dialogue context (names, pronouns, replies). '
            'When ambiguous, prefer the neutral or plural form.'
        )

    return (
        'You are a professional subtitle translator for Hebrew. Translate '
        'the following {src} subtitles to Hebrew.\n\n'
        'Context: {ctx}\n\n'
        '{cast}\n\n'
        'CRITICAL OUTPUT INVARIANTS (read before anything else):\n'
        '- The output MUST contain EXACTLY the same number of subtitle '
        'entries as the input, in the SAME ORDER.\n'
        '- Every input entry number must appear EXACTLY ONCE in the '
        'output. No skipping, no duplicating, no merging.\n'
        '- Every input timecode line ("HH:MM:SS,mmm --> HH:MM:SS,mmm") '
        'must appear in the output EXACTLY as written. Do not change '
        'them by a single character.\n'
        '- The TEXT inside an entry is the only thing you change. If '
        'an input entry has 1 text line, your output entry should have '
        '1 text line; if 2 lines, 2 lines.\n'
        '- Preserve the physical text-line order inside each entry: '
        'line 1 stays line 1, line 2 stays line 2. Do not swap stacked '
        'dialogue lines.\n'
        '- Each output entry separated from the next by a single blank '
        'line. Standard SRT shape.\n\n'
        'GENDER AGREEMENT (most important translation rule -- Hebrew '
        'is heavily gendered and getting this wrong is the #1 quality '
        'complaint):\n'
        '- Before translating each line, identify (a) who is speaking '
        'and (b) who they are addressing. Use the cast block above, '
        'the surrounding lines (reply patterns, named addressees, '
        'scene continuity), and any name/pronoun cues to decide.\n'
        '- Then pick the Hebrew form that matches:\n'
        '    * 1st person ("I am tired", "I went") -> SPEAKER gender.\n'
        '      Male speaker: "אני עייף", "אני הלכתי".\n'
        '      Female speaker: "אני עייפה", "אני הלכתי" (same past '
        'tense form, but adjectives differ -- "עייפה" not "עייף").\n'
        '    * 2nd person ("you are", "you should") -> ADDRESSEE gender.\n'
        '      Speaking to a man: "אתה צודק", "אתה רוצה".\n'
        '      Speaking to a woman: "את צודקת", "את רוצה".\n'
        '      Speaking to a group: "אתם" / "אתן".\n'
        '    * 3rd person ("he/she/they", "him/her") -> REFERENT gender.\n'
        '      About a man: "הוא הלך", "ראיתי אותו".\n'
        '      About a woman: "היא הלכה", "ראיתי אותה".\n'
        '- Possessives and adjectives describing a person also inflect '
        'for that person\'s gender: "אבא שלך" / "אמא שלך" (your dad / '
        'your mom). "החבר שלי" (male friend) vs "החברה שלי" (female '
        'friend).\n'
        '- DOUBLE-CHECK every verb, adjective, pronoun and possessive '
        'before finalising the entry. If the same character continues '
        'speaking across multiple entries, KEEP the gender consistent '
        '-- don\'t switch mid-scene.\n'
        '- Only when the speaker / addressee is genuinely unknowable '
        'from context AND the cast block (very rare), prefer a neutral '
        'or plural-form phrasing over guessing wrong. (Better still, '
        'restructure the sentence to avoid the gendered form entirely '
        'rather than guess.)\n'
        '- SPEAKER-PREFIX HINT (use this -- do NOT just drop it as I '
        'used to instruct): if a line starts with an ALL-CAPS speaker '
        'tag like "MABEL:" or "JOHN-PAUL:" or "DR. SMITH:", that is '
        'the explicit speaker. Match the name (case-insensitively) '
        'against the cast block above; if you find them, use their '
        'gender for first-person forms in that line AND for context '
        'when the next reply addresses them. THEN drop the tag from '
        'your Hebrew output (do not translate the prefix itself). If '
        'the prefix names a character NOT in the cast block, still '
        'use it as a consistent speaker identifier across the chunk -- '
        'pick a gender from contextual cues on first encounter, then '
        'keep it.\n'
        '- REPLY HEURISTIC: in two-character dialogue, a short line '
        '(typically 1-5 words, often a confirmation / denial / '
        'rhetorical question like "Right.", "No way.", "You sure?", '
        '"I told you.") that immediately follows another line is most '
        'likely a REPLY from the OTHER person. Speakers ALTERNATE '
        'unless context says otherwise. Apply the alternation rule '
        'before falling back to "guess gender from cast".\n\n'
        'PUNCTUATION POSITION (critical for RTL rendering):\n'
        '- In the SOURCE TEXT you write, punctuation that belongs at '
        'the end of a Hebrew sentence (period, question mark, '
        'exclamation mark, comma, colon, semicolon, ellipsis) MUST be '
        'placed AFTER the last Hebrew word, not before the first one.\n'
        '- Correct:   "מה שלומך?"   Wrong: "?מה שלומך"\n'
        '- Correct:   "אני בא, חכה."   Wrong: ".אני בא, חכה"\n'
        '- Correct:   "באמת!"   Wrong: "!באמת"\n'
        '- Even though Hebrew RENDERS right-to-left on screen, in the '
        'plain-text representation you produce, the punctuation goes '
        'AFTER the Hebrew word in the source-order sequence. Kodi\'s '
        'subtitle renderer will then position it correctly on screen.\n'
        '- This applies to every sentence and every sub-clause. A '
        'common AI failure mode is to put the punctuation at the '
        'logical start; do NOT do that.\n'
        '- Quotation marks: wrap quoted speech with regular " on both '
        'ends, opening before the quoted phrase and closing after it: '
        '"אמרתי \\"שלום\\" וזזתי" (the inner content stays as-is).\n\n'
        'OTHER TRANSLATION RULES:\n'
        '1. Use natural conversational Hebrew. Idioms should sound '
        'native, not literal.\n'
        '2. Keep HTML tags like <i></i> intact.\n'
        '3. Do NOT add hearing-impaired annotations like [breathing], '
        '(music playing), {{chuckles}}, or [BACKGROUND NOISE]. Drop '
        'them in the Hebrew output. (NOTE: ALL-CAPS speaker prefixes '
        '"NAME:" are handled by the SPEAKER-PREFIX HINT rule above -- '
        'USE them for gender inference, then drop only the prefix '
        'from the output.)\n'
        '4. Output ONLY the SRT content. No commentary, no preface, no '
        'closing remarks.\n\n'
        '{{prev_context_block}}'
        'SRT to translate ({entry_count} entries):\n\n'
        '{{chunk}}\n'
    ).format(src=src_name, ctx=context_line, cast=cast_block,
             entry_count='{entry_count}')


def build_prev_context_block(prev_context_lines):
    """Format the cross-chunk continuity block. `prev_context_lines`
    is a list of strings -- the dialogue text from the last few
    entries of the PREVIOUS chunk. Returns the prompt section as a
    string, or '' for the first chunk (no previous context).

    Keeping this as a helper rather than building inline so the
    string formatting stays out of the chunk-dispatch hot path in
    translate.py.
    """
    if not prev_context_lines:
        return ''
    body = '\n'.join('   ' + ln for ln in prev_context_lines
                     if ln and ln.strip())
    if not body.strip():
        return ''
    return (
        'PREVIOUS DIALOGUE CONTEXT (for continuity only -- ALREADY '
        'translated in a previous chunk; DO NOT include these in '
        'your output, just use them to remember who was just '
        'speaking and which gender forms apply):\n'
        + body + '\n\n'
    )


def build_arabic_gender_block(entry_arabic):
    """Build the Arabic gender-reference block (opt-in feature). `entry_arabic`
    is a list of (entry_number, arabic_text) for THIS chunk -- the time-aligned
    line from a HUMAN Arabic translation of the same scene. Arabic marks gender
    (أنتَ/أنتِ, gendered verbs/imperatives) almost 1:1 with Hebrew, so it pins
    down per-line speaker/addressee gender that English can't. Returns '' when
    no entry has a usable Arabic line.

    Validated: lifts gender accuracy ~27% (cast-only) -> ~90%+, zero regressions,
    while the FIDELITY clause keeps wording faithful to the English."""
    rows = [(n, t) for (n, t) in entry_arabic if t and t.strip()]
    if not rows:
        return ''
    body = '\n'.join('{0}: {1}'.format(n, t) for (n, t) in rows)
    return (
        'ARABIC GENDER REFERENCE -- HARD CONSTRAINT, NOT A HINT.\n'
        'For some entries below, the line from a PROFESSIONAL HUMAN Arabic '
        'translation of the SAME scene is given. Arabic, like Hebrew, '
        'explicitly marks the gender of the ADDRESSEE and the SPEAKER. For each '
        'such entry you MUST make the Hebrew agree in gender with its Arabic. '
        'Do NOT default to masculine -- read the markers and match them:\n'
        '- ADDRESSEE FEMININE when the Arabic has أنتِ , a ـكِ ending, a present '
        'verb ending ـين (تحاولين/تفعلين), or a feminine imperative ending ـي '
        '(اسمعي، دعيني، أغلقي، ابتعدي) -> Hebrew feminine: את / תקשיבי / תני.\n'
        '- ADDRESSEE MASCULINE when the Arabic has أنتَ , a ـكَ ending, a present '
        'verb without ـين (تعرف/تحاول), or a masculine imperative (اسمع، دع، '
        'أغلق، ابتعد) -> Hebrew masculine: אתה / תקשיב / תן.\n'
        '- SPEAKER FEMININE when the Arabic 1st-person adjective is feminine '
        '(محظوظة، ناضجة، متأكدة) -> Hebrew feminine 1st person (אני בטוחה).\n'
        '- Entry not listed / Arabic gender-neutral -> use the cast block + '
        'context instead.\n'
        'FIDELITY (critical): translate the ENGLISH faithfully, in natural '
        'Hebrew. The Arabic is ONLY a gender oracle -- do NOT let it affect your '
        'word choice, phrasing, idioms, length, register or meaning. If the '
        'Arabic paraphrases or differs from the English, IGNORE that and follow '
        'the English. Borrow from the Arabic NOTHING except grammatical gender.\n'
        'Per-entry Arabic (entry_number: arabic_line):\n'
        + body + '\n\n'
    )
