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
import threading as _threading
import time

try:
    import urllib.request as _urlreq
except Exception:  # pragma: no cover - urllib always present on CPython 3
    _urlreq = None

import json as _json


def _pace_memory_path():
    """Where the per-provider pace memory lives, or '' when there is no Kodi to
    ask (tests, tooling). Never raises."""
    try:
        import xbmcaddon
        import xbmcvfs
        prof = xbmcvfs.translatePath(
            xbmcaddon.Addon().getAddonInfo('profile')) or ''
    except Exception:
        return ''
    if not prof:
        return ''
    try:
        if not os.path.isdir(prof):
            os.makedirs(prof)
    except OSError:
        return ''
    return os.path.join(prof, _PACE_MEMORY_FILE)


def _provider_key(url):
    """The last two labels of the host: one debrid provider hands out many
    per-store hostnames (store-033.wnam.tb-cdn.io, store-027.wnam.tb-cdn.io) and
    they all draw on the SAME token bucket, so they must share one memory."""
    m = re.match(r'^https?://([^/:?#]+)', url or '', re.I)
    if not m:
        return ''
    labels = [p for p in m.group(1).lower().split('.') if p]
    return '.'.join(labels[-2:]) if len(labels) >= 2 else ''


def _pace_memory_load(url):
    """The pace to START this run at: last run's, probed 25% faster, clamped so
    it can never be below the normal starting pace. None when we know nothing."""
    key = _provider_key(url)
    path = _pace_memory_path()
    if not key or not path or not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = _json.loads(f.read()) or {}
        saved = float((data.get('hosts') or {}).get(key))
    except (IOError, OSError, ValueError, TypeError):
        return None
    if not (saved == saved) or saved <= 0:      # NaN / nonsense -> know nothing
        return None
    probe = saved * _PACE_MEMORY_PROBE
    if probe <= _HTTP_REQ_PACE_S:
        return None                              # nothing to remember: start normal
    return min(probe, _HTTP_REQ_PACE_MAX)


def _pace_memory_save(url, pace, reqs):
    """Record the pace this run ended on. Best-effort and silent."""
    key = _provider_key(url)
    path = _pace_memory_path()
    if not key or not path or reqs < _PACE_MEMORY_MIN_REQS:
        return
    try:
        pace = float(pace)
    except (TypeError, ValueError):
        return
    if not (pace == pace) or pace <= 0:
        return
    pace = max(_HTTP_REQ_PACE_S, min(pace, _HTTP_REQ_PACE_MAX))
    try:
        data = {}
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.loads(f.read()) or {}
        hosts = data.get('hosts')
        if not isinstance(hosts, dict):
            hosts = {}
        order = [h for h in (data.get('order') or []) if h in hosts]
        hosts[key] = round(pace, 3)
        order = [h for h in order if h != key] + [key]
        while len(order) > _PACE_MEMORY_MAX_HOSTS:
            hosts.pop(order.pop(0), None)
        tmp = path + '.aitmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(_json.dumps({'hosts': hosts, 'order': order}))
        os.replace(tmp, path)
    except (IOError, OSError, ValueError, TypeError):
        try:
            os.remove(path + '.aitmp')
        except OSError:
            pass

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
# The EOF probe reads only the first few bytes of its answer, but leaving the
# rest unread forces the shared keep-alive connection to be thrown away and
# rebuilt on the next read -- and storming a debrid CDN with fresh connections
# is what 429s the token. So finish a body that is small enough to finish, and
# only abandon one too big to bother with (a provider that ignores Range answers
# with the whole file, which can be tens of gigabytes).
_PROBE_DRAIN_MAX = 64 * 1024
# The probe asks for a range STARTING at bytes we already hold and running past
# the point in question, so the provider has to answer a satisfiable range --
# the one form of the question it is obliged to answer precisely. _PROBE_CONTROL
# is how much known data it starts from (long enough that a provider serving the
# wrong region cannot match it by chance, short enough to be free) and
# _PROBE_AHEAD is how far past the point it reaches.
_PROBE_CONTROL = 64
_PROBE_AHEAD = 16
# A debrid CDN token rate-limits by request COUNT and recovers after a short
# cooldown, so a transient 429 is EXPECTED (the relpos fast path issues many
# small requests). Back off (honor Retry-After) and retry rather than tripping
# the breaker on the first 429; only give up after exhausting retries. A small
# per-request pace keeps the burst rate under the limiter in the first place
# (the field 429 fired at ~35 req/s). Sleeping is safe -- extraction runs in a
# background thread, never the player's callback.
_HTTP_429_RETRIES = 5
# NOT reduced under sustained pressure, though it is tempting: retrying a read
# in place costs a fresh GET each time, so a run against a pushing-back CDN
# sends far more requests than it appears to (a field log's "60 req" was nearer
# 110 as far as the CDN was concerned -- hence the http_reqs counter). But
# exhausting these retries is exactly what trips the breaker, and that trip is
# what keeps a partial extract from being delivered. Measured: cutting them to 2
# sent 84% fewer requests and returned 0 of 50 cues.
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
# ...and the other half of AIMD, which was missing: the gap only ever GREW. One
# 429 near the start left every remaining request paying for it, and a burst of
# them pinned the pace at the 2.0s ceiling for the rest of the extraction -- ~28
# minutes of pure sleeping over 850 cues, on a provider that may well have
# recovered seconds later. So decay the gap back down after a clean run of
# requests.
# The floor is the STARTING pace, deliberately -- this recovers from back-
# pressure, it does NOT probe for the provider's real limit. 0.2s was chosen
# from a field incident where our request rate 429'd the PLAYER's own stream and
# CLOSED the movie; going below it to shave minutes off a lenient provider would
# risk exactly that on a strict one, and "works on every provider" is the point.
# So the pace stays inside [start, max] just as before -- it can simply come
# back now. Recovery is slower than back-off on purpose (0.9x per 25 clean
# requests vs 1.5x per 429): pacing too slow costs time, pacing too fast costs
# the movie.
_HTTP_PACE_DECAY = 0.85           # multiplier applied after a clean run
_HTTP_PACE_DECAY_AFTER = 12       # ...that many consecutive clean requests

# ONE congestion event must widen the pace ONCE.
#
# This is the bug that made every TorBox extraction crawl, and it is a textbook
# one. AIMD's multiplicative decrease belongs to a congestion EPOCH -- TCP halves
# the window once per round trip and deliberately ignores every further loss in
# that window, because those losses are the same event, reported again. We were
# multiplying per 429 RESPONSE. Since a single fetch retries up to
# _HTTP_429_RETRIES times and each retry that answers 429 backed off again, one
# unlucky cluster could multiply the pace by 1.5^5 = 7.6x on its own.
#
# Field log 63addde9 (Rick and Morty S06E07, BluRay REMUX, 364 cues):
#     18:16:16  first 429 after 68 requests   pace 0.20s -> 0.30s
#     18:16:49  SIXTH 429, 27 requests later  pace 1.52s -> 2.00s  (the ceiling)
# Thirty-three seconds of one congestion event, counted six times, and the run
# spent the next four minutes at the 2.00s ceiling doing 143 of 364 cues. The
# proof it was overshoot and not a genuinely slow provider is in the same log:
#     18:20:02  CDN quiet for 25 request(s) -- pace 2.00s -> 1.80s
# Twenty-five consecutive CLEAN requests at 2.00s. The tolerated pace was far
# below the ceiling we pinned ourselves to.
#
# So: after widening, refuse to widen again until we have actually MEASURED the
# new pace -- both a minimum number of completed requests and a minimum elapsed
# time at it. 429s inside that window are still honoured (Retry-After, backoff,
# retry, the streak breaker); they simply do not re-punish a pace whose effect
# is not known yet. If the new pace is genuinely still too fast, the next 429
# after the window widens it again -- which is the controller doing its job
# instead of free-falling to the ceiling on the first burst.
_HTTP_PACE_EPOCH_REQS = 8         # requests to complete before widening again
_HTTP_PACE_EPOCH_S = 5.0          # ...and seconds to elapse, whichever is later

# Remember what each provider tolerated, so we stop rediscovering it every time.
#
# The epoch fix above stops one congestion event from being punished six times,
# but every extraction still STARTS at 0.20s -- ~5 requests a second, above any
# plausible debrid sustained rate. A token bucket hides that: field log 63addde9
# shows 68 requests sailing through before the first refusal. So each run spends
# its burst allowance, hits the wall, and pays the whole climb again. That is why
# this has needed fixing over and over: the controller had no memory, so every
# episode re-learned the same lesson from zero.
#
# Now the pace a run converged on is written per provider (the last two labels of
# the host, so store-033.wnam.tb-cdn.io and store-027.wnam.tb-cdn.io are the same
# provider) and the next run starts there -- but 25% faster, so it keeps probing
# and a single bad night decays away over a few runs instead of pinning us slow
# forever. It can only ever start at or ABOVE _HTTP_REQ_PACE_S, never below, so
# no remembered value can make us hit a provider harder than a fresh install
# would; the worst case is starting slower than necessary and letting the normal
# decay walk it back.
_PACE_MEMORY_FILE = 'embedded_pace.json'
_PACE_MEMORY_PROBE = 0.75         # start this fraction of last time's pace
_PACE_MEMORY_MAX_HOSTS = 16       # keep the file small; drop the oldest
_PACE_MEMORY_MIN_REQS = 20        # too short a run tells us nothing -- don't save

# How many keep-alive connections the targeted (relpos) fetches may use at once.
#
# The extraction was never bandwidth-bound -- it was LATENCY-bound. One
# connection, one request at a time: pace (0.2s) + a debrid round trip (~0.35s)
# = ~0.55s per cue, and an episode's ~450 cues took about four minutes with the
# link sitting idle for most of it.
#
# The important part is what this does NOT change: the request RATE. The pace
# gate below is now shared by every connection, so the CDN still sees at most
# one request per `_pace` seconds no matter how many are in flight -- exactly
# the rate the AIMD controller converged on when it was serial. Concurrency
# only stops us paying the round trip on top of the gap we were already
# waiting. A 429 still widens the pace for everyone at once, and the
# circuit-breaker is still shared, so pushback stops all of them together.
#
# DEFAULT 1 -- OFF. The field settled this, and it settled it against me.
#
# The reasoning above has a hole, and TorBox found it in under thirty seconds.
# Keeping the same PACED SCHEDULE is not the same as keeping the same request
# RATE. Serially we asked once every pace + round trip (0.2 + 0.35 = ~1.8/s);
# with three connections the round trip stops counting and we ask once every
# pace (5/s). That IS the speedup -- a latency-bound loop cannot be made faster
# without asking more often -- and it is also three times the load, which is
# exactly what a debrid token rate-limits.
#
# What the field log showed (Rick and Morty S03E05, 572 cues): concurrency ran
# for 29 seconds, collected 5 backoffs, stood down as designed -- and by then the
# AIMD controller had ratcheted the pace from 0.20s to its 2.00s ceiling. The
# pace decays only after 25 consecutive clean requests, so recovering from that
# takes hundreds of them. The extraction was left crawling at ten times its
# normal gap: about nineteen minutes for an episode that used to take four. The
# safety machinery all worked; it just could not undo the damage the burst had
# already done.
#
# So concurrency is off until there is a provider it can be shown to help on,
# measured against that provider rather than against a stand-in. Everything it
# needs is still here and still tested -- set this to 3 to run it -- and the
# stand-down now also puts the pace back where it found it (see below), so a
# burst can no longer poison the rest of the run.
_HTTP_CONNS = 1

# Clusters fetched one at a time before the concurrent phase may start (see
# _healthy). Two is the normal cost; the third is slack for a file that needs
# one more before its CueTime can be proven.
_CONC_SEED_MAX = 3
# Fail-fast on a token the provider rate-limits HARD (TorBox): if this many
# fetches IN A ROW each need a 429 backoff, the token is saturated and a
# ~1700-request extraction is hopeless -- crawling on keeps the token hot for
# minutes, and the movie dies the moment the user unpauses into it. Give up
# early (~20s) with a clean deferral instead. A healthy provider (Real-Debrid)
# lands clean fetches that reset the streak, so it never trips there.
_HTTP_429_STREAK_MAX = 6
# ...and, with that streak reached, how long we must have collected NOTHING
# NEW before giving up. Back-pressure alone is not saturation: a provider can
# refuse half our reads while the player runs perfectly and cues keep landing,
# and abandoning there costs the user a whole play session for nothing now that
# progress is banked. Genuine saturation stops the cues, and this notices.
_STALLED_PROGRESS_S = 45.0
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
# ONE-SHOT ceiling. When a header read IS needed, size it to swallow the first
# block too if that is cheap -- one request instead of two. Only bites on files
# whose subtitle block precedes the cluster's video keyframe; measured on a
# realistic remux the relpos is ~0.4-1.5MB, so this rarely fires and the header
# elimination below is what actually removes the second request.
_ONE_SHOT_MAX = 128 * 1024
# HEADER ELIMINATION. Measured (synthetic remux, 40 clusters x 1-3 subtitle
# cues): 2.03-2.10 range requests PER CUE, because each cue paid an 8KB read at
# the cluster start purely to learn two things -- the cluster PREFIX (Cluster-ID
# length + size-VINT length, the origin CueRelativePosition is measured from)
# and the cluster TIMESTAMP. Neither has to be re-read:
#   * the prefix is a property of the MUXER, not of the cluster -- one file's
#     clusters are all within one size-VINT width of each other, so it is
#     learned once and reused;
#   * the absolute timestamp is ALREADY in the Cues index, as CueTime.
# Both are assumptions about a third party's file, so neither is trusted on
# faith: the first cluster is still read the old way and the two answers are
# CHECKED against it, and any later block that fails to parse falls back to a
# header read for that cluster (and re-learns) before the cue is handed to the
# window-scan net. Worst case is today's cost; typical case is half of it.
_PREFIX_MIN = 5                 # 4-byte Cluster ID + 1-byte size VINT
_PREFIX_MAX = 12                # 4-byte Cluster ID + 8-byte size VINT
# Two subtitle blocks in ONE cluster share a read when they sit this close. Kept
# deliberately small: a muxer interleaves by timestamp, so a cluster's subtitle
# blocks are typically HUNDREDS of KB apart, and pulling the video between them
# to save one request would trade a round-trip for bandwidth the player needs
# (field 2026-07-19 was a pure bandwidth-contention stall, no 429 at all).
_CLUSTER_BATCH_MAX = 96 * 1024
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
        # Retry TRANSPORT errors, never STATUS ones. urllib3's Retry honours
        # Retry-After for 413/429/503 by default, so a plain `max_retries=1`
        # made it swallow the CDN's 429 -- sleep for the header's duration and
        # replay the request -- BEFORE our code ever saw the status. Measured on
        # the local CDN stand-in: 15 server-side 429s, `_429_total` still 0. That
        # silently bypassed all of the 429 handling below it: the pace never
        # widened, the streak counter never tripped the breaker, nothing was
        # logged (which is why a field log could read "no 429s" while the token
        # was in fact being limited), and worst of all urllib3's sleep is NOT
        # abort-aware, so a starving player waited behind it. Let every 429 reach
        # our own loop, which honours Retry-After with a cap, polls the abort
        # callback while it waits, and feeds the back-pressure logic.
        try:
            _R = requests.adapters.Retry
            retries = _R(total=None, connect=1, read=1, status=0, redirect=0,
                         status_forcelist=frozenset(),
                         respect_retry_after_header=False,
                         raise_on_status=False)
        except Exception:
            retries = 0     # no Retry class -> no retries at all beats hidden ones
        a = requests.adapters.HTTPAdapter(
            pool_connections=1, pool_maxsize=1, max_retries=retries)
        s.mount('https://', a)
        s.mount('http://', a)
        return s
    except Exception:
        return None


def _complete_length(content_range):
    """The file's real length as stated in a Content-Range, or None.

    Both forms carry it: 'bytes 0-15/525000' on a normal partial answer, and
    'bytes */525000' on a 416. The length after the slash is the whole file, not
    the part being sent, so it is authoritative even when the range itself was
    refused. '*' (unknown length) yields None, as it should."""
    m = re.search(r'/\s*(\d+)\s*$', content_range or '')
    return int(m.group(1)) if m else None


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
        self._pace = _HTTP_REQ_PACE_S  # adaptive inter-request gap (AIMD)
        self._pace_floor = _HTTP_REQ_PACE_S   # ...never decays below the start
        self._429_streak = 0          # consecutive 429-needing fetches (fail-fast)
        self._clean_streak = 0        # consecutive fetches that needed no backoff
        self._429_total = 0           # how many fetches needed a backoff at all
        self._epoch_reqs = None       # requests done when the pace last widened
        self._epoch_at = 0.0          # ...and when, so one event widens it once
        self._epoch_until = 0.0       # Retry-After can make the window longer
        self._429_absorbed = 0        # 429s inside a window we're still measuring
        self._one_shot = 0            # cues resolved in ONE request, not two
        self._log = None              # set by extract_srt so pacing is visible
        self._prefix = None           # learned cluster prefix len (see below)
        self._cue_time_ok = None      # None=untested, True=CueTime verified
        self._hdr_reads = 0           # cluster-header reads we still had to pay
        self._prefix_relearn = 0      # times the learned prefix went stale
        self.http_reqs = 0            # ACTUAL GETs, retries included (see below)
        self._progress_mark = 0       # cues collected when we last moved
        self._progress_at = 0.0       # ...and when that was
        self._stats = None            # caller-visible progress/pressure dict
        self._abort_cb = None         # set by extract_srt; polled DURING sleeps
        self.total = 0
        # Every counter above is now touched by several fetch threads, and the
        # pace gate below decides ONE schedule for all of them, so both live
        # under this lock. It is held only around arithmetic -- never across a
        # network call or a sleep -- so it can never serialise the thing it
        # exists to make concurrent.
        self._lock = _threading.RLock()
        self._gate_at = 0.0           # earliest wall-clock time for the next GET
        self._sess = _new_session() if self.is_http else None
        # Spare connections for the targeted fetches. The first is `_sess`, so a
        # serial caller behaves exactly as before and nothing extra is opened
        # unless the concurrent path actually runs.
        self._spare = []
        if self._sess is not None:
            for _ in range(max(0, _HTTP_CONNS - 1)):
                s = _new_session()
                if s is None:
                    break
                self._spare.append(s)
        self._free = None             # session pool, built on first concurrent use
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

    def _probe_fetch(self, offset, size):
        """One tiny Range GET for the EOF probe: (code, Content-Range,
        Content-Length, body) or None if the request could not be made.

        Deliberately NOT routed through _read_session: this asks a question
        about the file rather than fetching data, and it must see the status and
        the headers, which _read_session collapses into bytes. It reads at most
        `size` bytes and NEVER drains a body it did not ask for -- a provider
        that ignores Range answers with the whole file, which can be 77GB. When
        the body is small enough to finish, it IS finished, so the shared
        keep-alive connection goes back to the pool instead of being discarded
        and reconnected on the next read."""
        hdrs = {'Range': 'bytes={0}-{1}'.format(offset, offset + size - 1),
                'User-Agent': _UA}
        if self._sess is not None:
            r = self._sess.get(self.url, headers=hdrs, timeout=_HTTP_TIMEOUT,
                               stream=True)
            self.http_reqs += 1
            cl = r.headers.get('Content-Length')
            try:
                body = r.raw.read(size) or b''
            except Exception:
                body = b''
            try:
                small = 0 <= int(cl) <= _PROBE_DRAIN_MAX
            except (TypeError, ValueError):
                small = False
            try:
                if small:
                    r.raw.read()          # finish it -> connection is reusable
            except Exception:
                pass
            try:
                r.close()
            except Exception:
                pass
            return r.status_code, r.headers.get('Content-Range'), cl, body
        if _urlreq is None:
            return None
        req = _urlreq.Request(self.url, headers=hdrs)
        try:
            resp = _urlreq.urlopen(req, timeout=_HTTP_TIMEOUT)
        except Exception as e:
            # urllib RAISES on a 416 rather than returning it, and the error
            # object still carries the status and the headers -- which is where
            # the answer is. Anything without a status is not an answer.
            code = getattr(e, 'code', None)
            if code is None:
                return None
            self.http_reqs += 1
            eh = getattr(e, 'headers', None)
            return (code, eh.get('Content-Range') if eh else None,
                    eh.get('Content-Length') if eh else None, b'')
        self.http_reqs += 1
        try:
            code = getattr(resp, 'status', None) or resp.getcode()
            try:
                body = resp.read(size) or b''
            except Exception:
                body = b''
            return (code, resp.headers.get('Content-Range'),
                    resp.headers.get('Content-Length'), body)
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def probe_beyond(self, offset, known=None):
        """Is there anything in this file AT `offset`? Returns 'more', 'eof' or
        'unknown', and only ever says 'eof' on evidence about `offset` itself.

        Reading at `offset` and looking at what comes back cannot answer this.
        `read()` collapses every outcome that is not a successful fetch into the
        same b'': a tripped breaker, any exception, and a server that ignores
        the Range header and answers 200 (which this file already documents
        happening in the field) all look exactly like a genuine end of file. So
        an empty read is NOT evidence of EOF, and treating it as such lets a
        real truncation -- one that happened to land on a clean element
        boundary, where parsing cannot see it either -- be certified as a
        complete subtitle with lines missing.

        Nor is it enough to check that the connection is healthy by re-reading
        bytes from BEFORE `offset`. That proves the provider can still serve a
        region we already have; it establishes nothing about the region in
        question, and a provider inconsistent exactly at the frontier of what
        has been fetched satisfies it while data is still there. (Measured: a
        subtitle delivered as complete, missing half its lines.)

        So the question is asked in the one form a provider is obliged to answer
        precisely: a range that STARTS INSIDE the file -- at bytes the caller
        already read, passed in as `known` -- and runs past `offset`. Being
        satisfiable, it cannot be answered with a 416 or with whatever a
        provider does to an out-of-range ask, and a compliant partial response
        must carry a Content-Range stating the file's true length. That length
        settles it outright. Failing that, the answer is measured rather than
        inferred: the known bytes must come back exactly, and then whether
        anything follows them is the answer -- data past `offset` means the
        earlier response really was cut short, and data that stops dead at
        `offset` means the file does. A provider serving the wrong region, or
        cut short itself, matches nothing and stays unknown.

        For a local file the size on disk answers directly.
        """
        if not self.is_http:
            try:
                sz = os.path.getsize(self.url)
            except Exception:
                return 'unknown'
            return 'eof' if offset >= sz else 'more'
        if self.tripped:
            return 'unknown'
        try:
            c_off, c_want = known if known else (0, b'')
            if not (c_want and 0 <= c_off < offset):
                # Nothing to check the answer against. Still ask from inside the
                # file rather than at the point itself -- a satisfiable range is
                # what obliges a provider to state the real length, and asking
                # at the point is the form that several of them answer in ways
                # nothing can interpret.
                c_off, c_want = max(0, offset - _PROBE_CONTROL), b''
            n = len(c_want)
            span = offset - c_off
            got = self._probe_fetch(c_off, span + _PROBE_AHEAD)
            if got is None:
                return 'unknown'
            body = got[3]
            past = len(body) > span
            if n and body[:n] == c_want and past:
                # Bytes past the point, from a provider demonstrably serving the
                # right region: the earlier response really was cut short. This
                # takes precedence over any length the same response states,
                # because a response contradicting itself is not evidence of an
                # end of file -- and erring towards "truncated" only ever costs
                # an attempt. The reverse -- a body that stops dead at the point
                # -- is NOT taken as proof of the end: a response that was itself
                # capped there looks identical, and only a provider already
                # violating the spec (a partial answer with no Content-Range)
                # can leave the question in that state.
                return 'more'
            verdict = self._classify_probe(got[0], got[1], got[2], offset)
            if verdict == 'eof' and past:
                # A stated end, with bytes past it in the same breath, and no
                # way to tell which is true -- the known bytes did not come back
                # (so nothing in this response is evidence about our region) or
                # there were none to check against. A header alone is trivial to
                # produce from the request without ever seeking there, which is
                # what a templated caching layer does, so it does not get to
                # settle a question its own body disputes. Defer.
                return 'unknown'
            return verdict if verdict != 'silent' else 'unknown'
        except Exception:
            return 'unknown'

    @staticmethod
    def _classify_probe(code, content_range, content_length, offset):
        """What one probe response's STATUS AND HEADERS establish about
        `offset`. 'silent' means they establish nothing, and the body has to be
        measured instead."""
        if code == 416:
            return 'eof'
        end = _complete_length(content_range)
        if end is not None and end > 0:
            return 'eof' if offset >= end else 'more'
        if code >= 300:
            return 'unknown'          # refused / errored -- says nothing at all
        if code == 200 and offset > 0:
            # Range ignored, so Content-Length describes the WHOLE file. A
            # length beyond our offset proves there is more there. Never read
            # the reverse as a confirmation of EOF: a declared length shorter
            # than the bytes we have already read contradicts them, and a
            # contradiction confirms nothing.
            try:
                cl = int(content_length)
            except (TypeError, ValueError):
                return 'unknown'
            return 'more' if cl > offset else 'unknown'
        return 'silent'

    def _making_progress(self):
        """Are we still actually collecting cues, despite the back-pressure?

        The 429 streak-breaker exists to protect the PLAYER: the reasoning is
        that a saturated token means the movie dies. But a 429 streak is only a
        PROXY for that, and a poor one -- a provider can push back on half our
        reads while the player is completely healthy, which is exactly what a
        field log shows (TorBox: 31 backoffs in 60 reads, the player fine
        throughout, extraction abandoned at 75 of 555 cues after 225s).

        There is a DIRECT guard for player harm already, and it is the one that
        matters: the caller's abort callback watches the playback clock and stops
        us within 8s if it ever freezes. And since an interrupted pass now banks
        its progress, crawling on is strictly better than giving up -- the same
        run would have reached ~300 cues in its remaining budget instead of
        stopping at 75, turning eight play sessions into two.

        So the breaker now fires only when back-pressure has ALSO stalled us: no
        new cues for a while. Real saturation looks like that; a slow provider
        does not."""
        try:
            n = (self._stats or {}).get('done') or 0
        except Exception:
            n = 0
        import time as _t
        now = _t.time()
        if n > self._progress_mark:
            self._progress_mark = n
            self._progress_at = now
            return True
        if not self._progress_at:
            self._progress_at = now
            return True
        return (now - self._progress_at) < _STALLED_PROGRESS_S

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

    def fetched_now(self):
        """Bytes fetched so far, read under the lock. The byte cap is what keeps
        an extraction from competing with the player for the line, so with
        several fetches in flight it must not be decided on a torn read."""
        with self._lock:
            return self.fetched

    def _gate_wait(self, pace):
        """Wait for this request's slot in the ONE shared schedule. Returns True
        if the wait was aborted (player needs the line).

        Claiming the slot is arithmetic under the lock; the waiting happens
        outside it, so several connections can be mid-flight while the next slot
        is already reserved. That is the whole trick: the CDN's view (one
        request per `pace`) is unchanged, and only our idle time between them
        disappears."""
        now = time.time()
        with self._lock:
            start = self._gate_at if self._gate_at > now else now
            self._gate_at = start + pace
        wait = start - now
        if wait <= 0:
            return False
        return self._sleep_or_abort(wait)

    def restore_pace(self, was):
        """Put the pace back to `was` after a burst we CHOSE to make provoked
        pushback. Without this the AIMD ratchet keeps the penalty for the rest
        of the extraction -- 0.20s to 2.00s in the field, and a decay that needs
        25 clean requests per step to walk it back -- so a 29-second experiment
        cost fifteen extra minutes. Only ever lowers the pace back toward where
        it started; a provider that is genuinely slow keeps its own widening,
        because that widening was not our doing."""
        with self._lock:
            if was is None or self._pace <= was:
                return False
            had, self._pace = self._pace, max(was, self._pace_floor)
            self._429_streak = 0
            self._clean_streak = 0
            if self._stats is not None:
                self._stats['pace'] = self._pace
        if self._log:
            self._log('pushback came from our own burst -- pace back to %.2fs '
                      'from %.2fs' % (self._pace, had))
        return True

    def _take_session(self):
        """Borrow a connection. Serial callers always get the original one, so
        nothing about the single-connection path changes; the spares are handed
        out only when something is already using it."""
        free = self._free
        if free is None:
            return self._sess
        try:
            return free.get(timeout=_HTTP_TIMEOUT)
        except Exception:
            return self._sess

    def _give_session(self, sess):
        free = self._free
        if free is None or sess is None:
            return
        try:
            free.put_nowait(sess)
        except Exception:
            pass

    def open_pool(self):
        """Arm the connection pool. Returns how many connections are available
        (1 = nothing to parallelise, so callers stay serial)."""
        if self._free is not None:
            return self._free.qsize()
        if self._sess is None or not self._spare:
            return 1
        try:
            import queue as _q
        except Exception:
            return 1
        free = _q.Queue()
        free.put(self._sess)
        for s in self._spare:
            free.put(s)
        self._free = free
        return free.qsize()

    def close_pool(self):
        """Give the spare connections back to the OS as soon as the concurrent
        phase is over -- the player keeps the line for the rest of playback."""
        self._free = None
        for s in self._spare:
            try:
                s.close()
            except Exception:
                pass
        self._spare = []

    def _read_session(self, offset, size):
        """One Range GET over the SHARED keep-alive connection. Single-range,
        never multipart (a fat multi-range body starves the hardware decoder). On
        a 429/5xx we BACK OFF (honor Retry-After) and retry a few times -- a
        debrid CDN token rate-limits by request count and recovers after a short
        cooldown -- and only trip the breaker after exhausting retries. Both the
        per-request pace and the backoff are abort-aware, so a stalled player is
        noticed within ~1s instead of behind a 2-minute retry storm."""
        # `reqs` counts LOGICAL reads; one of them can cost several GETs, because
        # a 429 is retried in place. On a provider that pushes back on half our
        # reads that is a large, invisible multiplier -- the field log's "60 req"
        # was really closer to 110 as far as the CDN was concerned, which both
        # understated the load and hid it from anyone reading the log. Count the
        # GETs separately and report both.
        with self._lock:
            self.reqs += 1
            n = self.reqs
            _pace = getattr(self, '_pace', _HTTP_REQ_PACE_S)
        saw_429 = False               # did THIS fetch need a 429 backoff?
        if n > 1 and _pace > 0:
            # THE rate limiter, and the reason concurrency does not multiply the
            # load: every connection takes its slot from one shared schedule, so
            # the CDN sees at most one request per `_pace` seconds in total --
            # the same rate as when this was serial. What concurrency removes is
            # only the round trip we used to pay AFTER the gap, in series.
            if self._gate_wait(_pace):
                self.tripped = True
                return b''
        sess = self._take_session()
        try:
            return self._read_session_inner(sess, offset, size, saw_429)
        finally:
            self._give_session(sess)

    def _read_session_inner(self, sess, offset, size, saw_429):
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
                with self._lock:
                    self.http_reqs += 1
                r = sess.get(self.url, headers={
                    'Range': 'bytes={0}-{1}'.format(offset, offset + size - 1),
                    'User-Agent': _UA}, timeout=_HTTP_TIMEOUT, stream=True)
                code = r.status_code
                if code == 429 or code >= 500:
                    saw_429 = True
                    ra = r.headers.get('Retry-After')
                    # Back-pressure: widen the pace so we ease off the contended
                    # token (protects the player, converges toward a rate the CDN
                    # tolerates). Persists for the rest of this extraction.
                    #
                    # ONCE per congestion event, though -- see _HTTP_PACE_EPOCH_*.
                    # Until the pace we just set has been measured, further 429s
                    # are the same event arriving again (very often literally the
                    # retries of this same fetch) and must not compound.
                    try:
                        _now = time.time()
                        with self._lock:
                            _was = getattr(self, '_pace', _HTTP_REQ_PACE_S)
                            self._429_total += 1
                            _measuring = (
                                self._epoch_reqs is not None
                                and (self.http_reqs - self._epoch_reqs
                                     < _HTTP_PACE_EPOCH_REQS
                                     or _now < self._epoch_at
                                     + _HTTP_PACE_EPOCH_S
                                     or _now < self._epoch_until))
                            if _measuring:
                                self._429_absorbed += 1
                            else:
                                self._pace = min(_was * 1.5,
                                                 _HTTP_REQ_PACE_MAX)
                                self._clean_streak = 0
                                self._epoch_reqs = self.http_reqs
                                self._epoch_at = _now
                                # The CDN told us how long it wants: that IS the
                                # window, so never re-widen inside it. Anything
                                # unparseable or non-finite just leaves the
                                # request/seconds window above to decide.
                                self._epoch_until = 0.0
                                if ra:
                                    try:
                                        _ra = float(ra)
                                    except (TypeError, ValueError):
                                        _ra = 0.0
                                    if 0.0 < _ra < 1e6:
                                        self._epoch_until = _now + min(
                                            _ra, _HTTP_429_MAX_WAIT)
                        if self._stats is not None:
                            self._stats['backoffs'] = self._429_total
                            self._stats['pace'] = self._pace
                        # Report the first one and then each doubling: the pace
                        # creeping 0.2s -> 2.0s is what turns a 3-minute extract
                        # into an 18-minute one, and it used to leave no trace
                        # at all in the log.
                        if self._log and not _measuring and (
                                self._429_total == 1
                                or self._pace >= _was * 2
                                or self._pace >= _HTTP_REQ_PACE_MAX > _was):
                            self._log(
                                'CDN pushed back (%d so far, %d absorbed as the '
                                'same event, HTTP %s) -- pace %.2fs -> %.2fs '
                                'after %d request(s)'
                                % (self._429_total, self._429_absorbed, code,
                                   _was, self._pace, self.reqs))
                    except Exception:
                        pass
                    try:
                        r.close()
                    except Exception:
                        pass
                    r = None
                    if _attempt >= _HTTP_429_RETRIES - 1:
                        # UNCONDITIONAL, deliberately. This is what guarantees a
                        # partial extract is never delivered: without `tripped`
                        # the pass can run to completion with reads that returned
                        # nothing and hand back a short subtitle as if it were
                        # whole. (Tried gating it on progress, the way the streak
                        # breaker is gated -- a fully-refusing provider then
                        # produced an SRT instead of deferring.)
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
                    # The retry is another GET, so it takes another slot in the
                    # shared schedule. Without this a refused fetch could replay
                    # on its own clock while other connections were dispatching,
                    # which is the one way concurrency could have pushed the rate
                    # the CDN sees above the paced one.
                    with self._lock:
                        _p = getattr(self, '_pace', _HTTP_REQ_PACE_S)
                    if _p > 0 and self._gate_wait(_p):
                        self.tripped = True
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
                # Fail-fast bookkeeping: a clean fetch resets the streak; a fetch
                # that only succeeded after 429 backoff extends it. Too many in a
                # row => the token is saturated (TorBox), so trip the breaker now
                # rather than crawl for minutes with the token held hot. This
                # cue's data is still returned; the caller sees `tripped` next and
                # defers (a partial extract is never delivered anyway).
                #
                # All of it under the lock: with several connections these are
                # read-modify-write on shared state, and a lost increment here
                # would mean a byte cap that never trips or a pace that decays
                # while the CDN is still pushing back.
                _decayed = None
                with self._lock:
                    self.fetched += len(data)
                    if saw_429:
                        self._429_streak = getattr(self, '_429_streak', 0) + 1
                        self._clean_streak = 0
                        if (self._429_streak >= _HTTP_429_STREAK_MAX
                                and not self._making_progress()):
                            self.tripped = True
                    else:
                        self._429_streak = 0
                        # Additive-increase half of AIMD: a long clean run is
                        # evidence the widened pace is now costing time for
                        # nothing, so give some of it back. Never below the
                        # floor, and never below where we started.
                        self._clean_streak = getattr(self, '_clean_streak', 0) + 1
                        if (self._clean_streak >= _HTTP_PACE_DECAY_AFTER
                                and self._pace > self._pace_floor):
                            self._clean_streak = 0
                            _decayed = self._pace
                            self._pace = max(self._pace * _HTTP_PACE_DECAY,
                                             self._pace_floor)
                if _decayed is not None:
                    # Own try/except, like its sibling above. This sits inside
                    # the method's broad `except Exception: return b''`, so a log
                    # callable that raises here would DISCARD a read that already
                    # succeeded -- and report it as a network failure, without
                    # setting `tripped`, so the caller could not tell the loss had
                    # nothing to do with the CDN.
                    try:
                        if self._stats is not None:
                            self._stats['pace'] = self._pace
                        if self._log:
                            self._log('CDN quiet for %d request(s) -- pace '
                                      '%.2fs -> %.2fs'
                                      % (_HTTP_PACE_DECAY_AFTER, _decayed,
                                         self._pace))
                    except Exception:
                        pass
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
    Each position is (cluster_pos, relative_pos_or_None, cue_time_or_None) --
    CueTime is the cue's ABSOLUTE timestamp in TimestampScale units, which is
    exactly what a cluster-header read would otherwise be spent computing (see
    _fetch_cluster_blocks).
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
    if len(raw) < need:
        # The Cues element declares its own size, and we did not get all of it.
        # This is the SAME truncation the cluster reads now guard against (a
        # capped response or a dropped connection, no 429 anywhere), reached
        # through a different door -- and it is worse here, because a short Cues
        # index simply yields FEWER cue positions. Every one of them is then
        # fetched successfully, the pass reports a complete success, and a
        # subtitle missing every line past the cut is delivered as if it were
        # whole. Measured: 30 of 60 cues, with nothing in the log to suggest it.
        # An empty return makes the caller defer.
        log('cues element truncated (%d of %d bytes, no 429) -- deferring '
            'rather than indexing half the file' % (len(raw), need))
        return [], False
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
        # CueTime is the CuePoint's own first child, a sibling of every
        # CueTrackPositions under it -- so read it before walking them.
        ctime = None
        tb = _Buf(cp, 0)
        for peid, psize, pstart in _walk(tb, len(cp)):
            if psize is None:
                break
            tb.p = pstart + psize
            if peid == _CUE_TIME:
                ctime = _read_uint(cp[pstart:pstart + psize])
                break
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
                any_pos.append((cpos, crel, ctime))
                if ctrack == want_track:
                    want_pos.append((cpos, crel, ctime))
    is_sub = bool(want_pos)
    # Keep EVERY distinct (cluster, relpos) pair. A single cluster routinely
    # holds >1 subtitle cue (two lines a couple seconds apart in fast dialogue),
    # and the relpos fast path fetches EXACTLY ONE block per relpos -- collapsing
    # them by cluster would silently drop every line but the first. A cue WITHOUT
    # relpos forces a full window-scan of its cluster (which recovers every block
    # in it), so it subsumes and REPLACES any relpos entries for the same cluster
    # (avoids fetching the same cluster twice).
    scan_only = set()          # clusters that carry a relpos-less cue
    rel_by_cpos = {}           # cpos -> {relpos: cue_time_or_None}
    for cpos, crel, ctime in (want_pos if is_sub else any_pos):
        if crel is None:
            scan_only.add(cpos)
        else:
            rel_by_cpos.setdefault(cpos, {})[crel] = ctime
    out = []
    for cpos in sorted(scan_only | set(rel_by_cpos)):
        if cpos in scan_only:
            out.append((cpos, None, None))
        else:
            for relpos in sorted(rel_by_cpos[cpos]):
                out.append((cpos, relpos, rel_by_cpos[cpos][relpos]))
    nrel = sum(1 for _c, r, _t in out if r is not None)
    ntime = sum(1 for _c, r, t in out if r is not None and t is not None)
    log('cues: %d cue(s) / %d cluster(s) (%s, %d with relpos, %d with cuetime)'
        % (len(out), len(scan_only | set(rel_by_cpos)),
           'sub-track' if is_sub else 'whole-file', nrel, ntime))
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
    if len(raw) < need:
        # The Cues element declares its own size, and we did not get all of it.
        # This is the SAME truncation the cluster reads now guard against (a
        # capped response or a dropped connection, no 429 anywhere), reached
        # through a different door -- and it is worse here, because a short Cues
        # index simply yields FEWER cue positions. Every one of them is then
        # fetched successfully, the pass reports a complete success, and a
        # subtitle missing every line past the cut is delivered as if it were
        # whole. Measured: 30 of 60 cues, with nothing in the log to suggest it.
        # An empty return makes the caller defer.
        log('cues element truncated (%d of %d bytes, no 429) -- deferring '
            'rather than indexing half the file' % (len(raw), need))
        return {}
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
                              abort_cb=None, log=None, stats=None):
    """Dense cue START times for SEVERAL languages in ONE head+Cues read.

    Returns {lang: sorted_times_ms} -- the same per-language skeleton
    `cue_reference_times` returns, but computed for every language in `langs` at
    once, reading the head + Cues element + timeline origin EXACTLY ONCE and
    slicing per track (one Cues index carries every track's cue points). This is
    what the cross-language embedded-align fallback uses so trying 2-3 languages
    costs ONE read, not one per language. `langs` is normalised to 2-letter
    codes; several may resolve to the same track. A language whose track has no
    per-cue index is omitted from the result. `allow_http` must be True for an
    HTTP/debrid source. `stats`, if given, is filled in the same way extract_srt
    fills it -- above all 'backoffs', so the caller can tell provider pressure
    from an ordinary pause instead of guessing. Never raises."""
    _log = log or _noop
    try:
        seen = list(dict.fromkeys(
            [str(l).lower()[:2] for l in (langs or []) if l]))
        if not seen:
            return {}
        src = _Source(url_or_path)
        src._abort_cb = abort_cb
        src._log = _log
        src._stats = stats if stats is not None else None
        if src._stats is not None:
            src._stats['backoffs'] = 0
            src._stats['pace'] = src._pace
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
                abort_cb=None, log=None, progress_cb=None, resume_path=None,
                stats=None):
    """Extract an embedded TEXT subtitle track as an SRT string.

    Pick the track by `track_num`, else by `lang` (BCP-47 prefix, e.g. 'en'
    matches 'eng'), else the first non-forced text track. Returns the SRT text,
    or None when there is no matching text track / the file has no usable Cues
    over HTTP / anything fails. NEVER raises -- the caller always has the
    external path to fall back to. `abort_cb`, if given, is polled between
    clusters; when it returns True (e.g. playback ended) extraction stops.
    `allow_http` must be True to extract from a debrid/HTTP stream (default
    False -- local-only); HTTP extraction then uses ONE keep-alive connection
    with coalesced ranges + a 429 circuit-breaker so it can't starve playback.
    `resume_path`, if given, is a scratch file where an INTERRUPTED HTTP pass
    leaves what it collected, so the next attempt continues instead of starting
    over. It never changes what is delivered -- a partial extract still returns
    None -- only what survives a deferral.
    `stats`, if given, is a dict this fills in as it goes: 'done'/'total' cues,
    'backoffs' (how many times the CDN pushed back) and 'pace'. The caller needs
    those to decide things it otherwise has to GUESS at -- above all whether the
    provider is actually under pressure, which is the difference between handing
    the connection back to the player and cancelling useful work for nothing."""
    _log = log or _noop
    t0 = time.time()
    src = None
    try:
        src = _Source(url_or_path)
        src._abort_cb = abort_cb   # polled DURING pace/backoff sleeps too
        src._log = _log            # so pacing/back-pressure is visible in a log
        # Start where this provider left off last time (see _PACE_MEMORY_*),
        # rather than spending the burst allowance re-learning it every episode.
        _remembered = _pace_memory_load(url_or_path)
        if _remembered:
            src._pace = _remembered
            _log('starting at %.2fs -- the pace this provider tolerated last '
                 'time, probed %d%% faster' % (
                     _remembered, int(round((1 - _PACE_MEMORY_PROBE) * 100))))
        src._stats = stats if stats is not None else None
        if src._stats is not None:
            src._stats.setdefault('done', 0)
            src._stats.setdefault('total', 0)
            src._stats['backoffs'] = 0
            src._stats['pace'] = src._pace
        if not src.total:
            return None
        seg_start, ts_scale, tracks, seeks = _parse_head(src, head_bytes, _log)
        subs = _sub_tracks(tracks)
        if not subs:
            return None
        # We translate THIS track's own text, so prefer an SDH track: it carries
        # the complete dialogue. (The cue_reference_times* callers deliberately do
        # NOT prefer SDH -- there the track is only a timing skeleton.)
        track = _pick_track(subs, track_num, lang, prefer_sdh=True)
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
                             progress_cb, resume_path, codec):
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
    finally:
        # On EVERY exit, including the ones that gave up. A run the provider
        # throttled into deferring is precisely the run whose lesson the next
        # one needs; saving only on success would keep re-learning it.
        try:
            if src is not None and src.is_http:
                _pace_memory_save(url_or_path, src._pace, src.http_reqs)
        except Exception:
            pass


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


def _pick_track(subs, track_num, lang, prefer_sdh=False):
    # prefer_sdh: order an SDH/hearing-impaired track FIRST among equally-tagged
    # matches. Turn it on ONLY when the track's own TEXT is what we translate
    # (extract_srt) -- SDH carries the complete dialogue. Keep it OFF (default)
    # when the track is used merely as a TIMING skeleton to align an EXTERNAL sub
    # (cue_reference_times*): an SDH track's extra sound-description cues have no
    # match in a plain external subtitle and would only depress the align overlap/
    # vote ratios, risking a previously-synced sub failing the gate.
    _sdh_key = ((lambda t: not _track_is_sdh(t)) if prefer_sdh else (lambda t: 0))
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
                                 _sdh_key(t), t['num']))
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
    cand.sort(key=lambda t: (_sdh_key(t), t['num']))   # SDH first (if prefer_sdh), then order
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


# ---- resume ------------------------------------------------------------------
# A deferral used to throw the whole pass away. On a provider that rate-limits
# hard, an HTTP extraction can ONLY ever be interrupted -- circuit-breaker, byte
# cap, time budget, or the user resuming after a pause -- so it never completed
# at all, no matter how many times the file was played. Persisting what a pass
# collected turns that dead end into progress: the next attempt starts where the
# last one stopped, and the extraction finishes across a few plays with the user
# doing nothing.
#
# Only whole CLUSTERS are recorded as finished -- one whose every targeted cue
# resolved, or that a window scan covered cleanly. A partially-resolved cluster
# is simply redone; _entries_to_srt already de-duplicates on (start, text), so
# redoing one costs a request, never a duplicated line.
#
# A partial extract is still NEVER delivered. This changes only what survives an
# interruption, not what counts as a finished subtitle.
_RESUME_MAGIC = b'KPIEMB1'
_RESUME_MAX = 16 * 1024 * 1024     # ~200x a feature film's worth of cues


def _resume_identity(src, want, codec, positions):
    """Fingerprint of THIS file and track. A debrid URL is per-session and is
    regenerated between plays, so it is deliberately NOT part of the identity --
    what makes reusing saved work safe is that the byte length, the track, the
    codec and the Cues layout all still match. Any mismatch discards it."""
    import hashlib
    h = hashlib.sha1()
    h.update(('%d|%s|%s|%d|%d|%d|%d' % (
        src.total, want, codec or '', len(positions),
        positions[0][0] if positions else 0,
        positions[-1][0] if positions else 0,
        sum(p[1] or 0 for p in positions[:64]))).encode('utf-8'))
    return h.hexdigest()


def _resume_load(path, identity, log):
    """(entries, finished_clusters, scan_pending_clusters) from an earlier pass
    over this exact file, or ([], set(), set()). Never raises: any doubt returns
    nothing, and the extraction simply starts over."""
    try:
        if not path or not os.path.exists(path):
            return [], set(), set()
        if os.path.getsize(path) > _RESUME_MAX:
            return [], set(), set()
        with open(path, 'rb') as f:
            blob = f.read()
        head, _sep, body = blob.partition(b'\n')
        parts = head.split(b' ')
        if len(parts) != 2 or parts[0] != _RESUME_MAGIC:
            return [], set(), set()
        if parts[1].decode('ascii', 'replace') != identity:
            log('resume: saved work belongs to a different file -- ignoring it')
            return [], set(), set()
        entries, done, scan = [], set(), set()
        p, n = 0, len(body)
        while p < n:
            tag = body[p:p + 1]
            p += 1
            if tag == b'E':
                if p + 20 > n:
                    return [], set(), set()
                ticks, dur, ln = struct.unpack('<qqI', body[p:p + 20])
                p += 20
                frame = body[p:p + ln]
                p += ln
                if len(frame) != ln:
                    return [], set(), set()   # truncated -> trust none of it
                entries.append((ticks, None if dur < 0 else dur, frame))
            elif tag in (b'K', b'S'):
                if p + 8 > n:
                    return [], set(), set()
                (cpos,) = struct.unpack('<Q', body[p:p + 8])
                (done if tag == b'K' else scan).add(cpos)
                p += 8
            else:
                return [], set(), set()
        if entries or done or scan:
            log('resume: %d cue(s), %d finished cluster(s) and %d awaiting a '
                'scan, recovered from an earlier pass'
                % (len(entries), len(done), len(scan)))
        return entries, done, scan
    except Exception:
        return [], set(), set()


def _resume_save(path, identity, entries, done, scan, log):
    """Persist an interrupted pass. Never raises; a failure only means the next
    attempt starts over, which is exactly today's behaviour."""
    if not path:
        return
    try:
        out = [_RESUME_MAGIC + b' ' + identity.encode('ascii') + b'\n']
        size = len(out[0])
        for ticks, dur, frame in entries:
            rec = b'E' + struct.pack('<qqI', int(ticks),
                                     -1 if dur is None else int(dur),
                                     len(frame)) + frame
            size += len(rec)
            if size > _RESUME_MAX:
                # Save nothing rather than a subset: dropping entries while
                # keeping their cluster marked finished would lose lines
                # permanently.
                return
            out.append(rec)
        for cpos in done:
            out.append(b'K' + struct.pack('<Q', int(cpos)))
        for cpos in scan:
            out.append(b'S' + struct.pack('<Q', int(cpos)))
        tmp = path + '.part'
        with open(tmp, 'wb') as f:
            f.write(b''.join(out))
        os.replace(tmp, path)
        log('resume: saved %d cue(s) / %d finished cluster(s) / %d awaiting a '
            'scan, for the next attempt'
            % (len(entries), len(done), len(scan)))
    except Exception:
        try:
            if os.path.exists(path + '.part'):
                os.remove(path + '.part')
        except Exception:
            pass


def _resume_clear(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _extract_cues(src, seeks, seg_start, want, entries,
                  max_bytes, deadline_s, t0, abort_cb, log, progress_cb=None,
                  resume_path=None, codec=''):
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
        for cpos, _rel, _ctime in positions:
            if cpos in seen_local:
                continue
            seen_local.add(cpos)
            if (time.time() - t0) > deadline_s or _aborted(abort_cb):
                return False
            _read_and_collect_cluster(
                src, cpos, want, entries, _CLUSTER_CAP_LOCAL, log)
        return True
    # HTTP only: a local pass is one cheap sequential walk, so there is nothing
    # worth carrying between attempts.
    identity = _resume_identity(src, want, codec, positions)
    prior, done, scan = _resume_load(resume_path, identity, log)
    entries.extend(prior)
    ok = _extract_cues_http(src, positions, entries, want, deadline_s, t0,
                            abort_cb, log, progress_cb, done, scan)
    if ok:
        _resume_clear(resume_path)
    else:
        _resume_save(resume_path, identity, entries, done, scan, log)
    return ok


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


def _batch_relposes(items):
    """Group ONE cluster's [(relpos, cue_time), ...] (sorted) into read batches.
    Blocks within _CLUSTER_BATCH_MAX of each other share a single range request;
    anything further apart gets its own, because the bytes in between are video
    the player needs and are not worth a saved round-trip."""
    batches = []
    cur = [items[0]]
    for it in items[1:]:
        if (it[0] - cur[0][0]) + _BLOCK_READ_HTTP <= _CLUSTER_BATCH_MAX:
            cur.append(it)
        else:
            batches.append(cur)
            cur = [it]
    batches.append(cur)
    return batches


def _read_cluster_header(src, cpos, first_relpos):
    """(prefix, cluster_ts, header_bytes) for the cluster at `cpos`, or
    (None, None, b''). Sized to swallow the first block too when that block sits
    close enough that one request beats two."""
    need = first_relpos + _PREFIX_MAX + _BLOCK_READ_HTTP
    one_shot = 0 <= first_relpos and need <= _ONE_SHOT_MAX
    with src._lock:
        src._hdr_reads += 1
    header = src.read(cpos, need if one_shot else _CLUSTER_HDR_READ)
    if src.tripped or not header:
        return None, None, b''
    prefix, cluster_ts = _cluster_prefix_and_ts(header)
    if prefix is None:
        return None, None, b''
    return prefix, cluster_ts, header


def _fetch_cluster_blocks(src, cpos, items, want, entries, log):
    """CueRelativePosition FAST PATH for ONE cluster. `items` is that cluster's
    [(relpos, cue_time), ...], sorted by relpos. Returns how many of them were
    resolved; the caller window-scans the whole cluster whenever that is short of
    len(items), so a miss can never silently drop a line.

    A block sits at cpos + prefix + relpos, and its absolute timestamp is
    cluster_ts + the block's own 16-bit offset. Both `prefix` and `cluster_ts`
    used to come from an 8KB read at the cluster start, spent AGAIN for every
    single cue -- which is where 2.03-2.10 requests per cue came from. Here the
    prefix is learned once per file and CueTime supplies the timestamp, so the
    steady state is ONE request per block (or per nearby group of them). The
    first cluster still pays the header read, and its answers are used to VERIFY
    both shortcuts before any later cluster relies on them."""
    resolved = 0
    prefix, cluster_ts, header = src._prefix, None, b''
    # Take the header when we have not learned the prefix yet, when CueTime has
    # not been proven to agree with it, or when any cue in THIS cluster has no
    # CueTime to stand in for the cluster timestamp. (`_cue_time_ok is False`
    # means the file's CueTimes were wrong, so every cluster keeps paying for a
    # header -- correct, just not fast.)
    if (prefix is None or src._cue_time_ok is not True
            or any(t is None for _r, t in items)):
        prefix, cluster_ts, header = _read_cluster_header(src, cpos, items[0][0])
        if prefix is None:
            return 0
        with src._lock:
            src._prefix = prefix

    def _place(buf, base, relpos, cue_time):
        """Parse the block at `relpos` out of `buf`, which starts at file offset
        `base`. Appends to `entries` on success. Returns True/False."""
        off = (cpos + prefix + relpos) - base
        if not (0 <= off < len(buf)):
            return False
        got = []
        if not _collect_one_block(buf[off:], want, cluster_ts or 0, got):
            return False
        ticks, dur, frame = got[0]
        if cluster_ts is None:
            # No header this time: `ticks` is the block's own 16-bit offset and
            # CueTime is the absolute time. (Only reachable once _cue_time_ok is
            # True, i.e. after this identity was checked against a real header.)
            entries.append((cue_time, dur, frame))
        else:
            entries.append((ticks, dur, frame))
            if cue_time is not None and src._cue_time_ok is None:
                # THE CHECK. Does this file's CueTime really equal the timestamp
                # the header math produces? Only if it does may later clusters
                # skip their header read.
                if ticks != cue_time:
                    src._cue_time_ok = False
                    if src._log:
                        src._log('CueTime disagrees with the cluster timestamp '
                                 '(%s vs %s) -- keeping the per-cluster header '
                                 'read' % (cue_time, ticks))
                elif cluster_ts:
                    # Agreement only PROVES anything at a non-zero cluster
                    # timestamp. The first cluster of every file is at 0, where
                    # cluster_ts + rel_ts == rel_ts -- so a muxer that wrote
                    # CueTime RELATIVE to its cluster instead of absolute would
                    # pass there and be wrong everywhere after it. Stay
                    # undecided (and keep paying for headers) until a cluster
                    # with a real timestamp settles it.
                    src._cue_time_ok = True
        return True

    for batch in _batch_relposes(items):
        # Anything the header read already covers costs no extra request.
        pending = []
        for (relpos, cue_time) in batch:
            if header and _place(header, cpos, relpos, cue_time):
                src._one_shot += 1
                resolved += 1
            else:
                pending.append((relpos, cue_time))
        if not pending:
            continue
        if src.fetched_now() >= _HTTP_TOTAL_CAP:
            return resolved
        lo = pending[0][0]
        span = (pending[-1][0] - lo) + _BLOCK_READ_HTTP
        base = cpos + prefix + lo
        buf = src.read(base, min(span, _HTTP_TOTAL_CAP - src.fetched_now()))
        if src.tripped or not buf:
            return resolved
        for (relpos, cue_time) in pending:
            if _place(buf, base, relpos, cue_time):
                resolved += 1
                continue
            if cluster_ts is not None:
                continue   # header path already; nothing left to try
            # The learned prefix did not resolve this block. Before writing the
            # cue off to the (expensive) window scan, pay for one header read: a
            # muxer CAN change its size-VINT width mid-file, and re-learning
            # here keeps every later cluster on the fast path.
            #
            # This is also the one place that PROVES the width is not stable for
            # this file, which is why the concurrent phase watches the counter:
            # three threads sharing one prefix value while it is being re-learned
            # is neither faster nor sound (see _healthy).
            with src._lock:
                src._prefix_relearn += 1
            prefix, cluster_ts, header = _read_cluster_header(src, cpos, relpos)
            if prefix is None:
                return resolved
            with src._lock:
                src._prefix = prefix
            if _place(header, cpos, relpos, cue_time):
                resolved += 1
            else:
                base2 = cpos + prefix + relpos
                if src.fetched_now() < _HTTP_TOTAL_CAP and _place(
                        src.read(base2, min(_BLOCK_READ_HTTP,
                                            _HTTP_TOTAL_CAP - src.fetched_now())),
                        base2, relpos, cue_time):
                    resolved += 1
            # Back to the fast path for the rest of this cluster: `buf`/`base`
            # were read against the OLD prefix, and _place's offset math already
            # accounts for the shift, so the remaining blocks still resolve.
            cluster_ts, header = None, b''
    return resolved


def _short_read(src, offset, asked, got):
    """Did the provider return FEWER bytes than a compliant server owes us?

    This is the only reliable truncation signal available. Everything else in
    this file watches HTTP status, and a capped Range response or a connection
    that dropped mid-stream carries none -- no 429, no 5xx, nothing to retry or
    trip on. Parsing cannot see it either: when the bytes happen to run out
    exactly at a Matroska child-element boundary, the cluster walk finishes
    normally and reports `truncated=False`, indistinguishable from a genuine
    complete parse. Three independent reproductions delivered a "complete" SRT
    missing cues that way, including on an ordinary bounded cluster.

    Byte count, by contrast, cannot be fooled. `src.total` is always known and
    accurate here (extract_srt refuses to proceed without it), so for any range
    inside the file a compliant server owes exactly what was asked, and anything
    less is truncation -- whatever the bytes happen to look like."""
    if not src.total or offset >= src.total:
        return False
    if len(got) >= min(asked, src.total - offset):
        return False
    # Short. That is USUALLY truncation -- but not if the file simply ends here
    # and the size probe was optimistic. `total` comes from a Content-Range or
    # Content-Length on a one-byte probe; a server that reports slightly more
    # than it will serve would otherwise make every read near the tail look
    # truncated, forever, at the same offset, on every attempt -- a file that
    # can never complete no matter how many times it is played. (Reproduced: a
    # total inflated by 5000 bytes on a 525KB file froze the extraction at the
    # same cluster across eight attempts, banking nothing new.)
    #
    # One tiny probe tells the two apart -- but ONLY if it can distinguish "the
    # provider says there is nothing there" from "the read failed". src.read()
    # cannot: it returns b'' for a tripped breaker, for any exception, and for a
    # server that ignores Range and answers 200, all of which are real behaviours
    # this file already handles elsewhere. Believing an empty read means EOF
    # would shrink `total` on a genuine truncation that landed on a clean element
    # boundary -- the one case parsing cannot catch either -- and hand back a
    # subtitle with lines silently missing. So ask probe_beyond(), which says
    # 'eof' only when the provider states it (a 416, or a Content-Range length),
    # and treat anything it cannot establish as truncation.
    probe_at = offset + len(got)
    # Hand the probe a stretch of the file we already hold, immediately before
    # the point in question. If a provider answers "nothing here" without saying
    # 416, re-reading those known bytes is what separates a real end of file
    # from a transport that has simply stopped delivering.
    _n = min(_PROBE_CONTROL, len(got))
    _known = (probe_at - _n, bytes(got[-_n:])) if _n >= 4 else None
    try:
        verdict = src.probe_beyond(probe_at, _known)
    except Exception:
        verdict = 'unknown'
    if verdict == 'more':
        return True                       # there IS more -- genuinely truncated
    if verdict != 'eof':
        # Unknown. Deferring costs an attempt; the alternative is delivering a
        # subtitle with lines missing.
        return True
    if src._log:
        src._log('file ends at %d though the provider reported %d -- '
                 'trusting the bytes, not the header'
                 % (probe_at, src.total))
    src.total = probe_at
    return False


def _run_concurrently(fn, work, workers, should_stop):
    """Run fn(*item) over `work` with `workers` threads, stopping early when
    `should_stop()` says so. Plain threads and an index counter -- no executor,
    because Kodi's Python has been known to leave one alive after an addon is
    torn down, and this must not outlive the extraction that started it.

    Every worker is a daemon and the caller joins them all, so an abort ends the
    phase as soon as the in-flight reads return rather than at the end of the
    list."""
    nxt = [0]
    lock = _threading.Lock()
    done = set()

    def _worker():
        while True:
            if should_stop():
                return
            with lock:
                i = nxt[0]
                if i >= len(work):
                    return
                nxt[0] += 1
            try:
                fn(*work[i])
            except Exception:
                # Do NOT record it as done. The caller re-runs everything this
                # returns short of, so an item that faulted is retried on one
                # connection instead of disappearing -- the difference between
                # deferring and handing back a subtitle with a hole in it.
                return
            with lock:
                done.add(i)

    threads = [_threading.Thread(target=_worker) for _ in range(workers)]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join()
    # The COMPLETED prefix, never the dispatched count: an item is only left
    # behind if every item before it also finished. Anything at or after this
    # index the caller runs itself, and re-running one that did finish is
    # harmless (duplicate cues are dropped when the SRT is built).
    n = 0
    while n < len(work) and n in done:
        n += 1
    return n


def _extract_cues_http(src, positions, entries, want, deadline_s, t0, abort_cb,
                       log, progress_cb=None, done_clusters=None,
                       scan_pending=None):
    """HTTP/debrid: ONE keep-alive connection, single-range serial. Per cue,
    two strategies chosen by whether the Cues carried a CueRelativePosition:
      * relpos present -> TARGETED: a small window AT the subtitle block, one
        request per block (see _fetch_cluster_blocks -- the cluster prefix is
        learned once for the file and CueTime supplies the timestamp, so the
        per-cue header read is gone). ~18x less data than a full cluster --
        gentle on the player's bandwidth over a scattered remux (the debrid
        case). Cues are walked CLUSTER at a time so a cluster is only ever
        window-scanned once.
      * relpos absent  -> WINDOW SCAN: fetch a ~1.79MB window at the cluster
        start and parse forward (his proven fallback), topping up the rare
        cluster bigger than the window.
    Player-safe by construction (single serial connection, byte/time caps, 429
    circuit-breaker). Returns True on a COMPLETE pass, False to defer."""
    budget = max(deadline_s, 90.0)
    finished = done_clusters if done_clusters is not None else set()
    # Clusters a previous pass already PROVED the targeted path cannot resolve.
    # Without carrying these, every attempt re-ran their (hopeless) targeted
    # fetches before reaching the scan phase -- so on a file with unresolvable
    # cues the scan was never reached and resume could not converge at all.
    needs_scan = scan_pending if scan_pending is not None else set()
    rel_by_cpos = {}
    scan_cues = []
    for (c, r, t) in positions:
        if r is None:
            scan_cues.append(c)
        else:
            rel_by_cpos.setdefault(c, []).append((r, t))
    total = len(positions)
    # Whatever an earlier attempt finished is already in `entries` -- skip it.
    carried = sum(len(v) for c, v in rel_by_cpos.items() if c in finished)
    carried += sum(1 for c in scan_cues if c in finished)
    rel_clusters = [(c, sorted(rel_by_cpos[c])) for c in sorted(rel_by_cpos)
                    if c not in finished and c not in needs_scan]
    scan_cues = [c for c in scan_cues if c not in finished]
    scan_cues.extend(c for c in sorted(needs_scan) if c not in finished)
    n_rel = sum(len(v) for _c, v in rel_clusters)
    log('%d sub-cue cluster(s): %d targeted (relpos) in %d cluster(s) + %d '
        'window-scan%s; caps %dMB / %.0fs'
        % (total, n_rel, len(rel_clusters), len(scan_cues),
           (' (%d already done)' % carried) if carried else '',
           _HTTP_TOTAL_CAP // (1 << 20), budget))

    def _cost():
        """What this attempt actually spent -- the numbers that were missing
        from every abort message, so a field log can say WHY it was slow."""
        el = max(time.time() - t0, 0.001)
        return ('%d/%d cue(s), %d read (%d GET, %d hdr, %d free), %.1fMB, '
                '%.0fs, pace %.2fs, %d backoff(s), %.2f cue/s'
                % (done, total, src.reqs, getattr(src, 'http_reqs', 0),
                   getattr(src, '_hdr_reads', 0),
                   getattr(src, '_one_shot', 0), src.fetched / 1e6, el,
                   getattr(src, '_pace', 0.0), getattr(src, '_429_total', 0),
                   done / el))

    def _defer():
        """Return a reason string when we must stop, else None."""
        if src.tripped:
            return 'circuit-breaker tripped (CDN 429/5xx)'
        _got = src.fetched_now()
        if _got >= _HTTP_TOTAL_CAP:
            return 'http byte cap reached (%.0fMB)' % (_got / 1e6)
        if (time.time() - t0) > budget:
            return 'http time budget reached (%.0fs)' % (time.time() - t0)
        if _aborted(abort_cb):
            return 'http extract aborted (playback ended)'
        return None

    def _tick(n):
        """Report progress to the UI (throttled). Never fatal."""
        if src._stats is not None:
            src._stats['done'] = min(n, total)
            src._stats['total'] = total
        if progress_cb:
            try:
                progress_cb(min(n, total), total)
            except Exception:
                pass

    done = carried
    state = {'done': carried, 'stop': None}
    state_lock = _threading.Lock()

    def _one_cluster(cpos, items):
        """Fetch ONE cluster's blocks and record the outcome. Safe to run from
        several threads: the only shared things it touches are `entries` and the
        two cluster sets, all under `state_lock`."""
        if state['stop'] is not None:
            return
        reason = _defer()
        if reason:
            with state_lock:
                if state['stop'] is None:
                    state['stop'] = reason
            return
        local = []
        try:
            got = _fetch_cluster_blocks(src, cpos, items, want, local, log)
        except Exception as e:
            # An unexpected fault here must NEVER end as a quiet success. Left
            # to escape, this cluster's blocks land in none of `entries`,
            # `finished` or `needs_scan`, the pass still reports COMPLETE, and
            # the resume file -- the one thing that could have recovered the
            # gap on a later attempt -- is cleared. That is a subtitle silently
            # missing lines, which is the exact outcome this whole function is
            # built to prevent. Treat it as "could not resolve these blocks" and
            # let the window scan below cover the cluster, the same path a short
            # read or an odd prefix already takes.
            log('cluster at %d failed unexpectedly (%r) -- window-scanning it'
                % (cpos, e))
            got = 0
        with state_lock:
            entries.extend(local)
            if got < len(items):
                if src.tripped:
                    if state['stop'] is None:
                        state['stop'] = 'circuit-breaker tripped mid-fetch'
                    return
                # Couldn't resolve every block from relpos (odd prefix / short
                # read / wrong track) -> window-scan THIS cluster so we never
                # drop a line. Duplicates are dropped in _entries_to_srt, so
                # re-finding the ones we already have is harmless. NOT marked
                # finished -- the scan below is what completes it -- but
                # remembered as scan-pending, so a later attempt goes straight
                # to the scan instead of paying for the targeted fetches all
                # over again.
                scan_cues.append(cpos)
                needs_scan.add(cpos)
            else:
                finished.add(cpos)
            state['done'] += len(items)
            n = state['done']
            if n % 100 < len(items):
                log('extract progress: %d/%d cue(s), %d req, %.0fMB'
                    % (n, total, src.reqs, src.fetched / 1e6))
            _tick(n)

    # 1) targeted relpos fetches.
    #
    # The FIRST cluster is deliberately alone: it is the one that learns the
    # file's cluster prefix and proves CueTime agrees with it, and every later
    # cluster is fast only because it can rely on both. Starting three at once
    # would have three of them pay that header read and verify the same thing
    # three times.
    if rel_clusters:
        def _healthy():
            """Concurrency is for the HEALTHY path only, and this is the whole
            safety argument for it.

            It needs the two shortcuts already proven on the first cluster (the
            prefix learned and CueTime agreeing), because a file whose prefix
            width changes mid-run has clusters re-learning it and three of them
            racing on that one value is neither faster nor sound. And it needs a
            provider that has not pushed back: back-pressure is measured in
            consecutive refusals against progress, and three connections
            accumulate refusals three times faster against the same progress --
            which would trip the breaker on exactly the flaky-but-usable
            provider the serial code was carefully taught to crawl through
            instead of abandoning.

            So the moment either stops being true we finish serially, in the
            exact code path all of that behaviour was tuned on."""
            return (src._prefix is not None and src._cue_time_ok is True
                    and getattr(src, '_429_total', 0) == 0
                    and getattr(src, '_prefix_relearn', 0) == 0
                    and not needs_scan)

        # Seed serially until both shortcuts are settled. It takes two clusters,
        # not one: the first learns the prefix, and CueTime can only be PROVEN
        # against a cluster with a non-zero timestamp -- the first cluster of
        # every file sits at 0, where the check would pass for a muxer that
        # wrote CueTime relative to its cluster and be wrong everywhere after.
        # If a file has not settled after a few clusters it never will (no
        # CueTime at all, say), so stop seeding and let it run serially.
        seed = 0
        while seed < len(rel_clusters) and state['stop'] is None:
            _one_cluster(*rel_clusters[seed])
            seed += 1
            if _healthy() or seed >= _CONC_SEED_MAX:
                break
        rest = rel_clusters[seed:]

        i = 0
        conns = (src.open_pool() if (src.is_http and rest and _healthy())
                 else 1)
        try:
            if conns > 1:
                # Remember the pace we are starting from. Asking more often is
                # what makes this faster, so if the provider refuses, the
                # refusals are OURS -- and their cost must not outlive the
                # experiment (see restore_pace).
                pace_before = getattr(src, '_pace', None)
                log('%d connections for the remaining %d cluster(s): the pace '
                    'stays %.2fs but the round trip stops counting, so we ask '
                    'about %d times as often'
                    % (conns, len(rest), pace_before or 0.0, conns))
                i = _run_concurrently(
                    _one_cluster, rest, conns,
                    lambda: state['stop'] is not None or src.tripped
                    or _aborted(abort_cb) or not _healthy())
                if i < len(rest):
                    log('finishing the last %d cluster(s) on one connection '
                        '(%d backoff(s), %d cluster(s) needing a scan)'
                        % (len(rest) - i, getattr(src, '_429_total', 0),
                           len(needs_scan)))
                    src.restore_pace(pace_before)
        finally:
            src.close_pool()
        for (cpos, items) in rest[i:]:
            if state['stop'] is not None:
                break
            _one_cluster(cpos, items)
    done = state['done']
    if state['stop'] is not None:
        log(state['stop'] + ' -- deferring [' + _cost() + ']')
        return False

    # 2) window-scan the remainder (no-relpos cues + any relpos misses)
    if scan_cues:
        ranges = _coalesce_ranges(sorted(set(scan_cues)), _CLUSTER_WINDOW_HTTP,
                                  _COALESCE_GAP, _MAX_RANGE, src.total)
        for (rstart, rend, cposes) in ranges:
            reason = _defer()
            if reason:
                log(reason + ' -- deferring')
                return False
            _want_n = min(rend - rstart, _HTTP_TOTAL_CAP - src.fetched)
            window = src.read(rstart, _want_n)
            if _short_read(src, rstart, _want_n, window):
                log('provider returned %d of %d bytes at %d (no 429) -- '
                    'deferring rather than trusting a truncated window'
                    % (len(window), _want_n, rstart))
                return False
            if src.tripped:
                log('circuit-breaker tripped mid-fetch -- deferring')
                return False
            # A SHORT BODY IS A FAILURE, not an empty region. A CDN may answer a
            # large Range with 200/206 and fewer bytes than asked -- a capped
            # response, or a connection that dropped mid-stream -- and no 429 is
            # ever involved, so the circuit-breaker, the backoff counter and the
            # retry loop are all blind to it. Skipping the clusters it failed to
            # cover let the pass finish and report success while their lines were
            # simply absent: 10 cues of 24 delivered as a whole subtitle. That is
            # precisely the outcome this function exists to prevent, so treat
            # every uncovered cluster as a reason to defer -- the resume file
            # keeps what was collected and the next attempt retries them.
            if not window:
                log('empty window for %d cluster(s) at %d (short body, no 429) '
                    '-- deferring rather than dropping them' % (len(cposes),
                                                                rstart))
                return False
            for cpos in cposes:
                if src.tripped:
                    break
                off = cpos - rstart
                if not (0 <= off < len(window)):
                    log('cluster at %d not covered by a %d-byte window (short '
                        'body, no 429) -- deferring' % (cpos, len(window)))
                    return False
                _end, truncated = _collect_one_cluster(window[off:], want, entries)
                if not _end:
                    # Nothing parsed at all: the bytes at this offset do not
                    # begin a Cluster. `truncated` is False here, which reads
                    # identically to "clean end of a cluster with nothing left"
                    # -- so without this the cue is marked finished and its lines
                    # are lost for good.
                    log('no cluster found at %d in the window (short/misaligned '
                        'body) -- deferring' % cpos)
                    return False
                if not truncated:
                    finished.add(cpos)   # covered cleanly -- never redo it
                    needs_scan.discard(cpos)
                    continue
                # Window too small for this cluster (a big co-located video/audio
                # block sits around the subtitle one) -> a LATER subtitle block
                # was not seen. Top-up the whole cluster; dedup in _entries_to_srt
                # drops any re-parsed block. STILL truncated -> DEFER (never
                # deliver a silently-partial subtitle).
                if src.fetched >= _HTTP_TOTAL_CAP:
                    log('byte cap reached at top-up -- deferring')
                    return False
                _want_t = min(_CLUSTER_TOPUP_MAX,
                              _HTTP_TOTAL_CAP - src.fetched)
                tup = src.read(cpos, _want_t)
                if _short_read(src, cpos, _want_t, tup):
                    log('provider returned %d of %d bytes at the top-up for %d '
                        '(no 429) -- deferring' % (len(tup), _want_t, cpos))
                    return False
                if src.tripped:
                    log('circuit-breaker tripped during top-up -- deferring')
                    return False
                _tend, tup_trunc = _collect_one_cluster(tup, want, entries)
                if not _tend:
                    log('top-up at %d returned nothing parseable (short body) '
                        '-- deferring' % cpos)
                    return False
                if tup_trunc:
                    log('cluster exceeds top-up cap (%dMB) -- deferring to avoid '
                        'a partial subtitle' % (_CLUSTER_TOPUP_MAX >> 20))
                    return False
                finished.add(cpos)       # the top-up completed it
                needs_scan.discard(cpos)
            done += len(cposes)
            _tick(done)

    if src.tripped:
        log('circuit-breaker tripped -- deferring')
        return False
    if progress_cb:
        _tick(total)   # 100% on a complete pass
    return True
