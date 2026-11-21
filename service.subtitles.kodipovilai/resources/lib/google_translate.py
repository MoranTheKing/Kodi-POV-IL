# MoranSubs by MoranTheKing - https://github.com/MoranTheKing/Kodi-POV-IL
# SPDX-License-Identifier: GPL-3.0-or-later (additional terms: LICENSE.txt)
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
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_ENDPOINT = 'https://translate.googleapis.com/translate_a/single'
# Google's second address (0.3.107). On 21 Nov 2026 the QA Kodi's own Python
# (3.8, OpenSSL 1.1.1) got Google's "unusual traffic" page (HTTP 429) for
# client=gtx on every Google host -- translate_a/single, translate_a/t, POST,
# with or without a browser User-Agent -- while the computer's Python on the
# same network was answered. client=dict-chrome-ex on translate_a/t (what
# Chrome's dictionary extension asks) still answered that Kodi, with the
# same Hebrew, character for character, for a whole 3,000-character chunk.
# The reviewer held it back -- it goes around a block Google set on purpose,
# from every viewer's device, and Google may block it too -- and the owner
# chose it (21 Nov 2026: a viewer who translates with Google only, by his
# own setting, gets nothing while Google turns Kodi away). It is asked only
# when gtx refuses, and first for an hour after such a refusal.
_ENDPOINT_T = 'https://translate.googleapis.com/translate_a/t'
_GTX_REFUSED_S = 3600
# When gtx last refused this device (epoch seconds): a window property, so
# the service and every subtitle search Kodi starts share the hour; this
# module's own copy where there is no Kodi.
_REFUSED_PROP = 'povil.gt.gtx_refused'
_GTX_REFUSED = [None]
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# Google sometimes adds/strips spaces inside timestamps when it translates a
# whole SRT chunk -- normalise them back to "HH:MM:SS,mmm --> HH:MM:SS,mmm".
_TIMESTAMP_RE = re.compile(
    r'(\d{2}):\s?(\d{2}):\s?(\d{2}),\s?(\d{3})\s?-{1,2}>\s?'
    r'(\d{2}):\s?(\d{2}):\s?(\d{2}),\s?(\d{3})')

# Why this thread's last call gave no Hebrew (0.3.107). A viewer, Nov 2026:
# "Google Translate fails on everything, whatever I play" -- while the same
# endpoint answered from here, through Kodi's own Python too. Every failure
# was swallowed into None, so neither his log nor the toast could say why.
# On 21 Nov 2026 Google also turned the QA Kodi's own Python away ("unusual
# traffic", HTTP 429) while the computer's Python on the same network was
# answered: 'blocked' is a real case, not only a heavy user's.
_LAST = threading.local()


def last_failure():
    """(kind, detail) for this thread's last failed call, or None.
    kind: 'blocked' -- Google refused this network (429/403, its "unusual
    traffic" page); 'tls' -- the secure connection failed its check (a
    device clock far off, a filter or an antivirus that opens HTTPS);
    'network' -- no connection (DNS, refused, timed out); 'reply' -- an
    answer that was not a translation."""
    return getattr(_LAST, 'why', None)


def _note(kind, detail):
    _LAST.why = (kind, detail)


def _body(e):
    """An HTTPError's page, read once (lower case)."""
    if not hasattr(e, '_povil_body'):
        try:
            e._povil_body = (e.read(4096) or b'').decode('utf-8', 'replace').lower()
        except Exception:
            e._povil_body = ''
    return e._povil_body


def _refused(e):
    """Whether an exception is Google refusing this client: 429/403, or its
    "unusual traffic" page under another code."""
    return isinstance(e, urllib.error.HTTPError) and (
        e.code in (403, 429) or 'unusual traffic' in _body(e) or '/sorry/' in _body(e))


def route():
    """The address this thread's last answer came from: 'gtx', or
    'dict-chrome-ex' (gtx refused this device); None before any answer."""
    return getattr(_LAST, 'route', None)


def _failure(e):
    """(kind, detail) of an exception from a request (see last_failure);
    the detail also names the first address's refusal when the second one
    failed after it."""
    kind, detail = _failure_of(e)
    first = getattr(e, '_povil_first', None)
    if first is not None:
        detail = '{0} (the first address: {1})'.format(detail, _failure_of(first)[1])
    return kind, detail


def _failure_of(e):
    if isinstance(e, urllib.error.HTTPError):
        if _refused(e):
            return 'blocked', 'HTTP {0}'.format(e.code)
        return 'reply', 'HTTP {0}'.format(e.code)
    reason = getattr(e, 'reason', None) if isinstance(e, urllib.error.URLError) else e
    if isinstance(reason, ssl.SSLError):
        return 'tls', '{0}: {1}'.format(type(reason).__name__, str(reason)[:160])
    if isinstance(reason, OSError):
        return 'network', '{0}: {1}'.format(type(reason).__name__, str(reason)[:160])
    return 'reply', '{0}: {1}'.format(type(e).__name__, str(e)[:160])


def _home():
    """Kodi's home window (its properties outlive one script), or None."""
    try:
        import xbmcgui
        return xbmcgui.Window(10000)
    except Exception:
        return None


def _gtx_refused_since():
    home = _home()
    if home is not None:
        try:
            value = home.getProperty(_REFUSED_PROP)
            if isinstance(value, str):
                return float(value) if value else None
        except Exception:
            pass
    return _GTX_REFUSED[0]


def _note_gtx_refused(when):
    _GTX_REFUSED[0] = when
    home = _home()
    if home is not None:
        try:
            home.setProperty(_REFUSED_PROP, '' if when is None else '%d' % when)
        except Exception:
            pass


def _ask(url, params, timeout):
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(params),
                                 headers={'User-Agent': _UA})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8'))


def _gtx(text, src_lang, timeout):
    data = _ask(_ENDPOINT, {
        'client': 'gtx',
        'sl': src_lang or 'auto',
        'tl': 'iw',  # Google's code for Hebrew
        'dt': 't',
        'q': text,
    }, timeout)
    # data[0] is a list of [translated_segment, source_segment, ...] pairs.
    return ''.join(seg[0] for seg in (data[0] or []) if seg and seg[0])


def _dict_t(text, src_lang, timeout):
    data = _ask(_ENDPOINT_T, {
        'client': 'dict-chrome-ex',
        'sl': src_lang or 'auto',
        'tl': 'iw',
        'q': text,
    }, timeout)
    # One text asked: [translation], or [[translation, the language it
    # found]] when the source language is 'auto'.
    first = data[0] if isinstance(data, list) and data else ''
    if isinstance(first, list):
        first = first[0] if first else ''
    return first if isinstance(first, str) else ''


def _translate_chunk(text, src_lang, timeout=30):
    """Google's Hebrew for `text`: gtx, or the second address when gtx
    refuses this device (and for an hour after it did -- then, should the
    second refuse too, gtx is asked once more)."""
    since = _gtx_refused_since()
    held = since is not None and 0 <= time.time() - since < _GTX_REFUSED_S
    first = None
    if not held:
        try:
            out = _gtx(text, src_lang, timeout)
            _LAST.route = 'gtx'
            return out
        except urllib.error.HTTPError as e:
            if not _refused(e):
                raise
            _note_gtx_refused(time.time())
            first = e
    try:
        out = _dict_t(text, src_lang, timeout)
        _LAST.route = 'dict-chrome-ex'
        return out
    except Exception as e:
        if held and _refused(e):
            try:
                out = _gtx(text, src_lang, timeout)
            except Exception:
                raise e
            _note_gtx_refused(None)
            _LAST.route = 'gtx'
            return out
        if first is not None:
            try:
                e._povil_first = first
            except Exception:
                pass
        raise


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


def translate_lines(lines, src_lang='auto', timeout=30):
    """Translate plain text lines (no SRT scaffolding) to Hebrew.

    One request per line, deliberately: the caller reassembles the cue by
    position, and batching would let a merged or dropped segment shift every
    line after it onto the wrong timecode. Entries reaching this path are
    single cues -- one to three short lines -- so the cost is bounded.

    Returns a list the same length as `lines`, or None if ANY line fails. A
    partial result would put two languages inside one cue, which is worse than
    the English the caller already has in hand.
    """
    _LAST.why = None
    try:
        out = []
        for line in lines:
            if not line.strip():
                out.append(line)
                continue
            heb = _translate_chunk(line, src_lang, timeout)
            if not heb or not heb.strip():
                _note('reply', 'no text in the answer')
                return None
            out.append(heb.strip())
        return out or None
    except Exception as e:
        _note(*_failure(e))
        return None


def translate_srt(text, src_lang='auto'):
    """Translate an SRT to Hebrew via Google. Returns the Hebrew SRT text, or
    None on any failure (the caller then keeps the source / aborts);
    last_failure() then says why."""
    _LAST.why = None
    try:
        if not text or not text.strip():
            _note('reply', 'nothing to translate')
            return None
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        parts = []
        chunks = _chunk_srt(text)
        for n, chunk in enumerate(chunks, 1):
            translated = _translate_chunk(chunk, src_lang)
            if not translated:
                _note('reply', 'no text in the answer to part {0} of {1}'.format(n, len(chunks)))
                return None
            parts.append(translated.strip('\n'))
        out = '\n\n'.join(parts)
        out = _TIMESTAMP_RE.sub(r'\1:\2:\3,\4 --> \5:\6:\7,\8', out)
        return out
    except Exception as e:
        _note(*_failure(e))
        return None
