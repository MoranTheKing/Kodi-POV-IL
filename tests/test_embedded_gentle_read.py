"""The embedded track's head and index are read in small pieces over HTTP, the
head only as far as the first Cluster, and the connection is handed back the
moment the reading ends (MoranSubs 0.3.81).

QA of 13 Nov 2026 (TorBox at a busy hour): the extraction opened with one 2 MB
head read and one 1.3 MB index read, right after the subtitle list let go of
the pause, and the picture froze 6-12 s later in most runs; without an
extraction nothing froze.

The fixtures are real Matroska files made by ffmpeg (black 32x32 video, one
S_TEXT/UTF8 English track of 40 lines with per-cue Cues; attached.mkv also
carries a 300 KB attachment, so its first Cluster starts past the first
piece):
  ffmpeg -f lavfi -i color=c=black:size=32x32:rate=1:duration=300 -i subs.srt
         -map 0:v -map 1:s -c:v libx264 -g 10 -c:s srt
         -metadata:s:s:0 language=eng [-attach zeros.bin
         -metadata:s:t mimetype=application/octet-stream] plain.mkv
Only the network is replaced: a session serving the file's bytes by Range."""
import importlib.util
import io
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'service.subtitles.kodipovilai/resources/lib/embedded_extract.py'
FIXTURES = ROOT / 'tests/fixtures/embedded_mkv'
URL = 'https://cdn.example/dld/film.mkv'


def load():
    spec = importlib.util.spec_from_file_location('embedded_gentle_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    stubs = {name: types.ModuleType(name) for name in ('xbmc', 'xbmcaddon', 'xbmcvfs', 'xbmcgui')}
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class Response(object):

    def __init__(self, body, start, total):
        self.status_code = 206
        self.headers = {'Content-Range': 'bytes %d-%d/%d' % (start, start + len(body) - 1, total),
                        'Content-Length': str(len(body))}
        self.raw = io.BytesIO(body)

    def close(self):
        pass


class Multipart(object):
    """A 206 multipart/byteranges answer (or, `cut`, one whose last part is short)."""

    def __init__(self, blob, spans, cut=False):
        self.status_code = 206
        out = bytearray()
        for a, b in spans:
            b = min(b, len(blob) - 1)                   # as a server does at the end of the file
            out += (b'--XyZ\r\nContent-Type: application/octet-stream\r\n'
                    b'Content-Range: bytes %d-%d/%d\r\n\r\n' % (a, b, len(blob)))
            out += blob[a:b + 1] + b'\r\n'
        out += b'--XyZ--\r\n'
        if cut:
            out = out[:len(out) - 200]
        self.headers = {'Content-Type': 'multipart/byteranges; boundary=XyZ', 'Content-Length': str(len(out))}
        self.raw = io.BytesIO(bytes(out))

    def close(self):
        pass


class Busy(object):
    status_code = 429
    headers = {'Content-Length': '0'}
    raw = io.BytesIO(b'')

    def close(self):
        pass


class Session(object):
    """Serves `blob` by Range. `asked` is every request as (offset, length); a request for many ranges
    is in `multi` as its list of ranges. `many`: how such a request is answered -- 'multipart' (as
    TorBox's nodes that support it), 'first' (only the first range, a node that does not), 'busy'
    (429), 'cut' (the last part short)."""

    def __init__(self, blob, on_get=None, many='multipart'):
        self.blob = blob
        self.asked = []
        self.multi = []
        self.order = []             # 'single' / 'multi', in the order asked
        self.many = many
        self.open = True            # a requests.Session reconnects after close()
        self.reopened = 0
        self.on_get = on_get

    def get(self, url, headers=None, timeout=None, stream=False):
        if not self.open:
            self.open = True
            self.reopened += 1
        spans = [(int(a), int(b)) for a, b in re.findall(r'(\d+)-(\d+)', headers['Range'])]
        self.order.append('multi' if len(spans) > 1 else 'single')
        if len(spans) > 1:
            self.multi.append(spans)
            if self.many == 'busy':
                return Busy()
            if self.many == 'reset':
                raise ConnectionError('reset by peer')
            if self.many == 'first':
                a, b = spans[0]
                r = Response(self.blob[a:b + 1], a, len(self.blob))
                r.headers['Content-Type'] = 'video/x-matroska'
                return r
            return Multipart(self.blob, spans, cut=(self.many == 'cut'))
        start, end = spans[0]
        self.asked.append((start, end - start + 1))
        if self.on_get:
            self.on_get(len(self.asked))
        return Response(self.blob[start:end + 1], start, len(self.blob))

    def close(self):
        self.open = False


class Gentle(unittest.TestCase):

    def setUp(self):
        self.ee = load()
        self.sessions = []
        self.patches = [
            patch.object(self.ee, '_HTTP_REQ_PACE_S', 0.0),
            patch.object(self.ee, '_pace_memory_load', lambda url: None),
            patch.object(self.ee, '_pace_memory_save', lambda *a: None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def serve(self, name, on_get=None, pad=0, many='multipart'):
        # `pad`: zeros after the file, so it is as long as a film and reading
        # past what is needed shows up as requests
        blob = (FIXTURES / name).read_bytes() + bytes(pad)

        def new_session():
            s = Session(blob, on_get, many)
            self.sessions.append(s)
            return s
        return blob, patch.object(self.ee, '_new_session', new_session)

    def requests(self):
        # the 1-byte size probe in _Source.__init__ is not a data read
        return [a for s in self.sessions for a in s.asked if a[1] > 1]

    # ---- the head --------------------------------------------------------

    def test_head_stops_at_the_first_cluster(self):
        for name, pieces in (('plain.mkv', 1), ('attached.mkv', 2)):
            with self.subTest(name):
                blob, net = self.serve(name, pad=8 * 1024 * 1024)
                self.sessions[:] = []
                with net:
                    src = self.ee._Source(URL)
                    src._piece = self.ee._HTTP_PIECE
                    got = self.ee._parse_head(src, self.ee.DEFAULT_HEAD_BYTES, lambda m: None)
                local = self.ee._parse_head(self.ee._Source(str(FIXTURES / name)),
                                            self.ee.DEFAULT_HEAD_BYTES, lambda m: None)
                self.assertEqual(got, local)
                asked = self.requests()
                self.assertEqual(len(asked), pieces, asked)
                self.assertTrue(all(n <= self.ee._HTTP_PIECE for _o, n in asked))
                first_cluster = blob.find(b'\x1f\x43\xb6\x75')
                self.assertLess(sum(n for _o, n in asked) - self.ee._HTTP_PIECE, first_cluster)

    def test_head_in_any_piece_size_parses_as_one_read(self):
        # whatever the piece size, the parse sees what a single 2 MB read gave it
        for name in ('plain.mkv', 'attached.mkv'):
            local = self.ee._parse_head(self.ee._Source(str(FIXTURES / name)),
                                        self.ee.DEFAULT_HEAD_BYTES, lambda m: None)
            for piece in (1000, 4093, 65536, 300000, 4 * 1024 * 1024):
                with self.subTest(name=name, piece=piece):
                    src = self.ee._Source(str(FIXTURES / name))
                    src._piece = piece
                    self.assertEqual(self.ee._parse_head(src, self.ee.DEFAULT_HEAD_BYTES, lambda m: None), local)

    def test_head_enough(self):
        ee = self.ee
        blob = (FIXTURES / 'attached.mkv').read_bytes()
        first_cluster = blob.find(b'\x1f\x43\xb6\x75')
        self.assertFalse(ee._head_enough(b''))
        self.assertFalse(ee._head_enough(blob[:3]))                  # inside the EBML header id
        self.assertFalse(ee._head_enough(blob[:200]))                # the attachment is cut off
        self.assertFalse(ee._head_enough(blob[:first_cluster + 2]))  # the Cluster id is cut off
        self.assertTrue(ee._head_enough(blob[:first_cluster + 12]))
        self.assertTrue(ee._head_enough(b'RIFF....AVI LIST'))         # not Matroska: the parse raises anyway
        ebml = b'\x1a\x45\xdf\xa3\x80'                                 # EBML header, empty
        seg = b'\x18\x53\x80\x67\x01\xff\xff\xff\xff\xff\xff\xff'     # Segment of unknown size
        unknown = b'\x12\x54\xc3\x67\x01\xff\xff\xff\xff\xff\xff\xff'  # Tags of unknown size
        self.assertTrue(ee._head_enough(ebml + seg + unknown))       # the parse stops there too
        self.assertFalse(ee._head_enough(ebml + seg + b'\x11\x4d\x9b\x74\x8a' + b'\x00' * 5))
        self.assertTrue(ee._head_enough(ebml + seg + b'\x11\x4d\x9b\x74\x85' + b'\x00' * 5
                                        + b'\x1f\x43\xb6\x75\x80'))

    # ---- reads in pieces ---------------------------------------------------

    def test_a_long_read_goes_in_pieces(self):
        blob, net = self.serve('attached.mkv')
        with net:
            src = self.ee._Source(URL)
            src._piece = 100000
            got = src.read(1000, 250000)
        self.assertEqual(got, blob[1000:251000])
        self.assertEqual(self.requests(), [(1000, 100000), (101000, 100000), (201000, 50000)])

    def test_without_pieces_it_is_one_request(self):
        blob, net = self.serve('attached.mkv')
        with net:
            src = self.ee._Source(URL)
            got = src.read(1000, 250000)
        self.assertEqual(got, blob[1000:251000])
        self.assertEqual(self.requests(), [(1000, 250000)])

    def test_a_stop_between_pieces_ends_the_read(self):
        blob, net = self.serve('attached.mkv')
        calls = []
        with net:
            src = self.ee._Source(URL)
            src._piece = 100000
            src._abort_cb = lambda: calls.append(1) or len(calls) > 1
            got = src.read(0, 250000)
        self.assertEqual(got, blob[:100000])
        self.assertTrue(src.tripped)
        self.assertEqual(self.requests(), [(0, 100000)])

    def test_the_end_of_the_file_ends_the_read(self):
        blob, net = self.serve('attached.mkv')
        with net:
            src = self.ee._Source(URL)
            src._piece = 100000
            got = src.read(len(blob) - 150000, 400000)
        self.assertEqual(got, blob[-150000:])
        self.assertEqual(len(self.requests()), 2)

    # ---- the whole extraction -----------------------------------------------

    def test_extraction_over_http_matches_the_local_file(self):
        for name in ('plain.mkv', 'attached.mkv'):
            with self.subTest(name):
                self.sessions[:] = []
                local = self.ee.extract_srt(str(FIXTURES / name), lang='en')
                self.assertEqual(local.count('-->'), 40)
                blob, net = self.serve(name)
                with net:
                    got = self.ee.extract_srt(URL, lang='en', allow_http=True)
                self.assertEqual(got, local)
                asked = self.requests()
                self.assertTrue(all(n <= self.ee._HTTP_PIECE for _o, n in asked), asked)
                self.assertTrue(self.sessions and not any(s.open for s in self.sessions))

    def test_an_interrupted_extraction_hands_the_connection_back(self):
        blob, net = self.serve('attached.mkv')
        n = []
        with net:
            got = self.ee.extract_srt(URL, lang='en', allow_http=True,
                                      abort_cb=lambda: n.append(1) or len(n) > 6)
        self.assertIsNone(got)
        self.assertTrue(self.sessions and not any(s.open for s in self.sessions))

    def test_standing_aside_closes_the_connection_and_the_reading_goes_on(self):
        local = self.ee.extract_srt(str(FIXTURES / 'attached.mkv'), lang='en')
        blob, net = self.serve('attached.mkv')
        stats = {}
        calls = []

        def abort():
            calls.append(1)
            if len(calls) == 5:
                stats['release']()      # what the caller's buffer wait does
                self.assertFalse(self.sessions[0].open)
            return False
        with net:
            got = self.ee.extract_srt(URL, lang='en', allow_http=True, abort_cb=abort, stats=stats)
        self.assertEqual(got, local)
        self.assertEqual([s.reopened for s in self.sessions], [1])
        self.assertFalse(self.sessions[0].open)

    def test_a_refused_http_extraction_hands_the_connection_back(self):
        blob, net = self.serve('plain.mkv')
        with net:
            self.assertIsNone(self.ee.extract_srt(URL, lang='en', allow_http=False))
        self.assertTrue(self.sessions and not any(s.open for s in self.sessions))

    def test_the_align_read_is_gentle_too(self):
        local = self.ee.cue_reference_times_multi(str(FIXTURES / 'attached.mkv'), ['en'])
        self.assertEqual(len(local.get('en') or []), 40)
        blob, net = self.serve('attached.mkv')
        with net:
            got = self.ee.cue_reference_times_multi(URL, ['en'], allow_http=True)
        self.assertEqual(got, local)
        asked = self.requests()
        # the head in pieces, only as far as the first Cluster; the rest as
        # before, one request each (this path has no buffer gate)
        piece = self.ee._HTTP_PIECE
        self.assertEqual(asked[:2], [(0, piece), (piece, piece)])
        self.assertTrue(any(n > piece for _o, n in asked[2:]), asked)
        self.assertTrue(self.sessions and not any(s.open for s in self.sessions))

    def test_cluster_reads_use_the_larger_piece(self):
        ee = self.ee
        blob, net = self.serve('attached.mkv', pad=12 * 1024 * 1024)
        seen = []
        real = ee._read_cues

        def read_cues(src, *a):
            out = real(src, *a)
            seen.append(src._piece)
            return out
        with net, patch.object(ee, '_read_cues', read_cues), \
                patch.object(ee, '_extract_cues_http', lambda src, *a, **k: seen.append(src._piece) or False):
            ee.extract_srt(URL, lang='en', allow_http=True)
        # the index itself in small pieces, the clusters after it in large ones
        self.assertEqual(seen, [ee._HTTP_PIECE, ee._HTTP_PIECE_CLUSTERS])

    def test_a_head_cut_short_is_refused(self):
        blob, net = self.serve('attached.mkv', pad=4 * 1024 * 1024)
        n = []

        def abort():
            n.append(1)
            return len(n) > 1           # the second piece of the head never comes
        with net:
            src = self.ee._Source(URL)
            src._piece = self.ee._HTTP_PIECE
            src._abort_cb = abort
            with self.assertRaises(ValueError):
                self.ee._parse_head(src, self.ee.DEFAULT_HEAD_BYTES, lambda m: None)

    def test_a_head_past_the_limit_stops_at_the_element_that_crosses_it(self):
        # attachments running past 2 MB in front of the first Cluster: a
        # single read would not have used them, so neither are they read
        ee = self.ee
        ebml = b'\x1a\x45\xdf\xa3\x80'
        seg = b'\x18\x53\x80\x67\x01\xff\xff\xff\xff\xff\xff\xff'
        big = b'\x19\x41\xa4\x69\x08' + (3 * 1024 * 1024).to_bytes(4, 'big')   # Attachments, 3 MB
        self.assertTrue(ee._head_enough(ebml + seg + big + b'\x00' * 10, 2 * 1024 * 1024))
        self.assertFalse(ee._head_enough(ebml + seg + big + b'\x00' * 10))

    # ---- many lines in one request -----------------------------------------

    def extract(self, name, many, pad=0):
        local = self.ee.extract_srt(str(FIXTURES / name), lang='en')
        self.sessions[:] = []
        blob, net = self.serve(name, many=many, pad=pad)
        logs = []
        made = []
        real = self.ee._Source

        def source(url):
            made.append(real(url))
            return made[-1]
        with net, patch.object(self.ee, '_Source', source):
            got = self.ee.extract_srt(URL, lang='en', allow_http=True, log=logs.append)
        self.src = made[0] if made else None
        return local, got, logs

    def test_many_lines_come_in_one_request(self):
        # padded: the batch must not lean on the end of the file to cover a read
        local, got, logs = self.extract('attached.mkv', 'multipart', pad=1024 * 1024)
        self.assertEqual(got, local)
        multi = [m for s in self.sessions for m in s.multi]
        self.assertEqual(len(multi), 1)                    # the 36 clusters after the first two: one request
        # in this small file the clusters lie a few hundred bytes apart, so their ranges meet and go as
        # one (a film's clusters are megabytes apart: 241 ranges, 515 KB in QA); none overlaps another
        self.assertTrue(all(b < c for (_a, b), (c, _d) in zip(multi[0], multi[0][1:])))
        self.assertTrue([l for l in logs if 'ranges in one request' in l])
        cluster_reads = [n for s in self.sessions for o, n in s.asked if n == self.ee._BLOCK_READ_HTTP]
        self.assertLessEqual(len(cluster_reads), 3)        # only the clusters that learn the layout
        order = self.sessions[0].order
        after = order[order.index('multi') + 1:]
        self.assertEqual(after, [])                        # every later line came from the one request

    def test_a_node_that_answers_one_range_is_asked_one_range_a_request(self):
        local, got, logs = self.extract('attached.mkv', 'first')
        self.assertEqual(got, local)
        self.assertEqual(len([m for s in self.sessions for m in s.multi]), 1)    # tried once
        self.assertTrue([l for l in logs if 'not served' in l])

    def test_a_cut_answer_is_not_used(self):
        local, got, logs = self.extract('attached.mkv', 'cut')
        self.assertEqual(got, local)
        self.assertEqual(len([m for s in self.sessions for m in s.multi]), 1)
        self.assertTrue([l for l in logs if 'not served' in l])

    def test_a_busy_answer_holds_the_batches_for_a_while(self):
        local, got, logs = self.extract('attached.mkv', 'busy')
        self.assertEqual(got, local)
        # one try, then single ranges -- not a batch before every line
        self.assertEqual(len([m for s in self.sessions for m in s.multi]), 1)
        self.assertTrue([l for l in logs if 'failed (HTTP 429)' in l])
        self.assertGreaterEqual(self.src._429_total, 1)              # counted as pushback, like any other

    def test_a_block_longer_than_the_short_window_is_read_again_in_full(self):
        with patch.object(self.ee, '_BLOCK_READ_MULTI', 16):
            local, got, logs = self.extract('attached.mkv', 'multipart')
        self.assertEqual(got, local)
        self.assertEqual(self.sessions[0].reopened, 0)
        # read again at its own place, not blamed on the file's layout
        self.assertEqual(self.src._prefix_relearn, 0)
        self.assertGreaterEqual(len([1 for o, n in self.sessions[0].asked if n == self.ee._BLOCK_READ_HTTP]), 30)

    def test_a_file_with_no_index_for_the_subtitle_lines_says_so(self):
        # over a stream, a file whose Cues point at video only: the caller is told why (it offers an
        # external subtitle instead); a local file is walked whole as before, and says nothing
        ee = self.ee
        blob, net = self.serve('plain.mkv')
        whole_file = [(1000 + 10 * i, None, None) for i in range(5)]
        for url, expect in ((URL, 'no_index'), (str(FIXTURES / 'plain.mkv'), None)):
            stats = {}
            with net, patch.object(ee, '_read_cues', lambda *a: (whole_file, False)):
                ee.extract_srt(url, lang='en', allow_http=True, stats=stats)
            self.assertEqual(stats.get('why'), expect, url[:20])

    def test_a_connection_error_on_a_batch_holds_the_batches_and_does_not_end_them(self):
        local, got, logs = self.extract('attached.mkv', 'reset')
        self.assertEqual(got, local)
        self.assertIsNot(self.src._multi, False)
        self.assertTrue([l for l in logs if 'failed (ConnectionError)' in l])

    def test_an_index_that_could_not_be_read_is_not_a_file_without_one(self):
        # the connection gives up right after the head (review of 0.3.81): the index exists, it just was
        # not read -- the caller must not be told to give up on the embedded track
        ee = self.ee
        blob, net = self.serve('plain.mkv')
        stats = {}
        calls = []
        with net:
            got = ee.extract_srt(URL, lang='en', allow_http=True, stats=stats,
                                 abort_cb=lambda: calls.append(1) or len(calls) > 1)
        self.assertIsNone(got)
        self.assertIsNone(stats.get('why'))

    def test_each_cluster_is_read_at_its_own_prefix(self):
        # South Park S04 MULTI WEB 2160p (owner's log, 14 Nov 2026): the clusters' size VINT is 3 bytes in
        # most and 4 in some, so one learned prefix is a byte off for those -- 58 relearns and 161 reads
        # past the batch in QA. Here the learned prefix is made wrong before every batch: each cluster's
        # own head, fetched in the batch, must still put every line in place without a relearn.
        ee = self.ee
        real = ee._Source.prefetch

        def stale(src, spans, **kw):
            src._prefix = (src._prefix or 7) + 1
            return real(src, spans, **kw)
        with patch.object(ee._Source, 'prefetch', stale):
            local, got, logs = self.extract('attached.mkv', 'multipart')
        self.assertEqual(got, local)
        self.assertEqual(self.src._prefix_relearn, 0)
        order = self.sessions[0].order
        self.assertEqual(order[order.index('multi') + 1:], [])

    def test_a_block_at_the_start_of_its_cluster_shares_one_range_with_the_head(self):
        ee = self.ee
        self.extract('attached.mkv', 'multipart')
        spans = self.sessions[0].multi[0]
        starts = [a for a, _b in spans]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(all(b < c for (_a, b), (c, _d) in zip(spans, spans[1:])), 'ranges overlap')

    def test_held_prefix_reads_the_cluster_head(self):
        ee = self.ee
        src = types.SimpleNamespace(_pref=ee._PartStore())
        self.assertIsNone(ee._held_prefix(src, 100))
        src._pref[100] = b'\x1f\x43\xb6\x75\x20\x01\x02' + b'\x00' * 9          # ID + a 3-byte size
        self.assertEqual(ee._held_prefix(src, 100), 7)
        self.assertNotIn(100, src._pref)                                         # a head alone: handed out
        src._pref[200] = b'\x1f\x43\xb6\x75\x10\x00\x01\x02' + b'\x00' * 4000   # a 4-byte size, and a block
        self.assertEqual(ee._held_prefix(src, 200), 8)
        self.assertIn(200, src._pref)                                            # it still serves the block
        src._pref[300] = b'\x1a\x45\xdf\xa3\x80' + b'\x00' * 11                    # not a cluster
        self.assertIsNone(ee._held_prefix(src, 300))

    # ---- a picked language whose embedded subtitle is a picture ----------------

    PGS_EN = {'num': 7, 'codec': 'S_HDMV/PGS', 'lang': 'eng', 'forced': False, 'type': 17,
              'lang_explicit': True, 'name': ''}

    def _tracks(self, *extra):
        ee = self.ee
        real = ee._sub_tracks
        return patch.object(ee, '_sub_tracks', lambda tracks: real(tracks) + list(extra))

    PGS_FR = dict(PGS_EN, num=6, lang='fre')
    AI_ORDER = ('en', 'es', 'de', 'fr', 'pt')

    def text(self, num, lang, name=''):
        return {'num': num, 'codec': 'S_TEXT/UTF8', 'lang': lang, 'forced': False, 'type': 17,
                'lang_explicit': True, 'name': name}

    def test_another_text_track_is_read_when_the_picked_one_is_a_picture(self):
        # the owner's file had English as a picture and French as text; here plain.mkv's English text
        # is read for a French pick whose French track is a picture
        ee = self.ee
        local = ee.extract_srt(str(FIXTURES / 'plain.mkv'), lang='en')
        used, stats = [], {}
        blob, net = self.serve('plain.mkv')
        with net, self._tracks(self.PGS_FR):
            got = ee.extract_srt(URL, lang='fr', allow_http=True, stats=stats, other_text=self.AI_ORDER,
                                 on_track=used.append)
            plain = ee.extract_srt(URL, lang='fr', allow_http=True, stats=stats)
        self.assertEqual(got, local)
        self.assertEqual(used, ['en'])
        self.assertIsNone(plain)                                              # not asked for: no other track
        self.assertEqual(stats.get('why'), 'no_text')

    def test_a_language_that_is_not_here_reads_nothing_else(self):
        ee = self.ee
        used, stats = [], {}
        blob, net = self.serve('plain.mkv')
        with net:
            self.assertIsNone(ee.extract_srt(URL, lang='fr', allow_http=True, stats=stats,
                                             other_text=self.AI_ORDER, on_track=used.append))
        self.assertEqual(used, [])
        self.assertIsNone(stats.get('why'))

    def test_the_best_language_for_the_ai_is_chosen(self):
        ee = self.ee
        tracks = [self.PGS_FR, self.text(21, 'ger'), self.text(22, 'spa', 'Signs & Songs'),
                  self.text(23, 'por'), self.text(24, 'heb')]
        used, logs = [], []
        blob, net = self.serve('plain.mkv')
        with net, patch.object(ee, '_sub_tracks', lambda t: list(tracks)):
            ee.extract_srt(URL, lang='fr', allow_http=True, other_text=self.AI_ORDER, on_track=used.append,
                           log=logs.append)
        self.assertEqual(used, ['de'])                                        # Spanish is signs only: last
        self.assertTrue(any('reading the ger text track #21 instead' in m for m in logs), logs)

    def test_an_untagged_track_ranks_after_the_tagged_ones(self):
        ee = self.ee
        untagged = dict(self.text(21, 'eng'), lang_explicit=False)
        used = []
        blob, net = self.serve('plain.mkv')
        with net, patch.object(ee, '_sub_tracks', lambda t: [self.PGS_FR, untagged, self.text(22, 'spa')]):
            ee.extract_srt(URL, lang='fr', allow_http=True, other_text=self.AI_ORDER, on_track=used.append)
        self.assertEqual(used, ['es'])

    def test_no_switch_is_reported_for_the_picked_language_s_own_track(self):
        # review of 0.3.82: _pick_track hands back a file's one untagged text track (it defaults to 'eng')
        # for a Spanish pick -- that is the Spanish pick's own track, not a switch from a picture
        ee = self.ee
        local = ee.extract_srt(str(FIXTURES / 'plain.mkv'), lang='en')
        used = []
        blob, net = self.serve('plain.mkv')
        real = ee._sub_tracks
        with net, patch.object(ee, '_sub_tracks',
                               lambda t: [dict(x, lang_explicit=False) for x in real(t)]):
            got = ee.extract_srt(URL, lang='es', allow_http=True, other_text=self.AI_ORDER, on_track=used.append)
        self.assertEqual(got, local)
        self.assertEqual(used, [])

    def test_hebrew_and_forced_tracks_are_never_the_other_track(self):
        ee = self.ee
        forced_fr = dict(self.text(25, 'fre'), forced=True)
        used, stats = [], {}
        blob, net = self.serve('plain.mkv')
        with net, patch.object(ee, '_sub_tracks', lambda t: [self.PGS_EN, self.text(24, 'heb'), forced_fr]):
            self.assertIsNone(ee.extract_srt(URL, lang='en', allow_http=True, stats=stats,
                                             other_text=self.AI_ORDER, on_track=used.append))
        self.assertEqual(used, [])
        self.assertEqual(stats.get('why'), 'no_text')

    def test_signs_tracks_are_known_by_name(self):
        ee = self.ee
        self.assertTrue(ee._track_is_signs({'name': 'English [Signs/Songs]'}))
        self.assertTrue(ee._track_is_signs({'name': 'Forced'}))
        self.assertFalse(ee._track_is_signs({'name': 'English SDH'}))
        self.assertFalse(ee._track_is_signs({'name': None}))

    def test_a_picture_track_in_the_picked_language_says_so(self):
        ee = self.ee
        blob, net = self.serve('plain.mkv')
        fr_text = {'num': 8, 'codec': 'S_TEXT/UTF8', 'lang': 'fre', 'forced': False, 'type': 17,
                   'lang_explicit': True, 'name': ''}
        stats = {}
        with net, patch.object(ee, '_sub_tracks', lambda tracks: [self.PGS_EN, fr_text]):
            self.assertIsNone(ee.extract_srt(URL, lang='en', allow_http=True, stats=stats))
        self.assertEqual(stats.get('why'), 'no_text')

    def test_a_forced_text_track_beside_the_picture_does_not_hide_it(self):
        ee = self.ee
        blob, net = self.serve('plain.mkv')
        forced = {'num': 9, 'codec': 'S_TEXT/UTF8', 'lang': 'eng', 'forced': True, 'type': 17,
                  'lang_explicit': True, 'name': 'Forced'}
        stats = {}
        with net, patch.object(ee, '_sub_tracks', lambda tracks: [self.PGS_EN, forced]):
            self.assertIsNone(ee.extract_srt(URL, lang='en', allow_http=True, stats=stats))
        self.assertEqual(stats.get('why'), 'no_text')

    def test_a_text_track_of_the_picked_language_is_read_even_beside_its_picture(self):
        ee = self.ee
        local = ee.extract_srt(str(FIXTURES / 'plain.mkv'), lang='en')
        blob, net = self.serve('plain.mkv')
        stats = {}
        with net, self._tracks(self.PGS_EN):
            got = ee.extract_srt(URL, lang='en', allow_http=True, stats=stats)
        self.assertEqual(got, local)
        self.assertIsNone(stats.get('why'))

    # ---- the store of batched parts ----------------------------------------------

    def test_the_store_finds_the_part_that_holds_a_span(self):
        ee = self.ee
        store = ee._PartStore()
        self.assertIsNone(store.covering(10, 20))
        store[100] = b'a' * 50
        store[300] = b'b' * 10
        store[120] = b'c' * 5                     # overlaps the first (asked for around a held one)
        self.assertEqual(store.covering(110, 150), (100, b'a' * 50))
        self.assertEqual(store.covering(121, 124), (120, b'c' * 5))
        self.assertEqual(store.covering(126, 140), (100, b'a' * 50))   # the nearest start does not hold it
        self.assertIsNone(store.covering(140, 151))
        self.assertIsNone(store.covering(250, 260))
        self.assertEqual(store.covering(300, 310)[0], 300)
        del store[100]
        self.assertIsNone(store.covering(110, 115))
        store.drop_before(200)
        self.assertEqual(sorted(store), [300])

    def test_a_full_store_keeps_what_lies_ahead(self):
        ee = self.ee
        blob, net = self.serve('attached.mkv', pad=1024 * 1024)
        with net, patch.object(ee, '_MULTI_STORE_MAX', 150):
            src = ee._Source(URL)
            src._pace = 0
            self.assertEqual(src.prefetch([(1000, 100), (5000, 100)]), 2)
            # over 150 bytes held: what lies behind the reading goes, what lies ahead stays
            self.assertEqual(src.prefetch([(9000, 100), (12000, 100)], keep_from=4000), 2)
            self.assertEqual(sorted(src._pref), [5000, 9000, 12000])
            self.assertEqual(src.read(5000, 100), blob[5000:5100])
            src.prefetch([(20000, 100), (30000, 100)])           # no position given: the store starts again
            self.assertEqual(sorted(src._pref), [20000, 30000])

    def test_holds_means_all_of_the_span(self):
        ee = self.ee
        src = types.SimpleNamespace(_pref=ee._PartStore(), total=0)
        src._pref[1000] = b'x' * 100
        self.assertTrue(ee._Source.holds(src, 1000))
        self.assertTrue(ee._Source.holds(src, 1050, 50))
        self.assertFalse(ee._Source.holds(src, 1050, 51))   # a window that spills past what is held
        src.total = 1100
        self.assertTrue(ee._Source.holds(src, 1050, 4096))  # cut at the end of the file: whole

    def test_no_request_carries_more_ranges_than_the_cap(self):
        ee = self.ee
        # short block windows, so the fixture's close clusters do not join into one range
        with patch.object(ee, '_MULTI_RANGES', 4), patch.object(ee, '_BLOCK_READ_MULTI', 200):
            local, got, logs = self.extract('attached.mkv', 'multipart')
        self.assertEqual(got, local)
        multi = self.sessions[0].multi
        self.assertGreater(len(multi), 1)
        self.assertTrue(all(len(spans) <= 4 for spans in multi), [len(x) for x in multi])

    def test_kodi_is_not_asked_between_every_cluster(self):
        # QA, 14 Nov 2026, Interstellar 2160p DV: 2,666 lines in 97 s from 40 requests -- the abort and
        # progress callbacks ask Kodi things, ~35 ms a cluster with a 4K film on screen. Between clusters
        # they are asked at most every _CALLBACK_POLL_S; before every request still.
        ee = self.ee
        calls = {'abort': 0, 'tick': 0}
        blob, net = self.serve('attached.mkv', many='multipart')
        with net, patch.object(ee, '_CALLBACK_POLL_S', 60.0):
            got = ee.extract_srt(URL, lang='en', allow_http=True,
                                 abort_cb=lambda: calls.__setitem__('abort', calls['abort'] + 1) or False,
                                 progress_cb=lambda d, t: calls.__setitem__('tick', calls['tick'] + 1))
        self.assertTrue(got)
        reqs = sum(1 for s in self.sessions for a in s.asked if a[1] > 1) + sum(len(s.multi) for s in self.sessions)
        self.assertLessEqual(calls['abort'], reqs + 2)            # the requests' own, plus the first between clusters
        self.assertLessEqual(calls['tick'], 4)                     # the first, a pass's last, the end (36 clusters)

    def test_an_mp4_says_so(self):
        # QA, 14 Nov 2026: The Dark Knight 2160p DV WEB-DL is an MP4 -- the pick ended in "could not extract";
        # the caller now offers the external subtitle instead
        ee = self.ee
        blob = b'\x00\x00\x00\x20ftypisom' + bytes(2 * 1024 * 1024)
        stats, logs = {}, []
        with patch.object(ee, '_new_session', lambda: Session(blob, None, 'multipart')):
            self.assertIsNone(ee.extract_srt(URL, lang='en', allow_http=True, stats=stats, log=logs.append))
        self.assertEqual(stats.get('why'), 'not_mkv')
        self.assertTrue(any('(MP4)' in m for m in logs), logs)

    def test_an_error_page_is_not_called_another_container(self):
        ee = self.ee
        stats = {}
        page = b'<html><body>link expired</body></html>' + b' ' * 4096
        with patch.object(ee, '_new_session', lambda: Session(page, None, 'multipart')):
            self.assertIsNone(ee.extract_srt(URL, lang='en', allow_http=True, stats=stats))
        self.assertIsNone(stats.get('why'))
        self.assertEqual(ee._container_name(b'G' + bytes(187) + b'G' + bytes(10)), 'MPEG-TS')
        self.assertIsNone(ee._container_name(b'G' + bytes(300)))

    def test_an_empty_answer_is_not_called_another_container(self):
        ee = self.ee
        stats = {}
        with patch.object(ee, '_new_session', lambda: Session(b'', None, 'multipart')):
            self.assertIsNone(ee.extract_srt(URL, lang='en', allow_http=True, stats=stats))
        self.assertIsNone(stats.get('why'))

    def test_join_spans(self):
        ee = self.ee
        self.assertEqual(ee._join_spans([(50, 10), (0, 10), (10, 5), (60, 1), (100, 4), (2, 3)]),
                         [(0, 15), (50, 11), (100, 4)])
        self.assertEqual(ee._join_spans([]), [])

    def test_byteranges_are_split_only_when_sound(self):
        ee = self.ee
        blob = bytes(range(256)) * 40
        ok = Multipart(blob, [(10, 19), (100, 109)]).raw.getvalue()
        ctype = 'multipart/byteranges; boundary=XyZ'
        self.assertEqual(ee._parse_byteranges(ok, ctype), [(10, blob[10:20]), (100, blob[100:110])])
        self.assertEqual(ee._parse_byteranges(ok, 'multipart/byteranges'), [])            # no boundary
        self.assertEqual(ee._parse_byteranges(ok.replace(b'Content-Range', b'X-Range'), ctype), [])
        short = Multipart(blob, [(10, 19), (100, 1099)], cut=True).raw.getvalue()
        self.assertEqual(ee._parse_byteranges(short, ctype), [])
        self.assertEqual(ee._parse_byteranges(ok, 'multipart/byteranges; boundary="XyZ"'),
                         [(10, blob[10:20]), (100, blob[100:110])])

    def test_subsync_reads_are_unchanged(self):
        # SubSync's own timing read (cue_reference_times) keeps its one-request
        # head: its first-play timing was measured with it
        blob, net = self.serve('plain.mkv')
        with net:
            self.ee.cue_reference_times(URL, lang='en', allow_http=True)
        self.assertEqual(self.requests()[0], (0, self.ee.DEFAULT_HEAD_BYTES))


if __name__ == '__main__':
    unittest.main()
