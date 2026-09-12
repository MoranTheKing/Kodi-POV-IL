"""Execute production range validation and recovery with deterministic HTTP doubles."""
import io
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      'addons/service.subtitles.kodipovilai/resources/lib'))
import mkv_probe as mp

DATA = bytes(range(100))


class Reply:
    def __init__(self, start, end, total=100, status=206, body=None):
        self.status = status
        self.headers = {'Content-Range': 'bytes %d-%d/%d' % (start, end, total),
                        'Content-Length': str(end - start + 1)}
        self.body = io.BytesIO(DATA[start:end + 1] if body is None else body)
        self.closed = False
        self.read_count = 0
        self.timeouts = []
        self.fp = types.SimpleNamespace(raw=types.SimpleNamespace(
            _sock=types.SimpleNamespace(settimeout=self.timeouts.append)))

    def read1(self, amount):
        self.read_count += 1
        return self.body.read(amount)

    def close(self):
        self.closed = True


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.replies = []
        self.factory = lambda start, end: Reply(start, min(end, len(DATA) - 1))
        self.chunk_patch = patch.object(mp, '_HTTP_RANGE_BYTES', 8)
        self.chunk_patch.start()
        self.open_patch = patch('urllib.request.urlopen', self.open)
        self.open_patch.start()
        self.addCleanup(self.open_patch.stop)
        self.addCleanup(self.chunk_patch.stop)

    def open(self, request, timeout):
        start, end = map(int, re.fullmatch(r'bytes=(\d+)-(\d+)', request.get_header('Range')).groups())
        self.calls.append((start, end))
        reply = self.factory(start, end)
        self.replies.append(reply)
        return reply

    def source(self, **kw):
        return mp._Source('https://fixture.invalid/media', **kw)

    def test_large_read_is_joined_in_order(self):
        src = self.source()
        self.assertEqual(src.read(3, 20), DATA[3:23])
        self.assertEqual(self.calls, [(3, 10), (11, 18), (19, 22)])
        self.assertEqual(src.fetched, 20)
        self.assertTrue(all(r.closed for r in self.replies))

    def test_server_short_ranges_are_completed(self):
        self.factory = lambda start, end: Reply(start, min(start + 2, end))
        self.assertEqual(self.source().read(0, 8), DATA[:8])
        self.assertEqual(self.calls, [(0, 7), (3, 7), (6, 7)])

    def test_byte_budget_covers_every_request(self):
        src = self.source(max_bytes=10)
        self.assertEqual(src.read(0, 100), DATA[:10])
        self.assertEqual(src.fetched, 10)
        self.assertEqual(src.read(10, 30), b'')
        self.assertEqual(self.calls, [(0, 7), (8, 9)])

    def test_known_eof_does_not_request_past_end(self):
        src = self.source()
        self.assertEqual(src.read(97, 9), DATA[97:])
        self.assertEqual(src.read(100, 1), b'')
        self.assertEqual(len(self.calls), 1)

    def test_negative_offset_refused(self):
        with self.assertRaises(ValueError):
            self.source().read(-1, 3)
        self.assertEqual(self.calls, [])

    def test_zero_budget_never_opens(self):
        self.assertEqual(self.source(max_bytes=0).read(0, 4), b'')
        self.assertEqual(self.calls, [])

    def test_wrong_start_is_rejected_before_reading(self):
        self.factory = lambda start, end: Reply(0, end - start)
        with self.assertRaises(ValueError):
            self.source().read(8, 4)
        self.assertEqual(self.replies[0].read_count, 0)
        self.assertTrue(self.replies[0].closed)

    def test_invalid_headers_are_rejected(self):
        for field, value in [('Content-Range', ''), ('Content-Range', 'bytes 0-7/*'),
                             ('Content-Range', 'bytes 0-8/100'),
                             ('Content-Range', 'bytes 0-7/7'),
                             ('Content-Length', '6'), ('Content-Encoding', 'gzip')]:
            def factory(start, end):
                r = Reply(start, end)
                r.headers[field] = value
                return r
            self.factory = factory
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.source().read(0, 8)
            self.assertTrue(self.replies[-1].closed)

    def test_changed_total_is_rejected(self):
        self.factory = lambda start, end: Reply(start, end, total=100 if start == 0 else 101)
        with self.assertRaises(ValueError):
            self.source().read(0, 16)

    def test_ignored_nonzero_range_is_rejected(self):
        self.factory = lambda start, end: Reply(0, 7, status=200)
        with self.assertRaises(ValueError):
            self.source().read(10, 8)
        self.assertEqual(self.replies[0].read_count, 0)

    def test_200_head_can_be_read_but_not_relabelled(self):
        self.factory = lambda start, end: Reply(0, 99, status=200)
        src = self.source()
        self.assertEqual(src.read(0, 4), DATA[:4])
        with self.assertRaises(ValueError):
            src.read(4, 4)

    def test_truncated_body_is_rejected(self):
        self.factory = lambda start, end: Reply(start, end, body=b'12')
        src = self.source()
        with self.assertRaises(ValueError):
            src.read(0, 8)
        self.assertEqual(src.fetched, 2)
        self.assertEqual(len(self.calls), 1)

    def test_partial_timeout_resumes_exact_suffix(self):
        def factory(start, end):
            reply = Reply(start, end)
            original = reply.read1
            if start == 0:
                def interrupted(amount):
                    if reply.read_count:
                        raise TimeoutError('fixture interruption')
                    return original(3)
                reply.read1 = interrupted
            return reply
        self.factory = factory
        src = self.source(max_bytes=8)
        self.assertEqual(src.read(0, 8), DATA[:8])
        self.assertEqual(self.calls, [(0, 7), (3, 7)])
        self.assertEqual(src.fetched, 8)

    def test_partial_reset_also_resumes(self):
        def factory(start, end):
            reply = Reply(start, end)
            original = reply.read1
            if start == 0:
                def interrupted(amount):
                    if reply.read_count:
                        raise ConnectionResetError('fixture reset')
                    return original(2)
                reply.read1 = interrupted
            return reply
        self.factory = factory
        self.assertEqual(self.source().read(0, 8), DATA[:8])
        self.assertEqual(self.calls, [(0, 7), (2, 7)])

    def test_stalled_tail_leaves_time_for_suffix_request(self):
        clock = [0]
        def factory(start, end):
            reply = Reply(start, end)
            original = reply.read1
            if start == 0:
                def interrupted(amount):
                    if reply.read_count:
                        clock[0] += reply.timeouts[-1]
                        raise TimeoutError('tail stopped delivering bytes')
                    return original(3)
                reply.read1 = interrupted
            return reply
        self.factory = factory
        with patch.object(mp.time, 'monotonic', lambda: clock[0]):
            src = self.source(deadline_s=10)
            self.assertEqual(src.read(0, 8), DATA[:8])
        self.assertEqual(self.calls, [(0, 7), (3, 7)])
        self.assertEqual(self.replies[0].timeouts, [10, 3])
        self.assertEqual(src.fetched, 8)

    def test_timeout_without_progress_is_not_retried(self):
        def factory(start, end):
            reply = Reply(start, end)
            reply.read1 = lambda _: (_ for _ in ()).throw(TimeoutError('fixture'))
            return reply
        self.factory = factory
        with self.assertRaises(TimeoutError):
            self.source().read(0, 8)
        self.assertEqual(len(self.calls), 1)

    def test_deadline_includes_body_and_stops_retry(self):
        clock = [0]
        def factory(start, end):
            reply = Reply(start, end)
            original = reply.read1
            def slow(amount):
                clock[0] += 2
                return original(1)
            reply.read1 = slow
            return reply
        self.factory = factory
        with patch.object(mp.time, 'monotonic', lambda: clock[0]):
            src = self.source(deadline_s=5)
            with self.assertRaises(TimeoutError):
                src.read(0, 8)
        self.assertEqual(src.fetched, 3)
        self.assertEqual(self.replies[0].timeouts, [5, 3, 1])
        self.assertEqual(len(self.calls), 1)

    def test_deadline_before_request(self):
        with self.assertRaises(TimeoutError):
            self.source(deadline_s=0).read(0, 4)
        self.assertEqual(self.calls, [])

    def test_416_only_means_eof_when_offset_is_outside_file(self):
        def factory(start, end):
            raise urllib.error.HTTPError('fixture', 416, 'range',
                                          {'Content-Range': 'bytes */100'}, io.BytesIO())
        self.factory = factory
        src = self.source()
        self.assertEqual(src.read(100, 8), b'')
        self.assertEqual(src.total, 100)
        with self.assertRaises(urllib.error.HTTPError):
            self.source().read(0, 8)


if __name__ == '__main__':
    unittest.main(verbosity=2)
