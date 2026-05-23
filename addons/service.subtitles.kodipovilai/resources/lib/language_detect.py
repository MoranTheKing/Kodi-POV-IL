# Best-effort language detection for SRT files we find on disk.
# Used when filename hints (foo.en.srt etc.) aren't available.
#
# Strategy: tally letters in known scripts. Hebrew is unambiguous
# from any Latin language, and within Latin scripts a small
# stopword count is enough for English vs Spanish/French/German.
#
# We don't pull in langdetect/cld3 -- bundling a wheel into a
# subtitle addon is overkill for this. ~90% accuracy on first
# 50 lines of an SRT is plenty for "skip if already Hebrew".

import re

HEBREW_RANGE = ('֐', '׿')
ARABIC_RANGE = ('؀', 'ۿ')
CYRILLIC_RANGE = ('Ѐ', 'ӿ')

EN_HINTS = {' the ', ' and ', ' you ', ' that ', ' have ', ' for ', ' not ', " 'll ", " 're ", ' to '}
ES_HINTS = {' que ', ' los ', ' las ', ' una ', ' por ', ' con ', ' para ', ' como ', ' está '}
FR_HINTS = {' que ', ' les ', ' une ', ' des ', ' est ', ' pas ', ' pour ', ' avec ', ' dans '}
DE_HINTS = {' der ', ' die ', ' und ', ' ich ', ' nicht ', ' ist ', ' das ', ' sie ', ' eine '}
PT_HINTS = {' que ', ' não ', ' uma ', ' você ', ' para ', ' está ', ' como ', ' são ', ' mas '}

TIMECODE_RE = re.compile(r'^\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}\s*$')
INDEX_RE    = re.compile(r'^\d{1,5}\s*$')


def _strip_to_text(srt_text, max_chars=4000):
    """Drop SRT index lines + timecodes, return the dialogue text
    (capped to avoid scanning megabyte-sized files)."""
    out = []
    for line in srt_text.splitlines():
        s = line.strip()
        if not s or INDEX_RE.match(s) or TIMECODE_RE.match(s):
            continue
        out.append(s)
        if sum(len(x) for x in out) >= max_chars:
            break
    return ' ' + ' '.join(out).lower() + ' '


def detect(srt_text):
    """Return one of: 'he', 'en', 'es', 'fr', 'de', 'pt', or '' (unknown)."""
    if not srt_text:
        return ''

    sample = srt_text[:8000]
    he_count = sum(1 for ch in sample if HEBREW_RANGE[0] <= ch <= HEBREW_RANGE[1])
    ar_count = sum(1 for ch in sample if ARABIC_RANGE[0] <= ch <= ARABIC_RANGE[1])
    cy_count = sum(1 for ch in sample if CYRILLIC_RANGE[0] <= ch <= CYRILLIC_RANGE[1])
    latin_count = sum(1 for ch in sample if ch.isalpha() and ord(ch) < 128)

    if he_count > 30:
        return 'he'
    if ar_count > 30:
        return 'ar'
    if cy_count > 30:
        return 'ru'
    if latin_count < 30:
        return ''  # not enough to decide

    text = _strip_to_text(srt_text)
    scores = {
        'en': sum(1 for s in EN_HINTS if s in text),
        'es': sum(1 for s in ES_HINTS if s in text),
        'fr': sum(1 for s in FR_HINTS if s in text),
        'de': sum(1 for s in DE_HINTS if s in text),
        'pt': sum(1 for s in PT_HINTS if s in text),
    }
    best_lang, best_score = max(scores.items(), key=lambda kv: kv[1])
    # Require a minimum signal so we don't false-positive on a
    # short SRT that happens to contain " que " etc.
    if best_score < 2:
        return 'en' if scores['en'] >= 1 else ''
    return best_lang


def from_filename(path):
    """Detect language from the SRT filename's standard suffix.
    e.g.  Movie.en.srt -> 'en',  Movie.heb.srt -> 'he'."""
    if not path:
        return ''
    name = path.rsplit('/', 1)[-1].rsplit('\\', 1)[-1].lower()
    name = name.rsplit('.srt', 1)[0]
    # tail token after the last dot
    if '.' not in name:
        return ''
    tail = name.rsplit('.', 1)[-1]
    mapping = {
        'en': 'en', 'eng': 'en', 'english': 'en',
        'he': 'he', 'heb': 'he', 'hebrew': 'he', 'iw': 'he',
        'es': 'es', 'esp': 'es', 'spa': 'es', 'spanish': 'es',
        'fr': 'fr', 'fre': 'fr', 'fra': 'fr', 'french': 'fr',
        'de': 'de', 'ger': 'de', 'deu': 'de', 'german': 'de',
        'pt': 'pt', 'por': 'pt', 'portuguese': 'pt',
        'ar': 'ar', 'ara': 'ar', 'arabic': 'ar',
        'ru': 'ru', 'rus': 'ru', 'russian': 'ru',
    }
    return mapping.get(tail, '')
