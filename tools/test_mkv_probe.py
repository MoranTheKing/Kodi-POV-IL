#!/usr/bin/env python3
"""Offline tests for resources/lib/mkv_probe.py (SubSync S4).

Builds a synthetic-but-valid Matroska file (video track + two subtitle
tracks, clusters spread across the file with filler) and verifies the probe
recovers the known subtitle cue times -- via LOCAL read AND via a real HTTP
server with Range support. Then feeds the probe output into
sync_align.verify_cues to close the loop.
"""
import os
import sys
import struct
import random
import tempfile
import threading

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..',
    'addons', 'service.subtitles.kodipovilai', 'resources', 'lib'))

import mkv_probe as mp  # noqa: E402
import sync_align as sa  # noqa: E402

FAILS = []


def check(desc, cond, extra=''):
    if cond:
        print('  ok  - ' + desc)
    else:
        FAILS.append(desc)
        print('  FAIL- ' + desc + (' [' + extra + ']' if extra else ''))


# ---- minimal EBML writer -----------------------------------------------------

def vint_size(val):
    """Encode an EBML size (1-8 bytes, marker bit)."""
    for length in range(1, 9):
        if val < (1 << (7 * length)) - 1:
            out = val | (1 << (7 * length))
            return out.to_bytes(length, 'big')
    raise ValueError


def raw_id(eid):
    length = (eid.bit_length() + 7) // 8
    return eid.to_bytes(length, 'big')


def el(eid, payload):
    return raw_id(eid) + vint_size(len(payload)) + payload


def uint_el(eid, val, width=None):
    length = width or max(1, (val.bit_length() + 7) // 8)
    return el(eid, val.to_bytes(length, 'big'))


def str_el(eid, s):
    return el(eid, s.encode('ascii'))


def simpleblock(track, rel_ts, payload=b'\x00'):
    body = vint_size(track) + struct.pack('>h', rel_ts) + b'\x80' + payload
    return el(0xA3, body)


def blockgroup(track, rel_ts, dur, payload=b'\x00'):
    blk = el(0xA1, vint_size(track) + struct.pack('>h', rel_ts)
             + b'\x00' + payload)
    return el(0xA0, blk + uint_el(0x9B, dur, 2))


def build_mkv(sub_times, forced_times, cluster_span_ms=5000,
              video_block_bytes=6000):
    """A valid MKV: track 1 = video, track 3 = eng text subs (BlockGroups with
    durations at sub_times), track 4 = FORCED sparse track. Clusters every
    cluster_span_ms with chunky video SimpleBlocks as filler."""
    ebml = el(0x1A45DFA3,
              uint_el(0x4286, 1) + uint_el(0x42F7, 1) + uint_el(0x42F2, 4)
              + uint_el(0x42F3, 8) + str_el(0x4282, 'matroska')
              + uint_el(0x4287, 4) + uint_el(0x4285, 2))
    info = el(0x1549A966, uint_el(0x2AD7B1, 1000000, 3))
    tracks = el(0x1654AE6B,
                el(0xAE, uint_el(0xD7, 1) + uint_el(0x83, 1)
                   + str_el(0x86, 'V_MPEG4/ISO/AVC'))
                + el(0xAE, uint_el(0xD7, 3) + uint_el(0x83, 0x11)
                     + str_el(0x86, 'S_TEXT/UTF8') + str_el(0x22B59C, 'eng'))
                + el(0xAE, uint_el(0xD7, 4) + uint_el(0x83, 0x11)
                     + str_el(0x86, 'S_TEXT/UTF8') + str_el(0x22B59C, 'heb')
                     + uint_el(0x55AA, 1)))
    total_ms = max(sub_times) + 10000
    clusters = b''
    rng = random.Random(3)
    subs_iter = sorted(sub_times)
    forced_iter = sorted(forced_times)
    si = fi = 0
    ts = 0
    while ts < total_ms:
        body = uint_el(0xE7, ts, 4)
        # video filler blocks
        for k in range(4):
            body += simpleblock(1, k * 40, bytes([rng.randrange(256)])
                                * video_block_bytes)
        while si < len(subs_iter) and ts <= subs_iter[si] < ts + cluster_span_ms:
            body += blockgroup(3, subs_iter[si] - ts, 2000,
                               b'Hello there, subtitle line')
            si += 1
        while fi < len(forced_iter) and ts <= forced_iter[fi] < ts + cluster_span_ms:
            body += simpleblock(4, forced_iter[fi] - ts, b'forced')
            fi += 1
        clusters += el(0x1F43B675, body)
        ts += cluster_span_ms
    segment = el(0x18538067, info + tracks + clusters)
    return ebml + segment


# Dialogue-ish times over ~12 minutes.
rng = random.Random(11)
SUB_TIMES, t = [], 8000
while t < 12 * 60 * 1000:
    SUB_TIMES.append(t)
    t += rng.randint(2000, 7000)
FORCED_TIMES = SUB_TIMES[::40]

mkv_bytes = build_mkv(SUB_TIMES, FORCED_TIMES)
tmpdir = tempfile.mkdtemp()
mkv_path = os.path.join(tmpdir, 'sample.mkv')
open(mkv_path, 'wb').write(mkv_bytes)
print('synthetic mkv: %.1f MB, %d sub cues' % (len(mkv_bytes) / 1e6,
                                               len(SUB_TIMES)))

logs = []


def log(m):
    logs.append(m)


print('== local-file probe ==')
res = mp.subtitle_reference(mkv_path, window_bytes=512 * 1024,
                            max_windows=12, log=log)
check('probe returned a result', res is not None, '\n'.join(logs))
if res:
    check('picked the non-forced eng track',
          res['track'].get('lang') == 'eng' and not res['track'].get('forced'),
          str(res['track']))
    got = set(c['start'] for c in res['cues'])
    real = set(SUB_TIMES)
    check('>= 25 cues recovered', len(got) >= 25, str(len(got)))
    check('every recovered cue is a REAL cue time (no garbage)',
          got.issubset(real), str(sorted(got - real)[:5]))

print('== HTTP Range probe (real socket) ==')
import http.server


class RangeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        rng_h = self.headers.get('Range') or ''
        m = __import__('re').match(r'bytes=(\d+)-(\d+)', rng_h)
        if not m:
            self.send_response(200)
            self.send_header('Content-Length', str(len(mkv_bytes)))
            self.end_headers()
            self.wfile.write(mkv_bytes)
            return
        a, b = int(m.group(1)), min(int(m.group(2)), len(mkv_bytes) - 1)
        chunk = mkv_bytes[a:b + 1]
        self.send_response(206)
        self.send_header('Content-Range',
                         'bytes %d-%d/%d' % (a, b, len(mkv_bytes)))
        self.send_header('Content-Length', str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(('127.0.0.1', 0), RangeHandler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = 'http://127.0.0.1:%d/sample.mkv' % srv.server_port
logs2 = []
res2 = mp.subtitle_reference(url, window_bytes=512 * 1024, max_windows=12,
                             log=logs2.append)
check('http probe returned a result', res2 is not None, '\n'.join(logs2))
if res2:
    check('http probe cues match local probe',
          set(c['start'] for c in res2['cues'])
          == set(c['start'] for c in res['cues']))
    check('budget accounted', res2['bytes'] > 0)
srv.shutdown()

print('== probe cues as sync reference (closing the loop) ==')
if res:
    # Candidate Hebrew shifted +9s from the file's true timeline.
    def _stamp(ms):
        h, rem = divmod(int(ms), 3600000)
        m2, rem = divmod(rem, 60000)
        s, msx = divmod(rem, 1000)
        return '%02d:%02d:%02d,%03d' % (h, m2, s, msx)
    blocks = []
    for i, st in enumerate(sorted(SUB_TIMES), 1):
        blocks.append('%d\n%s --> %s\nשלום לכולם, שורת דיאלוג' % (
            i, _stamp(st + 9000), _stamp(st + 9000 + 1800)))
    cand = '\n\n'.join(blocks) + '\n'
    v = sa.verify_cues(res['cues'], cand)
    check('verdict FIXABLE', v['status'] == sa.STATUS_FIXABLE, v['diag'])
    check('offset ~ +9000', abs(v['offset_ms'] - 9000) <= 500, v['diag'])
    fixed = sa.retime(cand, v['scale'], v['offset_ms'])
    v2 = sa.verify_cues(res['cues'], fixed)
    check('after retime CONFIRMED', v2['status'] == sa.STATUS_CONFIRMED,
          v2['diag'])

print()
if FAILS:
    print('FAILED (%d):' % len(FAILS))
    for f in FAILS:
        print('  - ' + f)
    sys.exit(1)
print('ALL TESTS PASSED')
