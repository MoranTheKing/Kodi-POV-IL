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
_LANG = 0x22B59C
_LANG_BCP47 = 0x22B59D
_FORCED = 0x55AA
_CLUSTER = 0x1F43B675
_CLUSTER_MAGIC = b'\x1f\x43\xb6\x75'
_TIMESTAMP = 0xE7
_SIMPLEBLOCK = 0xA3
_BLOCKGROUP = 0xA0
_BLOCK = 0xA1
_BLOCKDUR = 0x9B

_SUB_TRACK_TYPE = 0x11

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
    t = {'num': None, 'type': None, 'codec': '', 'lang': '', 'forced': False}
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
        elif eid in (_LANG, _LANG_BCP47):
            if not t['lang']:
                t['lang'] = payload.decode('ascii', 'replace').strip('\x00')
        elif eid == _FORCED:
            t['forced'] = bool(_read_uint(payload))
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
    return seg_start, ts_scale, subs


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
        seg_start, ts_scale, subs = _parse_head(src, head_bytes, _log)
        if not subs or not src.total:
            return None
        scale_ms = ts_scale / 1e6
        want = set(t['num'] for t in subs)
        collected = {}
        fractions = [0.06 + i * (0.86 / max(1, max_windows - 1))
                     for i in range(max_windows)]
        for f in fractions:
            if src.fetched >= max_bytes or (time.time() - t0) > deadline_s:
                _log('budget/deadline reached (%.1fMB, %.1fs)'
                     % (src.fetched / 1e6, time.time() - t0))
                break
            off = max(seg_start, int(src.total * f))
            window = src.read(off, min(window_bytes,
                                       max_bytes - src.fetched))
            if not window:
                continue
            _scan_cluster_blocks(window, off, want, scale_ms, collected)
            best_n = max((len(v) for v in collected.values()), default=0)
            if best_n >= min_cues and f > 0.7:
                break   # enough spread + enough cues
        if not collected:
            _log('no subtitle blocks found in %d windows' % len(fractions))
            return None

        def _track_score(tnum):
            t = next((x for x in subs if x['num'] == tnum), {})
            n = len(collected.get(tnum, ()))
            return (0 if t.get('forced') else 1, n)

        best = max(collected, key=_track_score)
        track = next((x for x in subs if x['num'] == best), {})
        if track.get('forced'):
            _log('only forced track(s) found -- too sparse to anchor')
            return None
        pts = sorted(set(int(t) for t, _d in collected[best]))
        durs = {int(t): d for t, d in collected[best] if d}
        cues = []
        for i, t in enumerate(pts):
            d = durs.get(t)
            if not d:
                gap = (pts[i + 1] - t) if i + 1 < len(pts) else 3000
                d = max(600, min(3000, gap - 100))
            cues.append({'start': t, 'end': t + int(d)})
        _log('probe ok: track #%s (%s %s) %d cues, %.1fMB in %.1fs' % (
            best, track.get('codec'), track.get('lang') or '?', len(cues),
            src.fetched / 1e6, time.time() - t0))
        return {'cues': cues, 'track': track, 'tracks': subs,
                'bytes': src.fetched}
    except Exception as e:
        _log('probe failed: %r' % e)
        return None
    finally:
        if src is not None:
            src.close()
