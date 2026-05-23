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
        'TRANSLATION RULES:\n'
        '1. Match Hebrew gender forms to BOTH the speaker AND the '
        'addressee:\n'
        '   - 1st person verbs/adjectives ("I am tired") -> speaker\n'
        '   - 2nd person ("you should") -> the addressee\n'
        '   - Pronouns like "her"/"him" -> the referent\n'
        '2. Infer speaker from context: reply patterns, named '
        'addressees, scene continuity.\n'
        '3. Use natural conversational Hebrew. Idioms should sound '
        'native, not literal.\n'
        '4. Keep HTML tags like <i></i> intact.\n'
        '5. When truly ambiguous about gender, prefer neutral / plural '
        'forms over guessing.\n'
        '6. Do NOT add hearing-impaired annotations like [breathing], '
        '(music playing), {{chuckles}}, or ALL-CAPS speaker prefixes '
        'like "MABEL: ". If the source contains any, drop them in the '
        'translation.\n'
        '7. Output ONLY the SRT content. No commentary, no preface, no '
        'closing remarks.\n\n'
        'SRT to translate ({entry_count} entries):\n\n'
        '{{chunk}}\n'
    ).format(src=src_name, ctx=context_line, cast=cast_block,
             entry_count='{entry_count}')
