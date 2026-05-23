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
        'CRITICAL RULES:\n'
        '1. Match Hebrew gender forms to BOTH the speaker AND the '
        'addressee:\n'
        '   - 1st person verbs/adjectives ("I am tired") -> speaker\'s gender\n'
        '   - 2nd person ("you should") -> the addressee\'s gender\n'
        '   - Pronouns like "her"/"him" -> the referent\'s gender\n'
        '2. Infer speaker from context: reply patterns, named addressees, '
        'scene continuity.\n'
        '3. Use natural conversational Hebrew. Idioms should sound native, '
        'not literal.\n'
        '4. Preserve timecodes EXACTLY as in source. Do NOT change '
        'subtitle numbers.\n'
        '5. Keep HTML tags like <i></i> intact.\n'
        '6. When truly ambiguous about gender, prefer the neutral/plural '
        'form over guessing.\n'
        '7. Output ONLY the SRT content. No commentary, no preface.\n\n'
        'SRT to translate:\n\n'
        '{{chunk}}\n'
    ).format(src=src_name, ctx=context_line, cast=cast_block)
