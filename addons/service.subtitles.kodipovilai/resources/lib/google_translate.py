# Google Translate fallback for MoranSubs.
#
# Mirrors what DarkSubs does (engine.google_machine_translate): split the SRT
# into ~3000-char chunks on subtitle-cue boundaries, translate each chunk to
# Hebrew via Google's free web endpoint, rejoin, and repair any timestamp
# spacing the translation introduced. No external dependency -- DarkSubs's
# googletrans library hits this same endpoint under the hood, so this is the
# same translation, just without bundling the library.
#
# Used ONLY when the user selects "Google" in translation_mode, OR as an
# automatic fallback when the Gemini daily quota runs out. These translations
# are machine quality and are NEVER shared to the community pool.

import json
import re
import urllib.parse
import urllib.request

_ENDPOINT = 'https://translate.googleapis.com/translate_a/single'
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# Google sometimes adds/strips spaces inside timestamps when it translates a
# whole SRT chunk -- normalise them back to "HH:MM:SS,mmm --> HH:MM:SS,mmm".
_TIMESTAMP_RE = re.compile(
    r'(\d{2}):\s?(\d{2}):\s?(\d{2}),\s?(\d{3})\s?-{1,2}>\s?'
    r'(\d{2}):\s?(\d{2}):\s?(\d{2}),\s?(\d{3})')


def _translate_chunk(text, src_lang):
    q = urllib.parse.urlencode({
        'client': 'gtx',
        'sl': src_lang or 'auto',
        'tl': 'iw',  # Google's code for Hebrew
        'dt': 't',
        'q': text,
    })
    req = urllib.request.Request(_ENDPOINT + '?' + q,
                                 headers={'User-Agent': _UA})
    raw = urllib.request.urlopen(req, timeout=30).read().decode('utf-8')
    data = json.loads(raw)
    # data[0] is a list of [translated_segment, source_segment, ...] pairs.
    return ''.join(seg[0] for seg in (data[0] or []) if seg and seg[0])


def _chunk_srt(text, limit=3000):
    """Group whole subtitle cues into <=limit-char chunks (so a translation
    request never cuts a cue in half)."""
    chunks = []
    cur = ''
    for cue in text.split('\n\n'):
        piece = cue + '\n\n'
        if cur and len(cur) + len(piece) > limit:
            chunks.append(cur)
            cur = piece
        else:
            cur += piece
    if cur.strip():
        chunks.append(cur)
    return chunks


def translate_srt(text, src_lang='auto'):
    """Translate an SRT to Hebrew via Google. Returns the Hebrew SRT text, or
    None on any failure (the caller then keeps the source / aborts)."""
    try:
        if not text or not text.strip():
            return None
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        parts = []
        for chunk in _chunk_srt(text):
            translated = _translate_chunk(chunk, src_lang)
            if not translated:
                return None
            parts.append(translated.strip('\n'))
        out = '\n\n'.join(parts)
        out = _TIMESTAMP_RE.sub(r'\1:\2:\3,\4 --> \5:\6:\7,\8', out)
        return out
    except Exception:
        return None
