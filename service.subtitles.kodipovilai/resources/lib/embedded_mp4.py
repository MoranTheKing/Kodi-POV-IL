# MoranSubs by MoranTheKing - https://github.com/MoranTheKing/Kodi-POV-IL
# SPDX-License-Identifier: GPL-3.0-or-later (additional terms: LICENSE.txt)
"""Embedded text subtitles from an MP4 (ISO BMFF) file, local or over HTTP.

WHY. 4K Dolby Vision WEB-DLs are often MP4, not Matroska (QA, 14 Nov 2026: The
Dark Knight and The Matrix 2160p DV WEB-DLs), and an embedded pick on one ended
in "could not extract". Their subtitles are text: tx3g (3GPP timed text, what
ffmpeg calls mov_text; Apple's 'text' handler) or wvtt (WebVTT in MP4).

HOW, and what it costs over a stream. The sample tables in the 'moov' box say
where every subtitle sample is, how long it is and when it plays -- so, as with
a Matroska index, only the subtitle bytes are fetched: the top-level box
headers (one small request each until 'moov'), 'moov' itself (6 MB on the Dark
Knight, in 2 MB pieces), then the samples, batched (_Source.prefetch). This
module only parses; embedded_extract drives the reading with its _Source, so
the pacing, the player's buffer gate and the abort checks are the same ones.
"""
import struct

_CONTAINERS = (b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts', b'udta',
               b'dinf')
TEXT_HANDLERS = (b'text', b'sbtl', b'subt')
TEXT_ENTRIES = (b'tx3g', b'text', b'wvtt')
PICTURE_HANDLERS = (b'subp',)                 # VobSub in MP4 ('mp4s')
MOOV_MAX = 96 * 1024 * 1024                   # a film's moov is a few MB
# A table count is the file's word: a broken one must not allocate gigabytes
# (review: a fixed-size stsz claiming 2e7 samples took 160 MB).
SAMPLES_MAX = 1000000
# A subtitle sample is a line or two; a "sample" larger than this is a broken
# table, never fetched (review).
SAMPLE_BYTES_MAX = 64 * 1024
TOP_BOXES_MAX = 64                            # top-level boxes walked to moov
# tx3g displayFlags: all samples forced
_TX3G_ALL_FORCED = 0x80000000


def _boxes(d, start, end):
    """(type, payload_start, end) of the boxes in d[start:end]."""
    p = start
    while p + 8 <= end:
        size, typ = struct.unpack_from('>I4s', d, p)
        hdr = 8
        if size == 1:
            if p + 16 > end:
                return
            size = struct.unpack_from('>Q', d, p + 8)[0]
            hdr = 16
        elif size == 0:
            size = end - p
        if size < hdr or p + size > end:
            return
        yield typ, p + hdr, p + size
        p += size


def _child(d, start, end, typ):
    for t, a, b in _boxes(d, start, end):
        if t == typ:
            return a, b
    return None


def _path(d, start, end, *types):
    span = (start, end)
    for t in types:
        span = _child(d, span[0], span[1], t)
        if span is None:
            return None
    return span


def find_moov(read, total):
    """(offset, size) of 'moov', walking the top-level box headers with
    read(offset, n) -> bytes; None when there is none (or it is too big)."""
    off = 0
    for _ in range(TOP_BOXES_MAX):
        if total and off + 8 > total:
            return None
        h = read(off, 16)
        if len(h) < 8:
            return None
        size, typ = struct.unpack_from('>I4s', h, 0)
        hdr = 8
        if size == 1:
            if len(h) < 16:
                return None
            size = struct.unpack_from('>Q', h, 8)[0]
            hdr = 16
        elif size == 0:
            size = (total - off) if total else 0
        if typ == b'moov':
            return (off, size) if hdr < size <= MOOV_MAX else None
        if size < hdr:
            return None
        off += size
    return None


def _mdhd(d, a):
    """(timescale, language) of an mdhd payload starting at a."""
    v = d[a]
    if v == 1:
        ts = struct.unpack_from('>I', d, a + 20)[0]
        lp = a + 32
    else:
        ts = struct.unpack_from('>I', d, a + 12)[0]
        lp = a + 20
    code = struct.unpack_from('>H', d, lp)[0] & 0x7FFF
    lang = ''.join(chr(((code >> s) & 31) + 0x60) for s in (10, 5, 0)) \
        if code else ''
    return ts, (lang if lang.isalpha() else '')


def _mvhd_timescale(d, moov):
    span = _child(d, moov[0], moov[1], b'mvhd')
    if span is None:
        return 0
    a = span[0]
    return struct.unpack_from('>I', d, a + (20 if d[a] == 1 else 12))[0]


def _elst(d, trak):
    """[(segment_duration, media_time)] of the track's edit list."""
    span = _path(d, trak[0], trak[1], b'edts', b'elst')
    if span is None:
        return []
    a = span[0]
    v = d[a]
    n = struct.unpack_from('>I', d, a + 4)[0]
    out, p = [], a + 8
    for _ in range(min(n, 64)):
        if v == 1:
            dur, mt = struct.unpack_from('>Qq', d, p)
            p += 20
        else:
            dur, mt = struct.unpack_from('>Ii', d, p)
            p += 12
        out.append((dur, mt))
    return out


def _text_of(d, start, end):
    try:
        return d[start:end].decode('utf-8', 'replace').strip('\x00 \r\n')
    except Exception:
        return ''


def tracks(moov_bytes):
    """Every subtitle track of a moov box (bytes starting at its header):
    dicts shaped like embedded_extract's Matroska tracks (num, codec, lang,
    lang_explicit, forced, name, hearing_impaired) plus what reading needs."""
    d = moov_bytes
    top = next(_boxes(d, 0, len(d)), None)
    if top is None or top[0] != b'moov':
        return []
    moov = (top[1], top[2])
    movie_ts = _mvhd_timescale(d, moov)
    out = []
    for t, a, b in _boxes(d, moov[0], moov[1]):
        if t != b'trak':
            continue
        hdlr = _path(d, a, b, b'mdia', b'hdlr')
        if hdlr is None:
            continue
        handler = d[hdlr[0] + 8:hdlr[0] + 12]
        if handler not in TEXT_HANDLERS + PICTURE_HANDLERS:
            continue
        tkhd = _child(d, a, b, b'tkhd')
        num = 0
        if tkhd is not None:
            num = struct.unpack_from(
                '>I', d, tkhd[0] + (20 if d[tkhd[0]] == 1 else 12))[0]
        mdhd = _path(d, a, b, b'mdia', b'mdhd')
        ts, lang = _mdhd(d, mdhd[0]) if mdhd else (0, '')
        elng = _path(d, a, b, b'mdia', b'elng')
        if elng is not None:
            ext = _text_of(d, elng[0] + 4, elng[1])
            if ext:
                lang = ext
        stbl = _path(d, a, b, b'mdia', b'minf', b'stbl')
        stsd = _child(d, stbl[0], stbl[1], b'stsd') if stbl else None
        entry, flags = b'', 0
        if stsd is not None:
            first = next(_boxes(d, stsd[0] + 8, stsd[1]), None)
            if first is not None:
                entry = first[0]
                if entry == b'tx3g' and first[1] + 12 <= first[2]:
                    flags = struct.unpack_from('>I', d, first[1] + 8)[0]
        name, kinds = '', []
        udta = _child(d, a, b, b'udta')
        if udta is not None:
            for ut, ua, ub in _boxes(d, udta[0], udta[1]):
                if ut == b'name':
                    name = _text_of(d, ua, ub)
                elif ut == b'kind':
                    kinds.append(_text_of(d, ua + 4, ub).lower())
        low = (name + ' ' + ' '.join(kinds)).lower()
        text = handler in TEXT_HANDLERS and entry in TEXT_ENTRIES
        out.append({
            'num': num, 'type': 17,
            'codec': ('S_TEXT/MP4_' + entry.decode('latin1').upper()) if text
            else 'S_VOBSUB',
            'lang': lang or 'und', 'lang_explicit': bool(lang) and lang != 'und',
            'forced': bool(flags & _TX3G_ALL_FORCED) or 'forced' in low,
            'name': name,
            'hearing_impaired': 'caption' in low or 'sdh' in low.split(),
            'entry': entry, 'media_ts': ts, 'movie_ts': movie_ts,
            'stbl': stbl, 'elst': _elst(d, (a, b)),
        })
    return out


def _shift_ms(tr):
    """Presentation = decode + this (ms), from the edit list: leading empty
    edits delay the track, the first media edit's media_time is where it
    starts."""
    delay = 0.0
    for dur, media_time in tr.get('elst') or []:
        if media_time == -1:
            if tr.get('movie_ts'):
                delay += dur * 1000.0 / tr['movie_ts']
            continue
        if tr.get('media_ts'):
            delay -= media_time * 1000.0 / tr['media_ts']
        break
    return delay


def samples(moov_bytes, tr):
    """[(offset, size, start_ms, end_ms)] of every sample of the track, in
    decode order (offsets absolute in the file)."""
    d = moov_bytes
    stbl = tr.get('stbl')
    if not stbl:
        return []
    a, b = stbl
    sizes = []
    stsz = _child(d, a, b, b'stsz')
    stz2 = None if stsz else _child(d, a, b, b'stz2')
    if stsz is not None:
        fixed, count = struct.unpack_from('>II', d, stsz[0] + 4)
        count = min(count, SAMPLES_MAX)
        if fixed:
            sizes = [fixed] * count
        else:
            sizes = list(struct.unpack_from('>%dI' % count, d, stsz[0] + 12))
    elif stz2 is not None:
        field = d[stz2[0] + 7]
        count = min(struct.unpack_from('>I', d, stz2[0] + 8)[0], SAMPLES_MAX)
        p = stz2[0] + 12
        if field == 16:
            sizes = list(struct.unpack_from('>%dH' % count, d, p))
        elif field == 8:
            sizes = list(d[p:p + count])
        elif field == 4:
            for i in range(count):
                byte = d[p + i // 2]
                sizes.append((byte >> 4) if i % 2 == 0 else (byte & 15))
    if not sizes:
        return []
    stco = _child(d, a, b, b'stco')
    co64 = None if stco else _child(d, a, b, b'co64')
    if stco is not None:
        n = min(struct.unpack_from('>I', d, stco[0] + 4)[0], SAMPLES_MAX)
        chunks = list(struct.unpack_from('>%dI' % n, d, stco[0] + 8))
    elif co64 is not None:
        n = min(struct.unpack_from('>I', d, co64[0] + 4)[0], SAMPLES_MAX)
        chunks = list(struct.unpack_from('>%dQ' % n, d, co64[0] + 8))
    else:
        return []
    stsc = _child(d, a, b, b'stsc')
    runs = []
    if stsc is not None:
        n = struct.unpack_from('>I', d, stsc[0] + 4)[0]
        for i in range(n):
            first, per, _sdi = struct.unpack_from('>III', d, stsc[0] + 8 + 12 * i)
            runs.append((first, per))
    if not runs:
        runs = [(1, 1)]
    offsets = []
    ri = 0
    for ci, base in enumerate(chunks, 1):
        while ri + 1 < len(runs) and runs[ri + 1][0] <= ci:
            ri += 1
        p = base
        for _ in range(runs[ri][1]):
            if len(offsets) >= len(sizes):
                break
            offsets.append(p)
            p += sizes[len(offsets) - 1]
        if len(offsets) >= len(sizes):
            break
    stts = _child(d, a, b, b'stts')
    deltas = []
    if stts is not None:
        n = struct.unpack_from('>I', d, stts[0] + 4)[0]
        for i in range(n):
            cnt, delta = struct.unpack_from('>II', d, stts[0] + 8 + 8 * i)
            deltas.extend([delta] * min(cnt, len(sizes) - len(deltas)))
            if len(deltas) >= len(sizes):
                break
    ts = float(tr.get('media_ts') or 1000)
    shift = _shift_ms(tr)
    out, t = [], 0
    for i, off in enumerate(offsets):
        dt = deltas[i] if i < len(deltas) else 0
        start = t * 1000.0 / ts + shift
        out.append((off, sizes[i], int(round(start)),
                    int(round(start + dt * 1000.0 / ts))))
        t += dt
    return out


def sample_text(data, entry):
    """The text of one sample ('' for an empty one)."""
    if not data:
        return ''
    if entry == b'wvtt':
        parts = []
        for t, a, b in _boxes(data, 0, len(data)):
            if t == b'vttc':
                payl = _child(data, a, b, b'payl')
                if payl is not None:
                    parts.append(_text_of(data, payl[0], payl[1]))
        return '\n'.join(p for p in parts if p).replace(
            '\r\n', '\n').replace('\r', '\n').strip()
    if len(data) < 2:
        return ''
    n = struct.unpack_from('>H', data, 0)[0]
    raw = data[2:2 + n]
    if raw[:2] in (b'\xfe\xff', b'\xff\xfe'):
        try:
            text = raw.decode('utf-16')
        except Exception:
            text = ''
    else:
        text = raw.decode('utf-8', 'replace')
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()


def empty_size(entry):
    """A sample no larger than this has no text (tx3g: the 2-byte length 0;
    wvtt: a lone 'vtte' box) -- it is not fetched."""
    return 8 if entry == b'wvtt' else 2
