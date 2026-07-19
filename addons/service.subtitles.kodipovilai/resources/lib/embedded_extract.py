# Embedded-subtitle TEXT extractor for the AI translation pipeline.
#
# Reads the *text* of an embedded subtitle track (SRT / ASS-SSA / WebVTT)
# straight out of a playing MKV/WebM -- over local files or debrid HTTP Range
# requests -- so the AI pipeline can translate a PERFECTLY SYNCED source: the
# embedded track's cue timestamps ARE the video's own timeline, so the Hebrew
# it produces needs no re-sync at all.
#
# This is the read-the-TEXT counterpart to mkv_probe.py, which reads only the
# embedded track's TIMESTAMPS (to re-time an external sub). Both walk the same
# Matroska structures; this one additionally reads the block PAYLOAD and, for
# HTTP, uses the Cues index to fetch only the clusters that hold subtitle data.
#
# Strategy:
#   local file  -> one sequential pass over the clusters (cheap, complete).
#   HTTP/debrid -> parse Cues, visit only the referenced clusters via surgical
#                  Range requests (tens of MB, never the whole file); if the
#                  file has no usable Cues we bail to None (the caller then
#                  falls through to the existing external-subtitle path).
#
# Self-contained: stdlib only, no xbmc, no package imports -- so it ships in
# BOTH the build and the slim standalone edition. Every entry point is fully
# guarded and returns None / [] on any problem, so a caller ALWAYS has the
# existing external path to fall back to: this can only ADD a source, never
# break one. Only TEXT codecs are extracted (S_TEXT/*); bitmap tracks
# (PGS/VOBSUB) are reported by probe_tracks() but not extracted here.

import os
import re
import struct
import time

try:
    import urllib.request as _urlreq
except Exception:  # pragma: no cover - urllib always present on CPython 3
    _urlreq = None

# ---- EBML / Matroska element IDs (raw, incl. length-descriptor bits) --------
_EBML = 0x1A45DFA3
_SEGMENT = 0x18538067
_SEEKHEAD = 0x114D9B74
_SEEK = 0x4DBB
_SEEKID = 0x53AB
_SEEKPOS = 0x53AC
_INFO = 0x1549A966
_TS_SCALE = 0x2AD7B1
_TRACKS = 0x1654AE6B
_TRACKENTRY = 0xAE
_TRACKNUM = 0xD7
_TRACKTYPE = 0x83
_CODEC = 0x86
_CODEC_PRIVATE = 0x63A2
_LANG = 0x22B59C
_LANG_BCP47 = 0x22B59D
_FORCED = 0x55AA
_CUES = 0x1C53BB6B
_CUE_POINT = 0xBB
_CUE_TIME = 0xB3
_CUE_TRACK_POS = 0xB7
_CUE_TRACK = 0xF7
_CUE_CLUSTER_POS = 0xF1
_CLUSTER = 0x1F43B675
_CLUSTER_MAGIC = b'\x1f\x43\xb6\x75'
_TIMESTAMP = 0xE7
_SIMPLEBLOCK = 0xA3
_BLOCKGROUP = 0xA0
_BLOCK = 0xA1
_BLOCKDUR = 0x9B

_SUB_TRACK_TYPE = 0x11

# ---- budgets ----------------------------------------------------------------
DEFAULT_HEAD_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_BYTES = 80 * 1024 * 1024      # surgical Cues fetch stays well under
DEFAULT_DEADLINE_S = 30.0
_HTTP_TIMEOUT = 15
_CLUSTER_WINDOW = 256 * 1024              # first fetch per referenced cluster
_CLUSTER_WINDOW_MAX = 2 * 1024 * 1024     # grow to this before giving up on it
_LOCAL_CHUNK = 4 * 1024 * 1024
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

_TEXT_CODEC_PREFIX = 'S_TEXT'


def _noop(_m):
    return None


def _aborted(abort_cb):
    """True when the caller signals to stop (e.g. playback ended). A callback
    that raises is treated as 'keep going', never as an abort."""
    if abort_cb is None:
        return False
    try:
        return bool(abort_cb())
    except Exception:
        return False


# ---- primitives (self-contained, byte-faithful to mkv_probe.py) -------------
class _Buf(object):
    __slots__ = ('d', 'n', 'p', 'base')

    def __init__(self, data, base):
        self.d = data
        self.n = len(data)
        self.p = 0
        self.base = base

    def left(self):
        return self.n - self.p


def _read_vint(buf, keep_marker):
    """(value, length) EBML variable-int at buf.p; (None, 0) when truncated.
    keep_marker=True for element IDs, False for sizes (marker stripped;
    all-ones payload -> None value = 'unknown size')."""
    if buf.left() < 1:
        return None, 0
    first = buf.d[buf.p]
    if first == 0:
        return None, 0
    length = 1
    mask = 0x80
    while not (first & mask):
        mask >>= 1
        length += 1
        if length > 8:
            return None, 0
    if buf.left() < length:
        return None, 0
    raw = buf.d[buf.p:buf.p + length]
    buf.p += length
    val = 0
    for b in raw:
        val = (val << 8) | b
    if keep_marker:
        return val, length
    val &= (1 << (7 * length)) - 1
    if val == (1 << (7 * length)) - 1:
        return None, length
    return val, length


def _read_uint(data):
    val = 0
    for b in data:
        val = (val << 8) | b
    return val


def _walk(buf, end):
    """Yield (element_id, size_or_None, payload_start) for children in
    buf.d[buf.p:end]; caller advances past each payload itself."""
    while buf.p < end:
        eid, _idl = _read_vint(buf, True)
        if eid is None:
            return
        size, slen = _read_vint(buf, False)
        if slen == 0:
            return
        yield eid, size, buf.p


class _Source(object):
    """Byte source with .read(offset, size) -- local file or HTTP Range.
    Reads are hard-capped at `size`: a server that ignores Range (200) at a
    non-zero offset yields b'' rather than streaming the whole file."""

    def __init__(self, url_or_path):
        self.url = url_or_path or ''
        self.is_http = bool(re.match(r'^https?://', self.url, re.I))
        self.fetched = 0
        self.total = 0
        if not self.is_http:
            try:
                self.total = os.path.getsize(self.url)
            except Exception:
                self.total = 0
        else:
            self.total = self._http_size()

    def _http_size(self):
        if _urlreq is None:
            return 0
        try:
            req = _urlreq.Request(
                self.url, headers={'Range': 'bytes=0-0', 'User-Agent': _UA})
            resp = _urlreq.urlopen(req, timeout=_HTTP_TIMEOUT)
            cr = resp.headers.get('Content-Range') or ''
            try:
                resp.read(1)
            except Exception:
                pass
            resp.close()
            m = re.search(r'/(\d+)\s*$', cr)
            if m:
                return int(m.group(1))
            cl = resp.headers.get('Content-Length')
            return int(cl) if cl else 0
        except Exception:
            return 0

    def read(self, offset, size):
        if size <= 0 or offset < 0:
            return b''
        if not self.is_http:
            try:
                with open(self.url, 'rb') as f:
                    f.seek(offset)
                    data = f.read(size)
                self.fetched += len(data)
                return data
            except Exception:
                return b''
        if _urlreq is None:
            return b''
        try:
            req = _urlreq.Request(self.url, headers={
                'Range': 'bytes={0}-{1}'.format(offset, offset + size - 1),
                'User-Agent': _UA})
            resp = _urlreq.urlopen(req, timeout=_HTTP_TIMEOUT)
            code = getattr(resp, 'status', None) or resp.getcode()
            if code == 200 and offset > 0:
                resp.close()
                return b''   # server ignored Range; can't safely seek
            data = resp.read(size)
            resp.close()
            self.fetched += len(data)
            return data
        except Exception:
            return b''


def _parse_track_entry(data):
    t = {'num': None, 'type': None, 'codec': '', 'lang': '', 'forced': False,
         'private': b''}
    buf = _Buf(data, 0)
    for eid, size, start in _walk(buf, len(data)):
        if size is None:
            break
        payload = data[start:start + size]
        buf.p = start + size
        if eid == _TRACKNUM:
            t['num'] = _read_uint(payload)
        elif eid == _TRACKTYPE:
            t['type'] = _read_uint(payload)
        elif eid == _CODEC:
            t['codec'] = payload.decode('ascii', 'replace')
        elif eid == _CODEC_PRIVATE:
            t['private'] = payload
        elif eid in (_LANG, _LANG_BCP47):
            if not t['lang']:
                t['lang'] = payload.decode('ascii', 'replace').strip('\x00')
    return t


def _parse_head(src, head_bytes, log):
    """(seg_start, ts_scale_ns, tracks, seeks) or raises.
    `seeks` maps element-id -> absolute file offset (from the SeekHead)."""
    head = src.read(0, head_bytes)
    buf = _Buf(head, 0)
    eid, _l = _read_vint(buf, True)
    if eid != _EBML:
        raise ValueError('not EBML/Matroska')
    esize, _sl = _read_vint(buf, False)
    if esize is None:
        raise ValueError('bad EBML header')
    buf.p += esize
    eid, _l = _read_vint(buf, True)
    if eid != _SEGMENT:
        raise ValueError('no Segment')
    _segsize, _sl = _read_vint(buf, False)
    seg_start = buf.p

    ts_scale = 1000000
    tracks = []
    seeks = {}
    p = seg_start
    while p < len(head):
        buf.p = p
        eid, _idl = _read_vint(buf, True)
        if eid is None:
            break
        size, slen = _read_vint(buf, False)
        if slen == 0:
            break
        pstart = buf.p
        if eid == _CLUSTER:
            break
        if size is None:
            break
        in_head = pstart + size <= len(head)
        payload = head[pstart:pstart + size] if in_head else b''
        if eid == _SEEKHEAD and in_head:
            sbuf = _Buf(payload, 0)
            for seid, ssize, sstart in _walk(sbuf, len(payload)):
                if ssize is None:
                    break
                sp = payload[sstart:sstart + ssize]
                sbuf.p = sstart + ssize
                if seid == _SEEK:
                    ibuf = _Buf(sp, 0)
                    sid, spos = None, None
                    for ieid, isize, istart in _walk(ibuf, len(sp)):
                        if isize is None:
                            break
                        ip = sp[istart:istart + isize]
                        ibuf.p = istart + isize
                        if ieid == _SEEKID:
                            sid = _read_uint(ip)
                        elif ieid == _SEEKPOS:
                            spos = _read_uint(ip)
                    if sid is not None and spos is not None:
                        seeks[sid] = seg_start + spos
        elif eid == _INFO and in_head:
            ibuf = _Buf(payload, 0)
            for ieid, isize, istart in _walk(ibuf, len(payload)):
                if isize is None:
                    break
                ip = payload[istart:istart + isize]
                ibuf.p = istart + isize
                if ieid == _TS_SCALE:
                    ts_scale = _read_uint(ip) or 1000000
        elif eid == _TRACKS and in_head:
            tbuf = _Buf(payload, 0)
            for teid, tsize, tstart in _walk(tbuf, len(payload)):
                if tsize is None:
                    break
                tp = payload[tstart:tstart + tsize]
                tbuf.p = tstart + tsize
                if teid == _TRACKENTRY:
                    tracks.append(_parse_track_entry(tp))
        p = pstart + size

    # SeekHead fallback for Tracks that live beyond the head fetch.
    if not tracks and seeks.get(_TRACKS):
        pos = seeks[_TRACKS]
        raw = src.read(pos, 512 * 1024)
        b2 = _Buf(raw, pos)
        eid2, _ = _read_vint(b2, True)
        size2, sl2 = _read_vint(b2, False)
        if eid2 == _TRACKS and sl2 and size2 is not None:
            if b2.p + size2 > len(raw):
                raw += src.read(pos + len(raw), size2 - (len(raw) - b2.p))
                b2 = _Buf(raw, pos)
                _read_vint(b2, True)
                _read_vint(b2, False)
            tp_all = raw[b2.p:b2.p + size2]
            tbuf = _Buf(tp_all, 0)
            for teid, tsize, tstart in _walk(tbuf, len(tp_all)):
                if tsize is None:
                    break
                tp = tp_all[tstart:tstart + tsize]
                tbuf.p = tstart + tsize
                if teid == _TRACKENTRY:
                    tracks.append(_parse_track_entry(tp))

    log('head: %d track(s), ts_scale=%dns' % (len(tracks), ts_scale))
    return seg_start, ts_scale, tracks, seeks


def _is_text_codec(codec):
    return (codec or '').upper().startswith(_TEXT_CODEC_PREFIX)


def _sub_tracks(tracks):
    return [t for t in tracks
            if t.get('type') == _SUB_TRACK_TYPE and t.get('num') is not None]


# ---- Cues -------------------------------------------------------------------
def _read_cues(src, seeks, seg_start, log):
    """Return sorted, de-duplicated absolute cluster positions from the Cues
    index (any track), or [] when there is no usable Cues element."""
    pos = seeks.get(_CUES)
    if not pos:
        return []
    raw = src.read(pos, 64 * 1024)
    if not raw:
        return []
    b = _Buf(raw, pos)
    eid, _l = _read_vint(b, True)
    size, slen = _read_vint(b, False)
    if eid != _CUES or slen == 0 or size is None:
        return []
    # Pull in the whole Cues element (it can exceed the first fetch).
    need = b.p + size
    while len(raw) < need:
        more = src.read(pos + len(raw), min(4 * 1024 * 1024, need - len(raw)))
        if not more:
            break
        raw += more
    b = _Buf(raw, pos)
    _read_vint(b, True)
    _read_vint(b, False)
    data = raw[b.p:b.p + size]
    positions = set()
    cbuf = _Buf(data, 0)
    for eid2, size2, start2 in _walk(cbuf, len(data)):
        if size2 is None:
            break
        cbuf.p = start2 + size2
        if eid2 != _CUE_POINT:
            continue
        cp = data[start2:start2 + size2]
        pbuf = _Buf(cp, 0)
        for peid, psize, pstart in _walk(pbuf, len(cp)):
            if psize is None:
                break
            pp = cp[pstart:pstart + psize]
            pbuf.p = pstart + psize
            if peid == _CUE_TRACK_POS:
                tbuf = _Buf(pp, 0)
                for teid, tsize, tstart in _walk(tbuf, len(pp)):
                    if tsize is None:
                        break
                    tp = pp[tstart:tstart + tsize]
                    tbuf.p = tstart + tsize
                    if teid == _CUE_CLUSTER_POS:
                        positions.add(seg_start + _read_uint(tp))
    out = sorted(positions)
    log('cues: %d cluster position(s)' % len(out))
    return out


# ---- block / cluster text ---------------------------------------------------
def _block_frame(payload, cluster_ts, want_track):
    """(abs_ticks, frame_bytes) for a (Simple)Block of want_track, or None.
    Laced blocks are skipped (subtitles are virtually never laced)."""
    buf = _Buf(payload, 0)
    tnum, _l = _read_vint(buf, False)
    if tnum is None or tnum != want_track:
        return None
    if buf.left() < 3:
        return None
    rel = struct.unpack('>h', payload[buf.p:buf.p + 2])[0]
    buf.p += 2
    flags = payload[buf.p]
    buf.p += 1
    if (flags >> 1) & 0x03:
        return None   # laced -> skip (safe: this cue is just omitted)
    frame = payload[buf.p:]
    if not frame:
        return None
    return cluster_ts + rel, frame


def _collect_cluster(window, base, want_track, out):
    """Parse cluster(s) in `window` (bytes at absolute offset `base`) and append
    (abs_ticks, dur_ticks_or_None, frame_bytes) for want_track into `out`.
    Returns the absolute offset one past the last fully-parsed cluster."""
    pos = 0
    last_end = base
    while True:
        idx = window.find(_CLUSTER_MAGIC, pos)
        if idx < 0:
            return last_end
        buf = _Buf(window, base)
        buf.p = idx + 4
        csize, sl = _read_vint(buf, False)
        if sl == 0:
            return last_end
        limit = buf.n if csize is None else min(buf.n, buf.p + csize)
        cluster_ts = None
        while buf.p < limit:
            if window[buf.p:buf.p + 4] == _CLUSTER_MAGIC:
                break
            eid, _idl = _read_vint(buf, True)
            if eid is None:
                break
            size, slen = _read_vint(buf, False)
            if slen == 0 or size is None:
                break
            if buf.p + size > buf.n:
                break   # element runs past the window -> stop this cluster
            payload = window[buf.p:buf.p + size]
            if eid == _TIMESTAMP:
                cluster_ts = _read_uint(payload)
            elif eid == _SIMPLEBLOCK and cluster_ts is not None:
                r = _block_frame(payload, cluster_ts, want_track)
                if r:
                    out.append((r[0], None, r[1]))
            elif eid == _BLOCKGROUP and cluster_ts is not None:
                gbuf = _Buf(payload, 0)
                block, gdur = None, None
                for geid, gsize, gstart in _walk(gbuf, len(payload)):
                    if gsize is None:
                        break
                    gp = payload[gstart:gstart + gsize]
                    gbuf.p = gstart + gsize
                    if geid == _BLOCK:
                        block = gp
                    elif geid == _BLOCKDUR:
                        gdur = _read_uint(gp)
                if block:
                    r = _block_frame(block, cluster_ts, want_track)
                    if r:
                        out.append((r[0], gdur, r[1]))
            buf.p += size
        if csize is not None:
            last_end = base + min(buf.p, limit)
        pos = buf.p if buf.p > idx + 4 else idx + 4


# ---- text decode ------------------------------------------------------------
_ASS_TAG = re.compile(r'\{[^}]*\}')
_VTT_TAG = re.compile(r'</?[^>]+>')


def _decode_frame(frame, codec):
    try:
        text = frame.decode('utf-8', 'replace')
    except Exception:
        return ''
    up = (codec or '').upper()
    if up in ('S_TEXT/ASS', 'S_TEXT/SSA'):
        # MKV ASS block body: ReadOrder,Layer,Style,Name,ML,MR,MV,Effect,Text
        parts = text.split(',', 8)
        text = parts[8] if len(parts) >= 9 else text
        text = text.replace('\\N', '\n').replace('\\n', '\n')
        text = _ASS_TAG.sub('', text)
    elif up == 'S_TEXT/WEBVTT':
        text = _VTT_TAG.sub('', text)
    return text.strip('﻿').strip()


def _fmt_ts(ms):
    if ms < 0:
        ms = 0
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ml = ms % 1000
    return '%02d:%02d:%02d,%03d' % (h, m, s, ml)


def _entries_to_srt(entries, scale_ms, origin_ms, codec):
    """entries: [(abs_ticks, dur_ticks_or_None, frame_bytes)] -> SRT string."""
    rows = []
    for ticks, dur, frame in entries:
        start = int(ticks * scale_ms - origin_ms)
        if start < 0:
            continue
        text = _decode_frame(frame, codec)
        if not text:
            continue
        dur_ms = int(dur * scale_ms) if dur else None
        rows.append((start, dur_ms, text))
    if not rows:
        return ''
    rows.sort(key=lambda r: r[0])
    # De-duplicate identical (start, text) that a Cues fetch can revisit.
    dedup = []
    seen = set()
    for start, dur_ms, text in rows:
        key = (start, text)
        if key in seen:
            continue
        seen.add(key)
        dedup.append([start, dur_ms, text])
    out = []
    for i, (start, dur_ms, text) in enumerate(dedup):
        if dur_ms and dur_ms > 0:
            end = start + dur_ms
        else:
            nxt = dedup[i + 1][0] if i + 1 < len(dedup) else start + 3000
            end = start + max(700, min(6000, nxt - start - 60))
        if end <= start:
            end = start + 700
        out.append('%d' % (i + 1))
        out.append('%s --> %s' % (_fmt_ts(start), _fmt_ts(end)))
        out.append(text)
        out.append('')
    return '\n'.join(out)


def _timeline_origin(src, seg_start, scale_ms, log):
    """First cluster timestamp in ms (the playback zero point) so cues line up
    with players that rebase to it. 0 for normal zero-based files."""
    try:
        pos = seg_start
        cap = seg_start + 8 * 1024 * 1024
        carry = b''
        while pos < cap:
            chunk = src.read(pos, 1024 * 1024)
            if not chunk:
                return 0.0
            data = carry + chunk
            idx = data.find(_CLUSTER_MAGIC)
            if idx >= 0:
                buf = _Buf(data, 0)
                buf.p = idx + 4
                _cs, sl = _read_vint(buf, False)
                if sl == 0:
                    return 0.0
                eid, _l = _read_vint(buf, True)
                size, slen = _read_vint(buf, False)
                if (eid == _TIMESTAMP and slen and size
                        and buf.p + size <= len(data)):
                    origin = _read_uint(data[buf.p:buf.p + size]) * scale_ms
                    if origin > 1000:
                        log('timeline origin %.1fs -- rebasing' % (origin / 1e3))
                    return float(origin)
                return 0.0
            carry = data[-4:]
            pos += len(chunk)
        return 0.0
    except Exception:
        return 0.0


# ---- public API -------------------------------------------------------------
def probe_tracks(url_or_path, head_bytes=DEFAULT_HEAD_BYTES, log=None):
    """Return the embedded subtitle tracks as
        [{'num','codec','lang','forced','is_text'}, ...]
    or [] when the file isn't Matroska / has none / can't be read. Cheap: reads
    only the head. Never raises."""
    _log = log or _noop
    try:
        src = _Source(url_or_path)
        if not src.total:
            return []
        _seg, _scale, tracks, _seeks = _parse_head(src, head_bytes, _log)
        out = []
        for t in _sub_tracks(tracks):
            out.append({'num': t['num'], 'codec': t['codec'],
                        'lang': (t['lang'] or '').lower(),
                        'forced': bool(t['forced']),
                        'is_text': _is_text_codec(t['codec'])})
        return out
    except Exception as e:
        _log('probe_tracks failed: %s' % e)
        return []


def extract_srt(url_or_path, track_num=None, lang=None,
                head_bytes=DEFAULT_HEAD_BYTES, max_bytes=DEFAULT_MAX_BYTES,
                deadline_s=DEFAULT_DEADLINE_S, abort_cb=None, log=None):
    """Extract an embedded TEXT subtitle track as an SRT string.

    Pick the track by `track_num`, else by `lang` (BCP-47 prefix, e.g. 'en'
    matches 'eng'), else the first non-forced text track. Returns the SRT text,
    or None when there is no matching text track / the file has no usable Cues
    over HTTP / anything fails. NEVER raises -- the caller always has the
    external path to fall back to. `abort_cb`, if given, is polled between
    clusters; when it returns True (e.g. playback ended) extraction stops."""
    _log = log or _noop
    t0 = time.time()
    try:
        src = _Source(url_or_path)
        if not src.total:
            return None
        seg_start, ts_scale, tracks, seeks = _parse_head(src, head_bytes, _log)
        subs = _sub_tracks(tracks)
        if not subs:
            return None
        track = _pick_track(subs, track_num, lang)
        if track is None:
            _log('no matching text track (num=%s lang=%s)' % (track_num, lang))
            return None
        if not _is_text_codec(track['codec']):
            _log('track #%s is %s (not text) -- skipping'
                 % (track['num'], track['codec']))
            return None
        want = track['num']
        codec = track['codec']
        scale_ms = ts_scale / 1e6
        origin_ms = _timeline_origin(src, seg_start, scale_ms, _log)
        entries = []
        if not src.is_http:
            _extract_local(src, seg_start, want, entries, deadline_s, t0,
                           abort_cb, _log)
        else:
            ok = _extract_http(src, seeks, seg_start, want, entries,
                               max_bytes, deadline_s, t0, abort_cb, _log)
            if not ok:
                return None
        if not entries:
            _log('no subtitle blocks collected for track #%s' % want)
            return None
        srt = _entries_to_srt(entries, scale_ms, origin_ms, codec)
        if not srt:
            return None
        _log('extracted %d cue(s) from track #%s (%s), %.1fMB, %.1fs'
             % (srt.count('-->'), want, codec, src.fetched / 1e6,
                time.time() - t0))
        return srt
    except Exception as e:
        _log('extract_srt failed: %s' % e)
        return None


def _pick_track(subs, track_num, lang):
    if track_num is not None:
        for t in subs:
            if t['num'] == track_num:
                return t
        return None
    if lang:
        pref = lang.lower()[:2]
        cand = [t for t in subs if _is_text_codec(t['codec'])
                and (t['lang'] or '').lower().startswith(pref)]
        # non-forced first, then forced
        cand.sort(key=lambda t: (t['forced'], t['num']))
        if cand:
            return cand[0]
        return None
    cand = [t for t in subs if _is_text_codec(t['codec']) and not t['forced']]
    cand.sort(key=lambda t: t['num'])
    return cand[0] if cand else None


def _extract_local(src, seg_start, want, entries, deadline_s, t0,
                   abort_cb, log):
    """One sequential pass over the file's clusters (cheap on local disk)."""
    pos = seg_start
    carry = b''
    carry_base = seg_start
    while pos < src.total:
        if (time.time() - t0) > deadline_s:
            log('local extract deadline reached')
            break
        if _aborted(abort_cb):
            log('local extract aborted (playback ended)')
            break
        chunk = src.read(pos, _LOCAL_CHUNK)
        if not chunk:
            break
        window = carry + chunk
        end = _collect_cluster(window, carry_base, want, entries)
        # keep a tail overlap so a cluster split across chunks is re-tried
        consumed = end - carry_base
        if consumed <= 0 or consumed >= len(window):
            carry = b''
            carry_base = pos + len(chunk)
        else:
            keep = min(len(window) - consumed, 1024 * 1024)
            carry = window[len(window) - keep:]
            carry_base = (pos + len(chunk)) - keep
        pos += len(chunk)


def _extract_http(src, seeks, seg_start, want, entries,
                  max_bytes, deadline_s, t0, abort_cb, log):
    """Cues-guided extraction: fetch only the referenced clusters via Range.
    Returns True on a completed pass, False when there is no usable Cues index
    (caller then falls back to the external path)."""
    positions = _read_cues(src, seeks, seg_start, log)
    if not positions:
        log('no usable Cues over HTTP -- deferring to external path')
        return False
    for cpos in positions:
        if src.fetched >= max_bytes or (time.time() - t0) > deadline_s:
            log('http extract budget/deadline reached (%.1fMB, %.1fs)'
                % (src.fetched / 1e6, time.time() - t0))
            return False
        if _aborted(abort_cb):
            log('http extract aborted (playback ended)')
            return False
        window = src.read(cpos, _CLUSTER_WINDOW)
        if not window or window[:4] != _CLUSTER_MAGIC:
            continue
        before = len(entries)
        _collect_cluster(window, cpos, want, entries)
        # Grow the window if this cluster held no want-track block yet but may
        # extend beyond the first fetch (a big cluster whose sub block is late).
        grow = _CLUSTER_WINDOW
        while (len(entries) == before and grow < _CLUSTER_WINDOW_MAX
               and src.fetched < max_bytes):
            grow *= 2
            window = src.read(cpos, grow)
            if not window:
                break
            del entries[before:]
            _collect_cluster(window, cpos, want, entries)
    return True
