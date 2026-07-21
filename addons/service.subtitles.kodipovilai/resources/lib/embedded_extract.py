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
_HEARING_IMPAIRED = 0x55AB     # FlagHearingImpaired (Matroska): 1 == SDH/CC track
_TRACKNAME = 0x536E            # TrackName: human label, often "English (SDH)" etc.
_CUES = 0x1C53BB6B
_CUE_POINT = 0xBB
_CUE_TIME = 0xB3
_CUE_TRACK_POS = 0xB7
_CUE_TRACK = 0xF7
_CUE_CLUSTER_POS = 0xF1
_CUE_RELATIVE_POS = 0xF0
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
# A debrid CDN token rate-limits by request COUNT and recovers after a short
# cooldown, so a transient 429 is EXPECTED (the relpos fast path issues many
# small requests). Back off (honor Retry-After) and retry rather than tripping
# the breaker on the first 429; only give up after exhausting retries. A small
# per-request pace keeps the burst rate under the limiter in the first place
# (the field 429 fired at ~35 req/s). Sleeping is safe -- extraction runs in a
# background thread, never the player's callback.
_HTTP_429_RETRIES = 5
_HTTP_429_MAX_WAIT = 30.0          # cap on one backoff sleep (seconds)
# A 429 means the shared token is at its limit and the PLAYER needs that
# headroom, so back off substantially (not just enough for our own retry).
_HTTP_429_BASE_WAIT = 3.0
# Gentle baseline pace. On a strict provider (TorBox) our small fast requests
# plus the player's stream tripped the per-token limit and 429'd the PLAYER,
# closing the movie. Pace hard so our added request rate stays well under the
# limit; the player-stall abort (translate.py) is the backstop if it still bites.
_HTTP_REQ_PACE_S = 0.2            # STARTING gap between range requests
_HTTP_REQ_PACE_MAX = 2.0         # ceiling: every 429 widens the gap toward this
#                                  (AIMD-style back-pressure -- we can't know a
#                                  provider's exact limit, so let the CDN's own
#                                  429s tune us down to a rate it tolerates)
# Fail-fast on a token the provider rate-limits HARD (TorBox): if this many
# fetches IN A ROW each need a 429 backoff, the token is saturated and a
# ~1700-request extraction is hopeless -- crawling on keeps the token hot for
# minutes, and the movie dies the moment the user unpauses into it. Give up
# early (~20s) with a clean deferral instead. A healthy provider (Real-Debrid)
# lands clean fetches that reset the streak, so it never trips there.
_HTTP_429_STREAK_MAX = 6
_CLUSTER_CAP_LOCAL = 32 * 1024 * 1024     # local: effectively read whole clusters
_CUES_CAP = 24 * 1024 * 1024              # hard ceiling on the Cues element read

# HTTP/debrid Cues extraction (field incident 2026-07-19: a fresh-connection-per-
# read storm 429'd the CDN token and KILLED playback). The safe shape, proven in
# the wild: ONE keep-alive connection (see _Source._sess) + single-range serial
# fetches of cluster windows, coalescing nearby cluster positions into few large
# Range requests, a circuit-breaker on the first 429/5xx, a top-up for clusters
# bigger than the window, and hard byte/time caps so a spread-out file DEFERS to
# the external path rather than fetch gigabytes alongside the player.
# Per-cluster window for the WINDOW-SCAN fallback (files whose Cues carry NO
# CueRelativePosition). 1792KB, not 512KB: his live debrid telemetry (2026-06,
# real 1080p WEB-DL) showed the TRUE cluster median ~1.51MB, p99 ~1.72MB -- the
# subtitle block sits AFTER the cluster's video keyframe, so a 512KB window
# truncated nearly every cluster and forced a top-up round-trip. 1792KB covers
# p99 in one fetch; the top-up stays as the safety net for the rare outlier.
_CLUSTER_WINDOW_HTTP = 1792 * 1024        # window-scan read per cue cluster
_CLUSTER_TOPUP_MAX = 8 * 1024 * 1024      # top-up read cap for one big cluster
_COALESCE_GAP = 1 * 1024 * 1024           # merge cluster positions within this
_MAX_RANGE = 8 * 1024 * 1024              # cap per coalesced Range request
_HTTP_TOTAL_CAP = 700 * 1024 * 1024       # give up (defer) past this many bytes
# CueRelativePosition FAST PATH (the common case: mkvmerge writes relpos by
# default). When a cue tells us the subtitle block's offset INSIDE its cluster
# we fetch just a tiny header (to resolve the cluster prefix + timestamp) and a
# small window AT the block, instead of pulling the whole ~1.5MB cluster. ~18x
# less data than the window scan -> far gentler on the player's bandwidth on a
# scattered remux, which is exactly the debrid case.
# Kept SMALL on purpose: a subtitle (Simple)Block/BlockGroup is well under 1 KB,
# so we only need a few KB at the target. The prior 16KB+128KB (~144 KB/cue) was
# wasteful THROUGHPUT that -- on a strict token (TorBox) sharing bandwidth with
# the player -- drained the player's buffer and stalled it (field, 2026-07-19,
# no 429: pure bandwidth contention). 8KB header + 32KB block = ~40 KB/cue, ~3.6x
# less. 32KB still comfortably covers a block + BlockGroup; a rare larger element
# just falls through to the window-scan for that one cue.
_CLUSTER_HDR_READ = 8 * 1024              # header read to resolve prefix + ts
_BLOCK_READ_HTTP = 32 * 1024              # window fetched AT a targeted block
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


def _new_session():
    """ONE keep-alive requests.Session (single pooled connection). This is the
    heart of debrid-safety: all Range reads reuse ONE TCP connection -- the same
    shape as the player's own single connection -- instead of storming the CDN
    with a fresh connection per read (which 429'd the token and killed playback
    in the field). None when requests isn't importable (then HTTP extraction is
    declined rather than risk a fresh-connection storm)."""
    try:
        import requests
        s = requests.Session()
        a = requests.adapters.HTTPAdapter(
            pool_connections=1, pool_maxsize=1, max_retries=1)
        s.mount('https://', a)
        s.mount('http://', a)
        return s
    except Exception:
        return None


class _Source(object):
    """Byte source with .read(offset, size) -- local file or HTTP Range. HTTP
    reads go over ONE reused keep-alive connection (see _new_session); a 429/5xx
    trips a circuit-breaker so every later read returns b'' and we back off the
    instant the CDN pushes back. Reads are hard-capped at `size`: a server that
    ignores Range (200) at a non-zero offset yields b'' rather than the file."""

    def __init__(self, url_or_path):
        self.url = url_or_path or ''
        self.is_http = bool(re.match(r'^https?://', self.url, re.I))
        self.fetched = 0
        self.reqs = 0
        self.tripped = False          # circuit-breaker: set on a 429/5xx
        self._pace = _HTTP_REQ_PACE_S  # adaptive inter-request gap (grows on 429)
        self._429_streak = 0          # consecutive 429-needing fetches (fail-fast)
        self._abort_cb = None         # set by extract_srt; polled DURING sleeps
        self.total = 0
        self._sess = _new_session() if self.is_http else None
        if not self.is_http:
            try:
                self.total = os.path.getsize(self.url)
            except Exception:
                self.total = 0
        else:
            self.total = self._http_size()

    @property
    def has_session(self):
        """A reused keep-alive connection is available. HTTP extraction requires
        this so it never storms the CDN with fresh connections."""
        return self._sess is not None

    def _http_size(self):
        try:
            if self._sess is not None:
                r = self._sess.get(
                    self.url, headers={'Range': 'bytes=0-0', 'User-Agent': _UA},
                    timeout=_HTTP_TIMEOUT, stream=True)
                cr = r.headers.get('Content-Range') or ''
                cl = r.headers.get('Content-Length')
                try:
                    r.close()
                except Exception:
                    pass
                m = re.search(r'/(\d+)\s*$', cr)
                if m:
                    return int(m.group(1))
                return int(cl) if cl else 0
        except Exception:
            return 0
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
        if self.tripped:
            return b''
        if self._sess is not None:
            return self._read_session(offset, size)
        return self._read_urllib(offset, size)

    def _sleep_or_abort(self, secs):
        """Sleep up to `secs`, in <=1s slices, polling the abort callback between
        them. Returns True the moment we're asked to stop (playback ended / the
        player stalled), so a long 429 backoff can't block us from yielding the
        token back to the player for up to two minutes."""
        import time as _t
        cb = getattr(self, '_abort_cb', None)
        remaining = secs
        while remaining > 0:
            if cb is not None:
                try:
                    if cb():
                        return True
                except Exception:
                    pass
            step = 1.0 if remaining > 1.0 else remaining
            _t.sleep(step)
            remaining -= step
        return False

    def _read_session(self, offset, size):
        """One Range GET over the SHARED keep-alive connection. Single-range,
        never multipart (a fat multi-range body starves the hardware decoder). On
        a 429/5xx we BACK OFF (honor Retry-After) and retry a few times -- a
        debrid CDN token rate-limits by request count and recovers after a short
        cooldown -- and only trip the breaker after exhausting retries. Both the
        per-request pace and the backoff are abort-aware, so a stalled player is
        noticed within ~1s instead of behind a 2-minute retry storm."""
        _pace = getattr(self, '_pace', _HTTP_REQ_PACE_S)
        self.reqs += 1
        saw_429 = False               # did THIS fetch need a 429 backoff?
        if self.reqs > 1 and _pace > 0:
            if self._sleep_or_abort(_pace):
                self.tripped = True
                return b''
        for _attempt in range(_HTTP_429_RETRIES):
            if getattr(self, '_abort_cb', None) is not None:
                try:
                    if self._abort_cb():
                        self.tripped = True
                        return b''
                except Exception:
                    pass
            r = None
            try:
                r = self._sess.get(self.url, headers={
                    'Range': 'bytes={0}-{1}'.format(offset, offset + size - 1),
                    'User-Agent': _UA}, timeout=_HTTP_TIMEOUT, stream=True)
                code = r.status_code
                if code == 429 or code >= 500:
                    saw_429 = True
                    # Back-pressure: widen the pace so we ease off the contended
                    # token (protects the player, converges toward a rate the CDN
                    # tolerates). Persists for the rest of this extraction.
                    try:
                        self._pace = min(getattr(self, '_pace', _HTTP_REQ_PACE_S)
                                         * 1.5, _HTTP_REQ_PACE_MAX)
                    except Exception:
                        pass
                    ra = r.headers.get('Retry-After')
                    try:
                        r.close()
                    except Exception:
                        pass
                    r = None
                    if _attempt >= _HTTP_429_RETRIES - 1:
                        self.tripped = True   # limiter not recovering -> give up
                        return b''
                    try:
                        wait = (min(float(ra), _HTTP_429_MAX_WAIT) if ra
                                else min(_HTTP_429_BASE_WAIT * (2 ** _attempt), _HTTP_429_MAX_WAIT))
                        # A negative / NaN / -inf Retry-After parses via float()
                        # WITHOUT raising, but then time.sleep(wait) throws -- and
                        # the outer `except Exception` would swallow it and return
                        # b'' WITHOUT ever setting self.tripped, silently killing
                        # both the backoff AND the breaker (unbounded hammering).
                        # Reject any non-finite / out-of-range value up front.
                        if not (0 <= wait <= _HTTP_429_MAX_WAIT):
                            raise ValueError
                    except (ValueError, TypeError, OverflowError):
                        wait = min(_HTTP_429_BASE_WAIT * (2 ** _attempt), _HTTP_429_MAX_WAIT)
                    if self._sleep_or_abort(wait):
                        self.tripped = True   # player needs the token -- stop now
                        return b''
                    continue
                if code == 200 and offset > 0:
                    return b''
                # Full-body fill-loop: a single r.raw.read(size) short-reads on a
                # urllib3 stream (returned 2 cues/1568 in the field); read until
                # `size` bytes or EOF, exactly like requests' own resp.content.
                buf = bytearray()
                while len(buf) < size:
                    chunk = r.raw.read(size - len(buf))
                    if not chunk:
                        break
                    buf += chunk
                data = bytes(buf)
                self.fetched += len(data)
                # Fail-fast bookkeeping: a clean fetch resets the streak; a fetch
                # that only succeeded after 429 backoff extends it. Too many in a
                # row => the token is saturated (TorBox), so trip the breaker now
                # rather than crawl for minutes with the token held hot. This
                # cue's data is still returned; the caller sees `tripped` next and
                # defers (a partial extract is never delivered anyway).
                if saw_429:
                    self._429_streak = getattr(self, '_429_streak', 0) + 1
                    if self._429_streak >= _HTTP_429_STREAK_MAX:
                        self.tripped = True
                else:
                    self._429_streak = 0
                return data
            except Exception:
                return b''
            finally:
                if r is not None:
                    try:
                        r.close()
                    except Exception:
                        pass
        return b''

    def _read_urllib(self, offset, size):
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
                return b''
            # Fill-loop (see _read_session): a single resp.read(size) may return
            # short; accumulate until `size` bytes or EOF.
            buf = bytearray()
            while len(buf) < size:
                chunk = resp.read(size - len(buf))
                if not chunk:
                    break
                buf += chunk
            resp.close()
            data = bytes(buf)
            self.fetched += len(data)
            return data
        except Exception:
            return b''


def _parse_track_entry(data):
    t = {'num': None, 'type': None, 'codec': '', 'lang': '', 'forced': False,
         'private': b'', 'name': '', 'hearing_impaired': False}
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
        elif eid == _FORCED:
            t['forced'] = bool(_read_uint(payload))
        elif eid == _HEARING_IMPAIRED:
            # Authoritative SDH flag -- no guessing. Read from the head bytes we
            # ALREADY parse for lang/codec, so it's free and works on a strict
            # debrid token (this is the cheap head read, not the full extract).
            t['hearing_impaired'] = bool(_read_uint(payload))
        elif eid == _TRACKNAME:
            t['name'] = payload.decode('utf-8', 'replace').strip('\x00')
        elif eid in (_LANG, _LANG_BCP47):
            if not t['lang']:
                t['lang'] = payload.decode('ascii', 'replace').strip('\x00')
    # Matroska spec: a TrackEntry with NO Language element IS English ('eng',
    # or 'en' for LanguageBCP47). Many upscale/anime releases omit the tag on
    # their English sub track; Kodi shows it as 'eng' for exactly this reason.
    # Without this default we are stricter than the spec and miss the very
    # track the user asked for. Record whether the tag was explicit so a track
    # that really carries 'eng' outranks one that only defaulted to it.
    t['lang_explicit'] = bool(t['lang'])
    if not t['lang']:
        t['lang'] = 'eng'
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
def _read_cues(src, seeks, seg_start, want_track, log):
    """Absolute cluster positions from the Cues index, as (positions, is_sub).
    Prefers cue points that reference `want_track` (per-track subtitle cues,
    which point straight at subtitle-bearing clusters); falls back to all cue
    positions when the file has none. ([], False) when there's no usable Cues.
    Hard-capped by _CUES_CAP so a corrupt/huge Cues size can NEVER trigger a
    multi-GB read."""
    pos = seeks.get(_CUES)
    if not pos:
        return [], False
    raw = src.read(pos, 64 * 1024)
    if not raw:
        return [], False
    b = _Buf(raw, pos)
    eid, _l = _read_vint(b, True)
    size, slen = _read_vint(b, False)
    if eid != _CUES or slen == 0 or size is None:
        return [], False
    need = b.p + size
    if need > _CUES_CAP:
        log('cues element too large (%d bytes) -- skipping' % size)
        return [], False
    while len(raw) < need:
        more = src.read(pos + len(raw), min(4 * 1024 * 1024, need - len(raw)))
        if not more:
            break
        raw += more
    b = _Buf(raw, pos)
    _read_vint(b, True)
    _read_vint(b, False)
    data = raw[b.p:b.p + size]
    want_pos, any_pos = [], []
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
            if peid != _CUE_TRACK_POS:
                continue
            ctrack, cpos, crel = None, None, None
            tbuf = _Buf(pp, 0)
            for teid, tsize, tstart in _walk(tbuf, len(pp)):
                if tsize is None:
                    break
                tp = pp[tstart:tstart + tsize]
                tbuf.p = tstart + tsize
                if teid == _CUE_TRACK:
                    ctrack = _read_uint(tp)
                elif teid == _CUE_CLUSTER_POS:
                    cpos = seg_start + _read_uint(tp)
                elif teid == _CUE_RELATIVE_POS:
                    crel = _read_uint(tp)
            if cpos is not None:
                any_pos.append((cpos, crel))
                if ctrack == want_track:
                    want_pos.append((cpos, crel))
    is_sub = bool(want_pos)
    # Keep EVERY distinct (cluster, relpos) pair. A single cluster routinely
    # holds >1 subtitle cue (two lines a couple seconds apart in fast dialogue),
    # and the relpos fast path fetches EXACTLY ONE block per relpos -- collapsing
    # them by cluster would silently drop every line but the first. A cue WITHOUT
    # relpos forces a full window-scan of its cluster (which recovers every block
    # in it), so it subsumes and REPLACES any relpos entries for the same cluster
    # (avoids fetching the same cluster twice).
    scan_only = set()          # clusters that carry a relpos-less cue
    rel_by_cpos = {}           # cpos -> set of distinct relpos values
    for cpos, crel in (want_pos if is_sub else any_pos):
        if crel is None:
            scan_only.add(cpos)
        else:
            rel_by_cpos.setdefault(cpos, set()).add(crel)
    out = []
    for cpos in sorted(scan_only | set(rel_by_cpos)):
        if cpos in scan_only:
            out.append((cpos, None))
        else:
            for relpos in sorted(rel_by_cpos[cpos]):
                out.append((cpos, relpos))
    nrel = sum(1 for _c, r in out if r is not None)
    log('cues: %d cue(s) / %d cluster(s) (%s, %d with relpos)'
        % (len(out), len(scan_only | set(rel_by_cpos)),
           'sub-track' if is_sub else 'whole-file', nrel))
    return out, is_sub


def _read_cue_times_multi(src, seeks, seg_start, want_tracks, log):
    """{track_num: SORTED distinct raw CueTime (ts_scale ticks)} for every track
    in `want_tracks`, from ONE Cues-element read. This is the read-once core: a
    subtitle file's single Cues index carries cue points for EVERY track, so N
    tracks (e.g. the cross-language align fallback trying several languages) cost
    ONE head+Cues read instead of one per track. Reads ONLY the Cues element --
    NO cluster block fetches -- so it stays a handful of range requests even on a
    huge file (viable on a strict debrid token where the full extract is not).
    CueTime is the cue's START on the segment timeline. A track with no per-cue
    index is simply absent from the result. Never raises (caller wraps)."""
    want_tracks = set(want_tracks)
    if not want_tracks:
        return {}
    pos = seeks.get(_CUES)
    if not pos:
        return {}
    raw = src.read(pos, 64 * 1024)
    if not raw:
        return {}
    b = _Buf(raw, pos)
    eid, _l = _read_vint(b, True)
    size, slen = _read_vint(b, False)
    if eid != _CUES or slen == 0 or size is None:
        return {}
    need = b.p + size
    if need > _CUES_CAP:
        log('cue-times: cues element too large (%d bytes) -- skipping' % size)
        return {}
    while len(raw) < need:
        more = src.read(pos + len(raw), min(4 * 1024 * 1024, need - len(raw)))
        if not more:
            break
        raw += more
    b = _Buf(raw, pos)
    _read_vint(b, True)
    _read_vint(b, False)
    data = raw[b.p:b.p + size]
    buckets = {t: [] for t in want_tracks}
    cbuf = _Buf(data, 0)
    for eid2, size2, start2 in _walk(cbuf, len(data)):
        if size2 is None:
            break
        cbuf.p = start2 + size2
        if eid2 != _CUE_POINT:
            continue
        cp = data[start2:start2 + size2]
        pbuf = _Buf(cp, 0)
        ctime = None
        tracks_here = set()
        for peid, psize, pstart in _walk(pbuf, len(cp)):
            if psize is None:
                break
            pp = cp[pstart:pstart + psize]
            pbuf.p = pstart + psize
            if peid == _CUE_TIME:
                ctime = _read_uint(pp)
            elif peid == _CUE_TRACK_POS:
                tbuf = _Buf(pp, 0)
                for teid, tsize, tstart in _walk(tbuf, len(pp)):
                    if tsize is None:
                        break
                    tp = pp[tstart:tstart + tsize]
                    tbuf.p = tstart + tsize
                    if teid == _CUE_TRACK:
                        tracks_here.add(_read_uint(tp))
        if ctime is None:
            continue
        # Bucket this cue's START under every WANTED subtitle track it indexes.
        # (Video-keyframe cues reference the video track, which isn't in
        # want_tracks, so they're ignored -- only per-subtitle cues mark when a
        # subtitle line appears.)
        for t in (tracks_here & want_tracks):
            buckets[t].append(ctime)
    return {t: sorted(set(v)) for t, v in buckets.items() if v}


def _read_cue_times(src, seeks, seg_start, want_track, log):
    """SORTED distinct raw CueTime values (ts_scale ticks) for `want_track`, or []
    when the file has no per-subtitle Cues index for it. Thin wrapper over the
    read-once core (`_read_cue_times_multi`) -- byte-identical parse, one track."""
    return _read_cue_times_multi(
        src, seeks, seg_start, {want_track}, log).get(want_track, [])


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


# Legitimate children of a Cluster. Inside an UNKNOWN-size cluster, ANY other id
# marks the start of the next segment-level element (the cluster has ended) --
# that's how an unbounded cluster's extent is recovered. Void/CRC-32 can appear.
_CLUSTER_CHILD_IDS = frozenset((
    _TIMESTAMP, _SIMPLEBLOCK, _BLOCKGROUP,
    0xA7,    # Position
    0xAB,    # PrevSize
    0x5854,  # SilentTracks
    0xAF,    # EncryptedBlock
    0xEC,    # Void
    0xBF,    # CRC-32
))


def _collect_one_cluster(window, want_track, out):
    """`window` starts at a Cluster element. Parse its children STRUCTURALLY (by
    declared size -- no magic-byte scan, so binary block data can never be
    mis-read as a nested cluster) and append (abs_ticks, dur_or_None, frame) for
    want_track into `out`. Returns the offset within `window` one past the
    cluster's last child (where the NEXT element begins, so an UNKNOWN-size
    cluster's true length is recoverable); `truncated` is True when parsing
    stopped because a child element ran PAST the end of `window` -- i.e. the read
    was too small and a later block (possibly a subtitle one) was NOT seen, so
    the caller must top-up rather than trust the result as complete. It is False
    on a genuine end (declared size reached, or an unbounded cluster's next
    segment-level element)."""
    b = _Buf(window, 0)
    eid, _l = _read_vint(b, True)
    if eid != _CLUSTER:
        return 0, False
    size, slen = _read_vint(b, False)
    if slen == 0:
        return 0, False
    bounded = size is not None
    limit = min(b.n, b.p + size) if bounded else b.n
    cluster_ts = None
    truncated = False
    while b.p < limit:
        child_start = b.p
        ceid, _cidl = _read_vint(b, True)
        if ceid is None:
            truncated = True   # child-id VINT cut off by the window
            b.p = child_start
            break
        if not bounded and ceid not in _CLUSTER_CHILD_IDS:
            # Unknown-size cluster: a non-child id is the next segment-level
            # element -> this cluster ends here (do NOT consume it). A genuine
            # end, NOT a truncation.
            b.p = child_start
            break
        csize, cslen = _read_vint(b, False)
        if cslen == 0 or csize is None:
            truncated = True   # child-size VINT cut off by the window
            b.p = child_start
            break
        cstart = b.p
        if cstart + csize > b.n:
            truncated = True   # this child runs past the window -> need more
            b.p = child_start
            break
        payload = window[cstart:cstart + csize]
        if ceid == _TIMESTAMP:
            cluster_ts = _read_uint(payload)
        elif ceid == _SIMPLEBLOCK and cluster_ts is not None:
            r = _block_frame(payload, cluster_ts, want_track)
            if r:
                out.append((r[0], None, r[1]))
        elif ceid == _BLOCKGROUP and cluster_ts is not None:
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
        b.p = cstart + csize
    return b.p, truncated


def _read_and_collect_cluster(src, cpos, want_track, out, cap, log):
    """Read ONE cluster at absolute offset `cpos` by its DECLARED size (capped
    at `cap` bytes -- so a subtitle block deep inside a huge cluster is the only
    thing ever missed, never memory/bandwidth) and collect want_track blocks.
    Returns the declared full cluster length (header + payload) for sequential
    advancement, or 0 when `cpos` is not a Cluster."""
    hdr = src.read(cpos, 16)
    if len(hdr) < 2:
        return 0
    hb = _Buf(hdr, 0)
    eid, _idl = _read_vint(hb, True)
    if eid != _CLUSTER:
        return 0
    size, slen = _read_vint(hb, False)
    if slen == 0:
        return 0
    hlen = hb.p
    if size is None:
        # Unknown-size cluster: read a bounded window; the structural parser
        # stops at the next segment-level element and reports where. Advance by
        # that so the walker resumes exactly at that element. If the cluster
        # fills the whole capped read (next element not seen), advance by the
        # read length (best effort).
        window = src.read(cpos, cap)
        consumed, _trunc = _collect_one_cluster(window, want_track, out)
        return consumed if 0 < consumed < len(window) else len(window)
    clen = hlen + size
    window = src.read(cpos, min(clen, cap))
    if len(window) >= hlen:
        _collect_one_cluster(window, want_track, out)
    return clen


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


def cue_reference_times(url_or_path, track_num=None, lang=None,
                        head_bytes=DEFAULT_HEAD_BYTES, allow_http=False,
                        abort_cb=None, log=None):
    """Return the embedded subtitle track's dense cue START times as a SORTED
    list of ints (milliseconds, rebased to the playback timeline), or [] when
    the file has no per-subtitle Cues index / no matching track / can't be read.

    CHEAP by design: reads ONLY the head + the Cues element + a tiny timeline-
    origin probe -- a handful of range requests, NEVER the ~1 request-per-cue
    cluster fetches that `extract_srt` needs. That makes it safe on a strict
    debrid token (e.g. TorBox) where the full-text extract starves the player.
    The returned times are the exact instants each embedded subtitle line
    appears, i.e. a dense, ground-truth timing skeleton for re-syncing an
    external subtitle. `allow_http` must be True for an HTTP/debrid source
    (default False = local only). Never raises."""
    _log = log or _noop
    try:
        src = _Source(url_or_path)
        src._abort_cb = abort_cb
        if not src.total:
            return []
        if src.is_http and not allow_http:
            _log('cue-times: HTTP not allowed (setting off) -- skipping')
            return []
        seg_start, ts_scale, tracks, seeks = _parse_head(src, head_bytes, _log)
        subs = _sub_tracks(tracks)
        if not subs:
            return []
        track = _pick_track(subs, track_num, lang)
        if track is None:
            _log('cue-times: no matching track (num=%s lang=%s)'
                 % (track_num, lang))
            return []
        raw_times = _read_cue_times(src, seeks, seg_start, track['num'], _log)
        if not raw_times:
            _log('cue-times: no per-subtitle Cues index for track #%s'
                 % track['num'])
            return []
        scale_ms = ts_scale / 1e6
        origin_ms = _timeline_origin(src, seg_start, scale_ms, _log)
        out = sorted({int(round(t * scale_ms - origin_ms)) for t in raw_times
                      if (t * scale_ms - origin_ms) >= 0})
        _log('cue-times: %d dense reference time(s) in %d req / %.0fKB'
             % (len(out), src.reqs, src.fetched / 1024.0))
        return out
    except Exception as e:
        (log or _noop)('cue_reference_times failed: %s' % e)
        return []


def cue_reference_times_multi(url_or_path, langs, track_num=None,
                              head_bytes=DEFAULT_HEAD_BYTES, allow_http=False,
                              abort_cb=None, log=None):
    """Dense cue START times for SEVERAL languages in ONE head+Cues read.

    Returns {lang: sorted_times_ms} -- the same per-language skeleton
    `cue_reference_times` returns, but computed for every language in `langs` at
    once, reading the head + Cues element + timeline origin EXACTLY ONCE and
    slicing per track (one Cues index carries every track's cue points). This is
    what the cross-language embedded-align fallback uses so trying 2-3 languages
    costs ONE read, not one per language. `langs` is normalised to 2-letter
    codes; several may resolve to the same track. A language whose track has no
    per-cue index is omitted from the result. `allow_http` must be True for an
    HTTP/debrid source. Never raises."""
    _log = log or _noop
    try:
        seen = list(dict.fromkeys(
            [str(l).lower()[:2] for l in (langs or []) if l]))
        if not seen:
            return {}
        src = _Source(url_or_path)
        src._abort_cb = abort_cb
        if not src.total:
            return {}
        if src.is_http and not allow_http:
            _log('cue-times: HTTP not allowed (setting off) -- skipping')
            return {}
        seg_start, ts_scale, tracks, seeks = _parse_head(src, head_bytes, _log)
        subs = _sub_tracks(tracks)
        if not subs:
            return {}
        # Map each requested language -> the track it selects (the SAME picker the
        # single-lang path uses); several langs can resolve to one track (e.g. the
        # sole-text-track fallback), which then serves them all from one bucket.
        lang_track = {}
        want_tracks = set()
        for lg in seen:
            tr = _pick_track(subs, track_num, lg)
            if tr is not None:
                lang_track[lg] = tr['num']
                want_tracks.add(tr['num'])
        if not want_tracks:
            _log('cue-times(multi): no matching track for langs=%s' % (seen,))
            return {}
        by_track = _read_cue_times_multi(src, seeks, seg_start, want_tracks, _log)
        if not by_track:
            _log('cue-times(multi): no per-subtitle Cues index for track(s) %s'
                 % (sorted(want_tracks),))
            return {}
        scale_ms = ts_scale / 1e6
        origin_ms = _timeline_origin(src, seg_start, scale_ms, _log)
        out = {}
        for lg, tnum in lang_track.items():
            raw_times = by_track.get(tnum)
            if not raw_times:
                continue
            out[lg] = sorted({int(round(t * scale_ms - origin_ms))
                              for t in raw_times
                              if (t * scale_ms - origin_ms) >= 0})
        _log('cue-times(multi): %d/%d lang(s) indexed in %d req / %.0fKB'
             % (len(out), len(seen), src.reqs, src.fetched / 1024.0))
        return out
    except Exception as e:
        (log or _noop)('cue_reference_times_multi failed: %s' % e)
        return {}


def extract_srt(url_or_path, track_num=None, lang=None,
                head_bytes=DEFAULT_HEAD_BYTES, max_bytes=DEFAULT_MAX_BYTES,
                deadline_s=DEFAULT_DEADLINE_S, allow_http=False,
                abort_cb=None, log=None, progress_cb=None):
    """Extract an embedded TEXT subtitle track as an SRT string.

    Pick the track by `track_num`, else by `lang` (BCP-47 prefix, e.g. 'en'
    matches 'eng'), else the first non-forced text track. Returns the SRT text,
    or None when there is no matching text track / the file has no usable Cues
    over HTTP / anything fails. NEVER raises -- the caller always has the
    external path to fall back to. `abort_cb`, if given, is polled between
    clusters; when it returns True (e.g. playback ended) extraction stops.
    `allow_http` must be True to extract from a debrid/HTTP stream (default
    False -- local-only); HTTP extraction then uses ONE keep-alive connection
    with coalesced ranges + a 429 circuit-breaker so it can't starve playback."""
    _log = log or _noop
    t0 = time.time()
    try:
        src = _Source(url_or_path)
        src._abort_cb = abort_cb   # polled DURING pace/backoff sleeps too
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
        # DEBRID SAFETY: only extract from a live HTTP stream when explicitly
        # allowed, AND only when a reused keep-alive connection is available
        # (fresh-connection-per-read storms the CDN token and kills playback).
        # Otherwise defer to the external path (which still yields AI Hebrew).
        if src.is_http:
            if not allow_http:
                _log('HTTP extraction not allowed (setting off) -- deferring')
                return None
            if not src.has_session:
                _log('no keep-alive session (requests missing) -- declining '
                     'HTTP extraction to avoid a connection storm')
                return None
        # Surgical Cues-guided fetch first (per-track subtitle cues -- fast for
        # both local and debrid HTTP). If there are none: over HTTP defer to the
        # external path; a local file gets a complete sequential walk. A partial
        # extract is NEVER delivered -- we return None so the caller falls back.
        if not _extract_cues(src, seeks, seg_start, want, entries,
                             max_bytes, deadline_s, t0, abort_cb, _log,
                             progress_cb):
            entries = []
            if src.is_http:
                return None
            if not _extract_sequential(src, seg_start, want, entries,
                                       deadline_s, t0, abort_cb, _log):
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


# ISO 639 language-code equivalences. Kodi and the subtitle providers hand us a
# 2-letter ISO 639-1 code (e.g. 'es'), but a Matroska TrackEntry's Language
# element almost always carries the 3-letter ISO 639-2/B (bibliographic) code
# (e.g. 'spa'). For ~20 languages the 2-letter code is NOT a prefix of the
# 3-letter one -- 'es'!='spa', 'de'!='ger', 'nl'!='dut', 'ja'!='jpn', 'sv'!=
# 'swe', 'el'!='gre', 'zh'!='chi', 'cs'!='cze', 'ro'!='rum', 'sk'!='slo',
# 'is'!='ice', ... -- so a naive `track_lang.startswith(pref)` SILENTLY fails to
# match the track and the embedded translation falls through to another language
# (or the wrong cache). Canonicalize BOTH the requested code and the track code
# to a single ISO 639-1 key before comparing. Each row lists every code that
# means the same language (639-1, 639-2/B, 639-2/T, plus a couple of legacy
# aliases); every code in the row maps to the row's first (2-letter) entry.
# Languages where the 2-letter code IS a prefix of the 3-letter one (en/eng,
# fr/fre, it/ita, ru/rus, pt/por, ...) still resolve -- through this table or the
# startswith() fallback that is kept as a safety net for any code not listed.
_ISO639_ROWS = (
    ('en', 'eng'), ('es', 'spa'), ('fr', 'fre', 'fra'), ('de', 'ger', 'deu'),
    ('it', 'ita'), ('pt', 'por', 'pob', 'pb'), ('nl', 'dut', 'nld'),
    ('ru', 'rus'), ('pl', 'pol'), ('cs', 'cze', 'ces'), ('sk', 'slo', 'slk'),
    ('sl', 'slv'), ('ro', 'rum', 'ron'), ('el', 'gre', 'ell'), ('hu', 'hun'),
    ('fi', 'fin'), ('sv', 'swe'), ('da', 'dan'),
    # Norwegian + Bokmal/Nynorsk all fold to 'no': the add-on never distinguishes
    # them (it always requests generic 'no'), and a track tagged 'nob'/'nno' must
    # still match a 'no' request the way the old prefix code did ('nob'.startswith
    # ('no')). Keeping them as separate canonicals would silently drop those tags.
    ('no', 'nor', 'nb', 'nob', 'nn', 'nno'),
    ('is', 'ice', 'isl'), ('tr', 'tur'), ('ar', 'ara'),
    ('he', 'heb', 'iw'), ('fa', 'per', 'fas'), ('hi', 'hin'), ('ja', 'jpn'),
    ('ko', 'kor'), ('zh', 'chi', 'zho'), ('th', 'tha'), ('vi', 'vie'),
    ('id', 'ind'), ('ms', 'may', 'msa'), ('uk', 'ukr'), ('bg', 'bul'),
    ('sr', 'srp', 'scc'), ('hr', 'hrv', 'scr'), ('bs', 'bos'),
    ('mk', 'mac', 'mkd'), ('sq', 'alb', 'sqi'), ('et', 'est'), ('lv', 'lav'),
    ('lt', 'lit'), ('ka', 'geo', 'kat'), ('hy', 'arm', 'hye'), ('az', 'aze'),
    ('kk', 'kaz'), ('eu', 'baq', 'eus'), ('gl', 'glg'), ('ca', 'cat'),
    ('cy', 'wel', 'cym'), ('ga', 'gle'), ('af', 'afr'), ('sw', 'swa'),
    ('ta', 'tam'), ('te', 'tel'), ('ml', 'mal'), ('kn', 'kan'), ('bn', 'ben'),
    ('mr', 'mar'), ('gu', 'guj'), ('pa', 'pan'), ('ur', 'urd'), ('ne', 'nep'),
    ('si', 'sin'), ('my', 'bur', 'mya'), ('km', 'khm'), ('lo', 'lao'),
    ('bo', 'tib', 'bod'), ('mn', 'mon'), ('mi', 'mao', 'mri'),
)
_ISO639_CANON = {alias: row[0] for row in _ISO639_ROWS for alias in row}


def _lang_key(code):
    """Canonical ISO 639-1 key for a language code, so 'es' and 'spa' (and 'de'/
    'ger', 'ja'/'jpn', ...) compare equal. Strips any region/script suffix
    ('pt-BR' -> 'pt', 'zh_Hans' -> 'zh') and lowercases; returns the mapped
    2-letter code, or the cleaned input when the code isn't in the table (so an
    unknown/exotic code still self-compares)."""
    c = (code or '').strip().lower()
    if not c:
        return ''
    for sep in ('-', '_'):
        if sep in c:
            c = c.split(sep, 1)[0]
    return _ISO639_CANON.get(c, c)


def _name_is_sdh(name):
    """True when a TrackName clearly marks a hearing-impaired / SDH track. Matches
    ONLY whole tokens ("english (sdh)" -> ['english','sdh']) -- never a bare
    substring, so "hi" inside "Highlander" can't match. Bare "hi"/"cc" are
    deliberately NOT markers (too ambiguous); the authoritative FlagHearingImpaired
    catches flag-tagged tracks regardless of name."""
    toks = [t for t in re.split(r'[^a-z0-9]+', (name or '').lower()) if t]
    if 'sdh' in toks:
        return True
    for i in range(len(toks) - 1):
        if toks[i] == 'hearing' and toks[i + 1] == 'impaired':
            return True
    return False


def _track_is_sdh(t):
    """A subtitle track is SDH if the authoritative Matroska flag is set, or its
    name says so. SDH tracks carry the FULL dialogue (nothing dropped for the
    hearing), so they translate more completely -- preferred by _pick_track."""
    return bool(t.get('hearing_impaired')) or _name_is_sdh(t.get('name'))


def _pick_track(subs, track_num, lang):
    if track_num is not None:
        for t in subs:
            if t['num'] == track_num:
                return t
        return None
    if lang:
        want = _lang_key(lang)
        pref = (lang or '').strip().lower()[:2]

        def _lang_match(tl):
            tl = (tl or '').strip().lower()
            if not tl:
                return False
            # Canonical ISO 639-1/2B/2T equivalence (es<->spa, de<->ger, ...).
            if want and _lang_key(tl) == want:
                return True
            # Prefix fallback ONLY for a code we don't recognise. A RECOGNISED
            # code whose canonical differs from `want` is a definitively
            # different language, so we must NOT prefix-match it -- otherwise a
            # request for 'es' would wrongly grab Estonian 'est', or 'ar' would
            # grab Armenian 'arm' (a latent bug in the old startswith-only path).
            base = tl.split('-', 1)[0].split('_', 1)[0]
            if base in _ISO639_CANON:
                return False
            return bool(pref) and tl.startswith(pref)

        # Forced/signs-only tracks are excluded from auto-pick (same rule as the
        # no-lang branch below): a sparse signs-only sub is a worse deliverable
        # than falling through to the external subtitle search. This matters now
        # that an untagged forced track defaults to 'eng' and would otherwise
        # match the prefix.
        cand = [t for t in subs if _is_text_codec(t['codec'])
                and not t['forced']
                and _lang_match(t['lang'])]
        # Order among matched tracks: (1) an explicitly-tagged language beats one
        # that only defaulted to 'eng' (stronger language-confidence); (2) among
        # equally-tagged tracks prefer the SDH/hearing-impaired one -- it has the
        # complete dialogue, so it translates more fully (and, later, is the best
        # gender source); (3) then track order.
        cand.sort(key=lambda t: (not t.get('lang_explicit', True),
                                 not _track_is_sdh(t), t['num']))
        if cand:
            return cand[0]
        # No language match. When the file carries exactly ONE non-forced text
        # track it is almost certainly the stream Kodi surfaced (its tag may be
        # 'und' or otherwise not our prefix); use it rather than failing the
        # whole extraction -- BUT only when that lone track's language is genuinely
        # unknown, not when it is explicitly a DIFFERENT known language. Handing
        # back an explicit 'eng' text track for a Spanish request (e.g. the file's
        # only text sub is English while the Spanish track is a bitmap PGS) would
        # mislabel the source language and translate the wrong text. A tag is
        # "genuinely unknown" when it isn't a recognised ISO code (und/mis/...) OR
        # it only DEFAULTED to 'eng' (absent Language element, lang_explicit=False)
        # -- that track's real language is unknown, so it stays eligible.
        texts = [t for t in subs
                 if _is_text_codec(t['codec']) and not t['forced']]
        if len(texts) == 1:
            only = texts[0]
            tl = (only['lang'] or '').strip().lower()
            base = tl.split('-', 1)[0].split('_', 1)[0]
            # We only reach here when `only` did NOT lang-match (a matching track
            # would already have been returned via `cand` above). Use it anyway
            # when its language is genuinely unknown -- an unrecognised tag
            # (und/mis/...) or one that merely DEFAULTED to 'eng' (absent Language
            # element, lang_explicit=False) -- but NOT when it is an explicit,
            # recognised, DIFFERENT language (that would mislabel the source).
            if base not in _ISO639_CANON or not only.get('lang_explicit', True):
                return only
        return None
    cand = [t for t in subs if _is_text_codec(t['codec']) and not t['forced']]
    cand.sort(key=lambda t: (not _track_is_sdh(t), t['num']))   # SDH first, then order
    return cand[0] if cand else None


def _extract_sequential(src, seg_start, want, entries, deadline_s, t0,
                        abort_cb, log):
    """Walk the segment element-by-element on a seekable source, reading each
    Cluster in full by its DECLARED size (no chunk-straddle loss) and skipping
    every non-cluster element. Used for local files. Returns True if it reached
    EOF (complete), False if a deadline/abort cut it short (caller returns None
    so a partial extract is never delivered)."""
    pos = seg_start
    total = src.total
    while pos < total:
        if (time.time() - t0) > deadline_s:
            log('sequential extract deadline reached -- incomplete')
            return False
        if _aborted(abort_cb):
            log('sequential extract aborted (playback ended) -- incomplete')
            return False
        hdr = src.read(pos, 16)
        if len(hdr) < 2:
            break
        hb = _Buf(hdr, 0)
        eid, _idl = _read_vint(hb, True)
        if eid is None:
            break
        size, slen = _read_vint(hb, False)
        if slen == 0:
            break
        hlen = hb.p
        if eid == _CLUSTER:
            # Route to the cluster reader FIRST -- it handles unknown-size
            # clusters (size is None), which are legitimate EBML; bailing on
            # size-None here would silently truncate the file.
            clen = _read_and_collect_cluster(
                src, pos, want, entries, _CLUSTER_CAP_LOCAL, log)
            if clen <= 0:
                break
            pos += clen
        else:
            if size is None:
                break   # unknown-size non-cluster element: can't skip reliably
            pos += hlen + size
    return True


def _coalesce_ranges(positions, window, gap, max_range, total):
    """Group sorted cluster positions into (start, end, [positions]) sweep
    ranges: each covers ~`window` bytes per cluster, and adjacent positions
    within `gap` share ONE Range request (his proven request-count cut). Capped
    at `max_range` per range and the file size."""
    ranges = []
    ps = sorted(set(positions))
    if not ps:
        return ranges
    cap = total or (ps[-1] + window)
    cur_start = ps[0]
    cur_end = cur_start + window
    cur = [cur_start]
    for p in ps[1:]:
        if p < cur_end + gap and (p + window - cur_start) <= max_range:
            cur_end = max(cur_end, p + window)
            cur.append(p)
        else:
            ranges.append((cur_start, min(cur_end, cap), cur))
            cur_start, cur_end, cur = p, p + window, [p]
    ranges.append((cur_start, min(cur_end, cap), cur))
    return ranges


def _extract_cues(src, seeks, seg_start, want, entries,
                  max_bytes, deadline_s, t0, abort_cb, log, progress_cb=None):
    """Cues-guided extraction from per-track SUBTITLE cues. Local visits each
    cluster directly; HTTP uses coalesced sweep-ranges over the single keep-alive
    connection with a 429 circuit-breaker. Returns True only on a COMPLETE pass;
    False (no sub cues / breaker / budget / abort) -> the caller defers to the
    external path (HTTP) or a full sequential walk (local)."""
    positions, is_sub = _read_cues(src, seeks, seg_start, want, log)
    if not positions:
        return False
    if not is_sub:
        # Whole-file/video cues don't point at subtitle blocks, so a capped
        # per-cluster fetch would risk missing lines. Defer.
        log('no per-subtitle Cues -- deferring (avoid a partial extract)')
        return False
    if not src.is_http:
        # positions can now list a cluster more than once (one entry per relpos);
        # a local full-cluster parse recovers every block, so visit each cpos ONCE.
        seen_local = set()
        for cpos, _rel in positions:
            if cpos in seen_local:
                continue
            seen_local.add(cpos)
            if (time.time() - t0) > deadline_s or _aborted(abort_cb):
                return False
            _read_and_collect_cluster(
                src, cpos, want, entries, _CLUSTER_CAP_LOCAL, log)
        return True
    return _extract_cues_http(src, positions, entries, want, deadline_s, t0,
                              abort_cb, log, progress_cb)


def _cluster_prefix_and_ts(header):
    """From bytes that START at a Cluster element, return (prefix_len,
    cluster_ts). `prefix_len` = Cluster-ID length + Size-VINT length -- the byte
    distance from the cluster start to the first octet of cluster DATA, which is
    exactly what CueRelativePosition is measured from. `cluster_ts` = the
    cluster's Timestamp (its first child; a small header read always contains
    it). (None, None) when the bytes don't start with a Cluster or are too
    short to resolve both."""
    b = _Buf(header, 0)
    eid, idlen = _read_vint(b, True)
    if eid != _CLUSTER or idlen == 0:
        return None, None
    size, slen = _read_vint(b, False)   # size may be None (unknown-size) -- ok
    if slen == 0:
        return None, None
    prefix = idlen + slen
    cluster_ts = None
    limit = b.n if size is None else min(b.n, b.p + size)
    while b.p < limit:
        ceid, _cidl = _read_vint(b, True)
        if ceid is None:
            break
        csize, cslen = _read_vint(b, False)
        if cslen == 0 or csize is None:
            break
        cst = b.p
        if cst + csize > b.n:
            break
        if ceid == _TIMESTAMP:
            cluster_ts = _read_uint(header[cst:cst + csize])
            break
        b.p = cst + csize
    if cluster_ts is None:
        return None, None
    return prefix, cluster_ts


def _collect_one_block(window, want_track, cluster_ts, out):
    """Parse ONE (Simple)Block or BlockGroup element at the START of `window` (a
    CueRelativePosition target). Append (abs_ticks, dur_or_None, frame) when it
    carries want_track. Returns True when a want_track block was found & appended;
    False when the element is truncated by the window OR is not want_track's block
    (the caller then falls back to a full window-scan of the cluster, so a mis-
    resolved target never silently drops a line)."""
    b = _Buf(window, 0)
    eid, _l = _read_vint(b, True)
    if eid is None:
        return False
    size, slen = _read_vint(b, False)
    if slen == 0 or size is None:
        return False
    if b.p + size > b.n:
        return False   # element runs past the window -> truncated
    payload = window[b.p:b.p + size]
    if eid == _SIMPLEBLOCK:
        r = _block_frame(payload, cluster_ts, want_track)
        if r:
            out.append((r[0], None, r[1]))
            return True
        return False
    if eid == _BLOCKGROUP:
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
                return True
        return False
    return False


def _fetch_targeted_block(src, cpos, relpos, want, entries, log):
    """CueRelativePosition FAST PATH: fetch just the subtitle block. A tiny
    header read resolves the cluster prefix + Timestamp; the block then sits at
    cpos + prefix + relpos, so we fetch a small window THERE (reusing header
    bytes if the block already fell inside them). ~18x less data than pulling
    the whole ~1.5MB cluster. Returns True when the block was located & parsed,
    False when the cue couldn't be resolved (caller window-scans it as a net)."""
    header = src.read(cpos, _CLUSTER_HDR_READ)
    if src.tripped or not header:
        return False
    prefix, cluster_ts = _cluster_prefix_and_ts(header)
    if prefix is None:
        return False
    target = cpos + prefix + relpos
    if cpos <= target < cpos + len(header):
        if _collect_one_block(header[target - cpos:], want, cluster_ts, entries):
            return True   # block already inside the header read
    if src.fetched >= _HTTP_TOTAL_CAP:
        return False
    blk = src.read(target, min(_BLOCK_READ_HTTP, _HTTP_TOTAL_CAP - src.fetched))
    if src.tripped or not blk:
        return False
    return _collect_one_block(blk, want, cluster_ts, entries)


def _extract_cues_http(src, positions, entries, want, deadline_s, t0, abort_cb,
                       log, progress_cb=None):
    """HTTP/debrid: ONE keep-alive connection, single-range serial. Per cue,
    two strategies chosen by whether the Cues carried a CueRelativePosition:
      * relpos present -> TARGETED: tiny header read + a small window AT the
        subtitle block. ~18x less data than a full cluster -- gentle on the
        player's bandwidth over a scattered remux (the debrid case).
      * relpos absent  -> WINDOW SCAN: fetch a ~1.79MB window at the cluster
        start and parse forward (his proven fallback), topping up the rare
        cluster bigger than the window.
    Player-safe by construction (single serial connection, byte/time caps, 429
    circuit-breaker). Returns True on a COMPLETE pass, False to defer."""
    budget = max(deadline_s, 90.0)
    rel_cues = [(c, r) for (c, r) in positions if r is not None]
    scan_cues = [c for (c, r) in positions if r is None]
    total = len(positions)
    log('%d sub-cue cluster(s): %d targeted (relpos) + %d window-scan; '
        'caps %dMB / %.0fs'
        % (total, len(rel_cues), len(scan_cues),
           _HTTP_TOTAL_CAP // (1 << 20), budget))

    def _defer():
        """Return a reason string when we must stop, else None."""
        if src.tripped:
            return 'circuit-breaker tripped (CDN 429/5xx)'
        if src.fetched >= _HTTP_TOTAL_CAP:
            return 'http byte cap reached (%.0fMB)' % (src.fetched / 1e6)
        if (time.time() - t0) > budget:
            return 'http time budget reached (%.0fs)' % (time.time() - t0)
        if _aborted(abort_cb):
            return 'http extract aborted (playback ended)'
        return None

    def _tick(n):
        """Report progress to the UI (throttled). Never fatal."""
        if progress_cb:
            try:
                progress_cb(min(n, total), total)
            except Exception:
                pass

    done = 0
    # 1) targeted relpos fetches
    for (cpos, relpos) in rel_cues:
        reason = _defer()
        if reason:
            log(reason + ' -- deferring')
            return False
        if not _fetch_targeted_block(src, cpos, relpos, want, entries, log):
            if src.tripped:
                log('circuit-breaker tripped mid-fetch -- deferring')
                return False
            # Couldn't resolve the block from relpos (odd prefix / short read /
            # wrong track) -> window-scan THIS cue so we never drop a line.
            scan_cues.append(cpos)
        done += 1
        if done % 100 == 0:
            log('extract progress: %d/%d cue(s), %.0fMB'
                % (done, total, src.fetched / 1e6))
        if done % 10 == 0:
            _tick(done)

    # 2) window-scan the remainder (no-relpos cues + any relpos misses)
    if scan_cues:
        ranges = _coalesce_ranges(sorted(set(scan_cues)), _CLUSTER_WINDOW_HTTP,
                                  _COALESCE_GAP, _MAX_RANGE, src.total)
        for (rstart, rend, cposes) in ranges:
            reason = _defer()
            if reason:
                log(reason + ' -- deferring')
                return False
            window = src.read(rstart,
                              min(rend - rstart, _HTTP_TOTAL_CAP - src.fetched))
            if src.tripped:
                log('circuit-breaker tripped mid-fetch -- deferring')
                return False
            if not window:
                continue
            for cpos in cposes:
                if src.tripped:
                    break
                off = cpos - rstart
                if not (0 <= off < len(window)):
                    continue
                _end, truncated = _collect_one_cluster(window[off:], want, entries)
                if not truncated:
                    continue
                # Window too small for this cluster (a big co-located video/audio
                # block sits around the subtitle one) -> a LATER subtitle block
                # was not seen. Top-up the whole cluster; dedup in _entries_to_srt
                # drops any re-parsed block. STILL truncated -> DEFER (never
                # deliver a silently-partial subtitle).
                if src.fetched >= _HTTP_TOTAL_CAP:
                    log('byte cap reached at top-up -- deferring')
                    return False
                tup = src.read(cpos, min(_CLUSTER_TOPUP_MAX,
                                         _HTTP_TOTAL_CAP - src.fetched))
                if src.tripped:
                    log('circuit-breaker tripped during top-up -- deferring')
                    return False
                _tend, tup_trunc = _collect_one_cluster(tup, want, entries)
                if tup_trunc:
                    log('cluster exceeds top-up cap (%dMB) -- deferring to avoid '
                        'a partial subtitle' % (_CLUSTER_TOPUP_MAX >> 20))
                    return False
            done += len(cposes)
            _tick(done)

    if src.tripped:
        log('circuit-breaker tripped -- deferring')
        return False
    if progress_cb:
        _tick(total)   # 100% on a complete pass
    return True
