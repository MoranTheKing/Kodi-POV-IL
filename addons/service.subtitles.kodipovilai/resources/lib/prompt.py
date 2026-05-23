# The translation prompt. Centralised here so we can iterate on it
# without touching the orchestration code.
#
# The cast block is the secret sauce: Hebrew has heavy gendering on
# verbs/adjectives and the AI needs to know who's speaking and who
# they're addressing to pick the right form.

LANG_NAME = {
    'en': 'English',
    'es': 'Spanish',
    'fr': 'French',
    'de': 'German',
    'pt': 'Portuguese',
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
        'or plural-form phrasing over guessing wrong.\n\n'
        'OTHER TRANSLATION RULES:\n'
        '1. Use natural conversational Hebrew. Idioms should sound '
        'native, not literal.\n'
        '2. Keep HTML tags like <i></i> intact.\n'
        '3. Do NOT add hearing-impaired annotations like [breathing], '
        '(music playing), {{chuckles}}, or ALL-CAPS speaker prefixes '
        'like "MABEL: ". If the source contains any, drop them in the '
        'translation.\n'
        '4. Output ONLY the SRT content. No commentary, no preface, no '
        'closing remarks.\n\n'
        'SRT to translate ({entry_count} entries):\n\n'
        '{{chunk}}\n'
    ).format(src=src_name, ctx=context_line, cast=cast_block,
             entry_count='{entry_count}')
