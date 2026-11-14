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

    def extract(self, name, many):
        local = self.ee.extract_srt(str(FIXTURES / name), lang='en')
        self.sessions[:] = []
        blob, net = self.serve(name, many=many)
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
        local, got, logs = self.extract('attached.mkv', 'multipart')
        self.assertEqual(got, local)
        multi = [m for s in self.sessions for m in s.multi]
        self.assertEqual(len(multi), 1)                    # the 36 clusters after the first two: one request
        self.assertGreaterEqual(len(multi[0]), 30)
        # each line in a short window, not the 32 KB one
        self.assertTrue(all(b - a + 1 <= self.ee._BLOCK_READ_MULTI + 4096 for a, b in multi[0]))
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
