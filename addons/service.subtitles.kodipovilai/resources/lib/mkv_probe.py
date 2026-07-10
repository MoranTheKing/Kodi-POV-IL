# SubSync Phase S4 -- MKV/WebM container probe: read the EMBEDDED subtitle
# track's cue TIMESTAMPS straight out of the playing file, via HTTP Range
# requests (debrid direct links) or local reads -- WITHOUT downloading the
# file and WITHOUT decoding anything. Those timestamps are a timing reference
# anchored to the actual playing file, for releases (ColdFilm-style
# re-encodes) that exist in no subtitle database.
#
# Strategy (no Cues/index required):
#   1. head fetch: EBML header -> Segment -> (SeekHead ->) Info (TimestampScale)
#      + Tracks (subtitle tracks: number, codec, language, forced).
#   2. N sample windows at byte fractions across the file; in each window
#      resync on the Cluster magic (0x1F43B675), then walk SimpleBlocks /
#      BlockGroups and collect (abs time, duration) for subtitle tracks only
#      (payload bytes are skipped, never decoded -- works for text AND
#      bitmap/PGS tracks alike).
#   3. pick the densest non-forced subtitle track.
#
# Self-contained, stdlib only, no xbmc. Budgeted: every byte fetched is
# counted and hard-capped; a wall-clock deadline stops sampling gracefully.

import os
import re
import time
import struct

# ---- element IDs (raw, incl. length-descriptor bits) ------------------------
_EBML = 0x1A45DFA3
_SEGMENT = 0x18538067
_SEEKHEAD = 0x114D9B74
_SEEK = 0x4DBB
_SEEKID = 0x53AB
_SEEKPOS = 0x53AC
_INFO = 0x1549A966
_TS_SCALE = 0x2AD7B1
_DURATION = 0x4489
_TRACKS = 0x1654AE6B
_TRACKENTRY = 0xAE
_TRACKNUM = 0xD7
_TRACKTYPE = 0x83
_CODEC = 0x86
_CODEC_PRIVATE = 0x63A2
_LANG = 0x22B59C
_LANG_BCP47 = 0x22B59D
_FORCED = 0x55AA
_AUDIO_EL = 0xE1
_SAMPLERATE = 0xB5
_CHANNELS = 0x9F
_CLUSTER = 0x1F43B675
_CLUSTER_MAGIC = b'\x1f\x43\xb6\x75'
_TIMESTAMP = 0xE7
_SIMPLEBLOCK = 0xA3
_BLOCKGROUP = 0xA0
_BLOCK = 0xA1
_BLOCKDUR = 0x9B

_SUB_TRACK_TYPE = 0x11
_AUDIO_TRACK_TYPE = 0x02

DEFAULT_HEAD_BYTES = 2 * 1024 * 1024
DEFAULT_WINDOW_BYTES = 3 * 1024 * 1024
DEFAULT_MAX_WINDOWS = 10
DEFAULT_MAX_BYTES = 40 * 1024 * 1024
DEFAULT_DEADLINE_S = 25.0
_HTTP_TIMEOUT = 10


class _Source(object):
    """Byte source with .read(offset, size) -- local file or HTTP Range."""

    def __init__(self, url_or_path):
        self.url = url_or_path
        self.is_http = bool(re.match(r'^https?://', url_or_path or '', re.I))
        self.total = None
        self.fetched = 0
        self._fh = None
        if not self.is_http:
            self._fh = open(url_or_path, 'rb')
            self._fh.seek(0, os.SEEK_END)
            self.total = self._fh.tell()

    def close(self):
        try:
            if self._fh:
                self._fh.close()
        except Exception:
            pass

    def read(self, offset, size):
        if size <= 0:
            return b''
        if not self.is_http:
            self._fh.seek(offset)
            data = self._fh.read(size)
            self.fetched += len(data)
            return data
        import urllib.request
        req = urllib.request.Request(self.url, headers={
            'Range': 'bytes={0}-{1}'.format(offset, offset + size - 1),
            'User-Agent': 'Kodi-MoranSubs-SubSync/1.0',
        })
        resp = urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT)
        try:
            if self.total is None:
                cr = resp.headers.get('Content-Range') or ''
                m = re.search(r'/(\d+)\s*$', cr)
                if m:
                    self.total = int(m.group(1))
            if resp.status not in (200, 206):
                return b''
            # A 200 means the server ignored Range -- read only what we asked
            # for and never more (protects the budget on broken servers).
            data = resp.read(size)
            self.fetched += len(data)
            return data
        finally:
            try:
                resp.close()
            except Exception:
                pass


class _Buf(object):
    """Parse cursor over one fetched byte window."""

    def __init__(self, data, base):
        self.d = data
        self.n = len(data)
        self.p = 0
        self.base = base   # absolute file offset of d[0]

    def left(self):
        return self.n - self.p

    def abs_pos(self):
        return self.base + self.p


def _read_vint(buf, keep_marker):
    """(value, length) EBML variable-int at buf.p; (None, 0) when truncated.
    keep_marker=True for element IDs, False for sizes (marker bit stripped;
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
        return None, length   # unknown size
    return val, length


def _read_uint(data):
    val = 0
    for b in data:
        val = (val << 8) | b
    return val


def _walk(buf, end):
    """Yield (element_id, size_or_None, payload_start_in_buf) for children in
    buf.d[buf.p:end]; leaves buf.p at each element's payload start -- caller
    must advance past the payload itself."""
    while buf.p < end:
        eid, idlen = _read_vint(buf, True)
        if eid is None:
            return
        size, _slen = _read_vint(buf, False)
        if _slen == 0:
            return
        yield eid, size, buf.p


def _parse_track_entry(data):
    t = {'num': None, 'type': None, 'codec': '', 'lang': '', 'forced': False,
         'private': b'', 'samplerate': 0.0, 'channels': 0}
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
        elif eid == _FORCED:
            t['forced'] = bool(_read_uint(payload))
        elif eid == _AUDIO_EL:
            abuf = _Buf(payload, 0)
            for aeid, asize, astart in _walk(abuf, len(payload)):
                if asize is None:
                    break
                ap = payload[astart:astart + asize]
                abuf.p = astart + asize
                if aeid == _SAMPLERATE:
                    try:
                        t['samplerate'] = (struct.unpack('>f', ap)[0]
                                           if len(ap) == 4 else
                                           struct.unpack('>d', ap)[0])
                    except Exception:
                        pass
                elif aeid == _CHANNELS:
                    t['channels'] = _read_uint(ap)
    return t


def _parse_block(payload, cluster_ts, want_tracks, duration=None):
    """(track_num, abs_ticks, duration_ticks|None) from a (Simple)Block
    payload, or None if not a wanted track / malformed."""
    buf = _Buf(payload, 0)
    tnum, _l = _read_vint(buf, False)
    if tnum is None or tnum not in want_tracks:
        return None
    if buf.left() < 3:
        return None
    rel = struct.unpack('>h', payload[buf.p:buf.p + 2])[0]
    return tnum, cluster_ts + rel, duration


def _scan_cluster_blocks(window, base, want_tracks, scale_ms, out):
    """Find clusters in `window` (bytes at absolute offset `base`) and collect
    subtitle block times into out[track] = [(ms, dur_ms|None)]."""
    pos = 0
    while True:
        idx = window.find(_CLUSTER_MAGIC, pos)
        if idx < 0:
            return
        buf = _Buf(window, base)
        buf.p = idx + 4
        csize, _sl = _read_vint(buf, False)
        if _sl == 0:
            return
        # Walk cluster children until the next cluster magic / window end.
        limit = buf.n if csize is None else min(buf.n, buf.p + csize)
        cluster_ts = None
        while buf.p < limit:
            # Resync guard: a new cluster can begin inside an unknown-size one.
            if window[buf.p:buf.p + 4] == _CLUSTER_MAGIC:
                break
            eid, idl = _read_vint(buf, True)
            if eid is None:
                break
            size, sl = _read_vint(buf, False)
            if sl == 0 or size is None:
                break
            if buf.p + size > buf.n:
                break   # element extends past the window -> stop this cluster
            payload = window[buf.p:buf.p + size]
            if eid == _TIMESTAMP:
                cluster_ts = _read_uint(payload)
            elif eid == _SIMPLEBLOCK and cluster_ts is not None:
                r = _parse_block(payload, cluster_ts, want_tracks)
                if r:
                    out.setdefault(r[0], []).append(
                        (r[1] * scale_ms, None))
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
                    r = _parse_block(block, cluster_ts, want_tracks)
                    if r:
                        out.setdefault(r[0], []).append(
                            (r[1] * scale_ms,
                             gdur * scale_ms if gdur else None))
            buf.p += size
        pos = buf.p if buf.p > idx + 4 else idx + 4


def _parse_head(src, head_bytes, log):
    """(segment_data_start, ts_scale_ns, sub_tracks list). Uses a sequential
    scan of the head fetch; falls back to SeekHead positions for Tracks/Info
    that live beyond it (e.g. behind a large cover attachment)."""
    head = src.read(0, head_bytes)
    buf = _Buf(head, 0)
    eid, _l = _read_vint(buf, True)
    if eid != _EBML:
        raise ValueError('not an EBML/Matroska file')
    esize, _sl = _read_vint(buf, False)
    if esize is None:
        raise ValueError('bad EBML header')
    buf.p += esize
    eid, _l = _read_vint(buf, True)
    if eid != _SEGMENT:
        raise ValueError('no Segment')
    _seg_size, _sl = _read_vint(buf, False)
    seg_start = buf.p          # segment payload start (SeekPositions base)

    ts_scale = 1000000         # ns per tick (default -> 1ms)
    duration_ticks = 0.0
    tracks = []
    seeks = {}
    p = seg_start
    while p < len(head):
        buf.p = p
        eid, idl = _read_vint(buf, True)
        if eid is None:
            break
        size, sl = _read_vint(buf, False)
        if sl == 0:
            break
        pstart = buf.p
        if eid == _CLUSTER:
            break   # media started; Info/Tracks are behind us or via SeekHead
        if size is None:
            break
        payload_in_head = pstart + size <= len(head)
        payload = head[pstart:pstart + size] if payload_in_head else b''
        if eid == _SEEKHEAD and payload_in_head:
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
        elif eid == _INFO and payload_in_head:
            ibuf = _Buf(payload, 0)
            for ieid, isize, istart in _walk(ibuf, len(payload)):
                if isize is None:
                    break
                ip = payload[istart:istart + isize]
                ibuf.p = istart + isize
                if ieid == _TS_SCALE:
                    ts_scale = _read_uint(ip) or 1000000
                elif ieid == _DURATION:
                    try:
                        duration_ticks = (struct.unpack('>f', ip)[0]
                                          if len(ip) == 4 else
                                          struct.unpack('>d', ip)[0])
                    except Exception:
                        duration_ticks = 0.0
        elif eid == _TRACKS and payload_in_head:
            tbuf = _Buf(payload, 0)
            for teid, tsize, tstart in _walk(tbuf, len(payload)):
                if tsize is None:
                    break
                tp = payload[tstart:tstart + tsize]
                tbuf.p = tstart + tsize
                if teid == _TRACKENTRY:
                    tracks.append(_parse_track_entry(tp))
        p = pstart + size

    # SeekHead fallback for sections not inside the head fetch.
    def _fetch_section(section_id, want_id):
        pos = seeks.get(section_id)
        if pos is None:
            return b''
        raw = src.read(pos, 512 * 1024)
        b2 = _Buf(raw, pos)
        eid2, _ = _read_vint(b2, True)
        size2, sl2 = _read_vint(b2, False)
        if eid2 != want_id or sl2 == 0 or size2 is None:
            return b''
        if b2.p + size2 > len(raw):
            more = src.read(pos + len(raw), size2 - (len(raw) - b2.p))
            raw += more
        return raw[b2.p:b2.p + size2]

    if not tracks:
        tp_all = _fetch_section(_TRACKS, _TRACKS)
        if tp_all:
            tbuf = _Buf(tp_all, 0)
            for teid, tsize, tstart in _walk(tbuf, len(tp_all)):
                if tsize is None:
                    break
                tp = tp_all[tstart:tstart + tsize]
                tbuf.p = tstart + tsize
                if teid == _TRACKENTRY:
                    tracks.append(_parse_track_entry(tp))

    subs = [t for t in tracks
            if t['type'] == _SUB_TRACK_TYPE and t['num'] is not None]
    log('head: %d tracks, %d subtitle track(s): %s' % (
        len(tracks), len(subs),
        ['#%s %s %s%s' % (t['num'], t['codec'], t['lang'] or '?',
                          ' FORCED' if t['forced'] else '') for t in subs]))
    duration_s = duration_ticks * ts_scale / 1e9
    return seg_start, ts_scale, tracks, duration_s


def _timeline_origin_ms(src, seg_start, scale_ms, log):
    """The file's FIRST cluster timestamp in ms -- the playback zero point.
    Some remuxes/re-encodes keep the source disc's PTS origin (field case: an
    AI-AV1 BluRay whose timestamps start at ~313s); players rebase to the
    first timestamp at play, so probe cues must be rebased the same way or
    every embedded cue looks shifted by the origin. Scans forward from the
    segment start (past Tracks/attachments) up to a small cap; 0 when not
    found (normal zero-based files are unaffected either way)."""
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
                buf = _Buf(data, pos - len(carry))
                buf.p = idx + 4
                _csize, _sl = _read_vint(buf, False)
                if _sl == 0:
                    return 0.0
                # First child of a cluster is (nearly always) its Timestamp.
                eid, _l = _read_vint(buf, True)
                size, sl = _read_vint(buf, False)
                if (eid == _TIMESTAMP and sl and size
                        and buf.p + size <= len(data)):
                    origin = _read_uint(data[buf.p:buf.p + size]) * scale_ms
                    if origin > 1000:
                        log('timeline origin: first cluster at %.1fs -- '
                            'rebasing cues' % (origin / 1000.0))
                    return float(origin)
                return 0.0
            carry = data[-4:]
            pos += len(chunk)
        return 0.0
    except Exception:
        return 0.0


def subtitle_reference(url_or_path,
                       head_bytes=DEFAULT_HEAD_BYTES,
                       window_bytes=DEFAULT_WINDOW_BYTES,
                       max_windows=DEFAULT_MAX_WINDOWS,
                       max_bytes=DEFAULT_MAX_BYTES,
                       deadline_s=DEFAULT_DEADLINE_S,
                       min_cues=25,
                       log=None):
    """Probe the file and return
        {'cues': [{'start': ms, 'end': ms}, ...],   # densest usable sub track
         'track': {...}, 'bytes': fetched, 'tracks': [all sub tracks]}
    or None when the file has no usable subtitle track / isn't Matroska.
    Never raises."""
    _log = log or (lambda m: None)
    src = None
    try:
        src = _Source(url_or_path)
        t0 = time.time()
        seg_start, ts_scale, tracks, duration_s = _parse_head(
            src, head_bytes, _log)
        subs = [t for t in tracks
                if t['type'] == _SUB_TRACK_TYPE and t['num'] is not None]
        if not subs or not src.total:
            return None
        # Only NON-FORCED tracks anchor (forced = a handful of foreign-line
        # cues), but ALL of them together: every subtitle track of the file
        # lives on the SAME timeline, so their union is a valid -- and much
        # denser -- reference (a sparse signs track alone got 9 cues in the
        # field and produced a spurious peak).
        anchor = [t for t in subs if not t.get('forced')]
        if not anchor:
            _log('only forced track(s) present -- too sparse to anchor')
            return None
        scale_ms = ts_scale / 1e6
        want = set(t['num'] for t in anchor)
        # Bitrate-aware window: on a high-bitrate BDRip a fixed 3MB window
        # covers ~2s of stream and catches ~0-1 cues; size the window to span
        # ~8s of media (capped) when the head told us the duration.
        win = window_bytes
        if duration_s > 60 and src.total:
            byterate = src.total / duration_s
            # Span ~8s of media per window, but NEVER let big windows eat the
            # whole byte budget in the first few fractions (field case: 8.4MB
            # windows hit the 40MB cap after 5 of 10 windows, so the reference
            # only covered the first ~half of the file).
            win = int(max(window_bytes,
                          min(byterate * 8, 8 * 1024 * 1024,
                              max_bytes // max(8, max_windows))))
        origin_ms = _timeline_origin_ms(
            src, seg_start, ts_scale / 1e6, _log)
        collected = {}

        def _union_count():
            seen = set()
            for lst in collected.values():
                for t, _d in lst:
                    seen.add(int(t))
            return len(seen)

        def _sample(fractions):
            for f in fractions:
                if src.fetched >= max_bytes or (time.time() - t0) > deadline_s:
                    _log('budget/deadline reached (%.1fMB, %.1fs)'
                         % (src.fetched / 1e6, time.time() - t0))
                    return
                off = max(seg_start, int(src.total * f))
                window = src.read(off, min(win, max_bytes - src.fetched))
                if not window:
                    continue
                _scan_cluster_blocks(window, off, want, scale_ms, collected)

        step = 0.86 / max(1, max_windows - 1)
        _sample([0.06 + i * step for i in range(max_windows)])
        # Adaptive top-up: still sparse and budget left -> sample the midpoints.
        if _union_count() < min_cues:
            _sample([0.06 + (i + 0.5) * step for i in range(max_windows - 1)])
        if not collected:
            _log('no subtitle blocks found')
            return None

        merged = {}
        for lst in collected.values():
            for t, d in lst:
                ti = int(t - origin_ms)   # rebase to the playback timeline
                if ti < 0:
                    continue
                if d and (ti not in merged or not merged[ti]):
                    merged[ti] = d
                else:
                    merged.setdefault(ti, None)
        pts = sorted(merged)
        cues = []
        for i, t in enumerate(pts):
            d = merged.get(t)
            if not d:
                gap = (pts[i + 1] - t) if i + 1 < len(pts) else 3000
                d = max(600, min(3000, gap - 100))
            cues.append({'start': t, 'end': t + int(d)})

        def _sanitize(t):
            return {k: v for k, v in t.items() if not isinstance(v, bytes)}

        best = max(collected, key=lambda n: len(collected[n]))
        track = next((x for x in anchor if x['num'] == best), {})
        _log('probe ok: %d cues from %d track(s) (densest #%s %s %s), '
             '%.1fMB in %.1fs (win %.1fMB)' % (
                 len(cues), len(collected), best, track.get('codec'),
                 track.get('lang') or '?', src.fetched / 1e6,
                 time.time() - t0, win / 1e6))
        return {'cues': cues, 'track': _sanitize(track),
                'tracks': [_sanitize(t) for t in subs],
                'bytes': src.fetched}
    except Exception as e:
        _log('probe failed: %r' % e)
        return None
    finally:
        if src is not None:
            src.close()


# ---- S5: audio segment extraction (demux-only, AAC -> ADTS) ------------------

def _block_frames(payload):
    """((track, rel_ts), [frame bytes...]) for a (Simple)Block payload,
    handling all lacing modes. None on malformed."""
    buf = _Buf(payload, 0)
    tnum, _l = _read_vint(buf, False)
    if tnum is None or buf.left() < 3:
        return None
    rel = struct.unpack('>h', payload[buf.p:buf.p + 2])[0]
    flags = payload[buf.p + 2]
    buf.p += 3
    lacing = (flags >> 1) & 0x03
    data = payload[buf.p:]
    if lacing == 0:
        return (tnum, rel), [data]
    if not data:
        return None
    n = data[0] + 1
    pos = 1
    sizes = []
    if lacing == 1:      # Xiph
        for _ in range(n - 1):
            s = 0
            while pos < len(data):
                s += data[pos]
                brk = data[pos] < 255
                pos += 1
                if brk:
                    break
            sizes.append(s)
    elif lacing == 2:    # fixed
        rem = len(data) - 1
        if n <= 0 or rem % n:
            return None
        sizes = [rem // n] * (n - 1)
    else:                # EBML
        b2 = _Buf(data, 0)
        b2.p = pos
        first, flen = _read_vint(b2, False)
        if first is None:
            return None
        sizes.append(first)
        prev = first
        for _ in range(n - 2):
            # signed vint delta
            start_p = b2.p
            raw, rlen = _read_vint(b2, False)
            if raw is None:
                return None
            delta = raw - ((1 << (7 * rlen - 1)) - 1)
            prev += delta
            sizes.append(prev)
        pos = b2.p
    frames = []
    off = pos
    for s in sizes:
        if off + s > len(data):
            return None
        frames.append(data[off:off + s])
        off += s
    frames.append(data[off:])   # last frame = remainder
    return (tnum, rel), frames


def _asc_adts_header(private, frame_len):
    """7-byte ADTS header for one raw AAC frame, from the track's
    AudioSpecificConfig (CodecPrivate)."""
    if len(private) < 2:
        return b''
    aot = (private[0] >> 3) & 0x1F
    freq_idx = ((private[0] & 0x07) << 1) | (private[1] >> 7)
    chan = (private[1] >> 3) & 0x0F
    if aot < 1 or aot > 4 or freq_idx > 12:
        return b''
    profile = aot - 1
    total = frame_len + 7
    return bytes([
        0xFF, 0xF1,
        (profile << 6) | (freq_idx << 2) | (chan >> 2),
        ((chan & 0x03) << 6) | ((total >> 11) & 0x03),
        (total >> 3) & 0xFF,
        ((total & 0x07) << 5) | 0x1F,
        0xFC,
    ])


def _scan_cluster_audio(window, base, tnum, scale_ms, out):
    """Collect (abs_ms, raw_frame) for audio track `tnum` from clusters found
    in `window`. Laced frames get per-frame times spaced by out['frame_dur']."""
    pos = 0
    fdur = out['frame_dur']
    while True:
        idx = window.find(_CLUSTER_MAGIC, pos)
        if idx < 0:
            return
        buf = _Buf(window, base)
        buf.p = idx + 4
        csize, _sl = _read_vint(buf, False)
        if _sl == 0:
            return
        limit = buf.n if csize is None else min(buf.n, buf.p + csize)
        cluster_ts = None
        while buf.p < limit:
            if window[buf.p:buf.p + 4] == _CLUSTER_MAGIC:
                break
            eid, idl = _read_vint(buf, True)
            if eid is None:
                break
            size, sl = _read_vint(buf, False)
            if sl == 0 or size is None:
                break
            if buf.p + size > buf.n:
                break
            payload = window[buf.p:buf.p + size]
            blk = None
            if eid == _SIMPLEBLOCK and cluster_ts is not None:
                blk = payload
            elif eid == _BLOCKGROUP and cluster_ts is not None:
                gbuf = _Buf(payload, 0)
                for geid, gsize, gstart in _walk(gbuf, len(payload)):
                    if gsize is None:
                        break
                    if geid == _BLOCK:
                        blk = payload[gstart:gstart + gsize]
                    gbuf.p = gstart + gsize
            elif eid == _TIMESTAMP:
                cluster_ts = _read_uint(payload)
            if blk is not None:
                r = _block_frames(blk)
                if r and r[0][0] == tnum:
                    t0 = (cluster_ts + r[0][1]) * scale_ms
                    for i, fr in enumerate(r[1]):
                        if fr:
                            out['frames'].append((t0 + i * fdur, fr))
            buf.p += size
        pos = buf.p if buf.p > idx + 4 else idx + 4


def audio_segments(url_or_path, seg_seconds=20, positions=(0.22, 0.50, 0.78),
                   window_bytes=6 * 1024 * 1024,
                   max_bytes=48 * 1024 * 1024,
                   deadline_s=30.0, log=None):
    """Extract 2 short CONTIGUOUS AAC audio segments from the file (demux
    only, no decoding), each wrapped as a playable ADTS stream:
        [{'start_ms': t, 'seconds': s, 'data': adts_bytes}, ...]
    Returns [] when the audio codec isn't AAC (Gemini can't take AC3/DTS and
    on-device decode is impossible) or the container is unsupported. Never
    raises."""
    _log = log or (lambda m: None)
    src = None
    try:
        src = _Source(url_or_path)
        t0 = time.time()
        seg_start, ts_scale, tracks, _dur = _parse_head(
            src, DEFAULT_HEAD_BYTES, _log)
        if not src.total:
            return []
        auds = [t for t in tracks
                if t['type'] == _AUDIO_TRACK_TYPE and t['num'] is not None]
        aac = [t for t in auds if (t['codec'] or '').startswith('A_AAC')
               and len(t['private'] or b'') >= 2 and t['samplerate'] > 0]
        _log('audio tracks: %s' % (
            ['#%s %s %.0fHz' % (t['num'], t['codec'], t['samplerate'])
             for t in auds] or '-'))
        if not aac:
            _log('no AAC audio track -- audio anchor unavailable')
            return []
        tr = aac[0]
        sr = tr['samplerate']
        frame_dur = 1024.0 / sr * 1000.0
        scale_ms = ts_scale / 1e6
        origin_ms = _timeline_origin_ms(src, seg_start, scale_ms, _log)
        segments = []
        for f in positions:
            if src.fetched >= max_bytes or (time.time() - t0) > deadline_s:
                break
            state = {'frames': [], 'frame_dur': frame_dur}
            off = max(seg_start, int(src.total * f))
            got_s = 0.0
            while (got_s < seg_seconds and src.fetched < max_bytes
                   and (time.time() - t0) <= deadline_s):
                window = src.read(off, min(window_bytes,
                                           max_bytes - src.fetched))
                if not window:
                    break
                _scan_cluster_audio(window, off, tr['num'], scale_ms, state)
                off += len(window)
                if state['frames']:
                    ts = sorted(t for t, _f in state['frames'])
                    got_s = (ts[-1] - ts[0]) / 1000.0
                if len(window) < window_bytes:
                    break   # EOF
            frames = sorted(state['frames'], key=lambda x: x[0])
            if not frames:
                continue
            # Longest CONTIGUOUS run (gaps shift every later VAD timestamp).
            runs, cur = [], [frames[0]]
            for prev, nxt in zip(frames, frames[1:]):
                if nxt[0] - prev[0] <= 3 * frame_dur:
                    cur.append(nxt)
                else:
                    runs.append(cur)
                    cur = [nxt]
            runs.append(cur)
            best = max(runs, key=len)
            need = int(seg_seconds * 1000 / frame_dur)
            best = best[:need]
            if len(best) * frame_dur < 8000:
                continue   # under ~8s of clean audio -- not worth a call
            adts = bytearray()
            for _t, fr in best:
                hdr = _asc_adts_header(tr['private'], len(fr))
                if not hdr:
                    return []
                adts += hdr + fr
            segments.append({
                'start_ms': int(max(0.0, best[0][0] - origin_ms)),
                'seconds': len(best) * frame_dur / 1000.0,
                'data': bytes(adts),
            })
        _log('audio: %d segment(s), %.1fMB fetched in %.1fs' % (
            len(segments), src.fetched / 1e6, time.time() - t0))
        return segments
    except Exception as e:
        _log('audio extraction failed: %r' % e)
        return []
    finally:
        if src is not None:
            src.close()
