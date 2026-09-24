"""Opaque debrid URLs must route MP4 movie indexes by bytes, not filename."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'addons/service.subtitles.kodipovilai'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resources.lib import embedded_extract
from tools.test_mp4_probe import make_mp4


class OpaqueRemoteMP4Tests(unittest.TestCase):
    def test_actual_http_ranges_recover_opaque_mp4_timing(self):
        media = make_mp4(index_at_end=True, sample_count=240)
        requests = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args):
                pass

            def do_GET(self):
                match = re.fullmatch(r'bytes=(\d+)-(\d+)',
                                     self.headers.get('Range') or '')
                if not match:
                    self.send_error(400)
                    return
                start, end = map(int, match.groups())
                requests.append((start, end))
                if start >= len(media):
                    self.send_response(416)
                    self.send_header('Content-Range', 'bytes */%d' % len(media))
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                end = min(end, len(media) - 1)
                body = media[start:end + 1]
                self.send_response(206)
                self.send_header('Content-Range',
                                 'bytes %d-%d/%d' % (start, end, len(media)))
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = 'http://127.0.0.1:%d/opaque-id' % server.server_address[1]
        result = embedded_extract.cue_reference_profile(url, allow_http=True)
        self.assertEqual(len(result['starts']), 120)
        self.assertEqual(len(result['track_starts']), 1)
        self.assertTrue(result['cut_signature'].startswith('cut1:'))
        self.assertGreaterEqual(len(requests), 2)
        self.assertLess(result['bytes'], 2 * 1024 * 1024)

    def test_index_and_cut_identity_from_opaque_stream_url(self):
        media = make_mp4(index_at_end=True, sample_count=240)
        instances = []

        class Source:
            is_http = True
            total = len(media)
            tripped = False

            def __init__(self, _url):
                self.fetched = 0
                self.reqs = 0
                self._abort_cb = None
                self._log = None
                self.reads = []
                instances.append(self)

            def read(self, offset, size):
                self.reqs += 1
                self.reads.append((offset, size))
                data = media[offset:offset + size]
                self.fetched += len(data)
                return data

            def close(self):
                pass

        with patch.object(embedded_extract, '_Source', Source):
            result = embedded_extract.cue_reference_profile(
                'https://media.invalid/opaque-token', allow_http=True)
        self.assertEqual(len(result['starts']), 120)
        self.assertEqual(len(result['track_starts']), 1)
        self.assertTrue(result['cut_signature'].startswith('cut1:'))
        self.assertTrue(all(size <= embedded_extract.DEFAULT_HEAD_BYTES
                            for _offset, size in instances[0].reads))

    def test_no_timed_text_keeps_unknown_with_cut_identity(self):
        media = make_mp4(fragmented=True)

        class Source:
            is_http = True
            total = len(media)
            tripped = False

            def __init__(self, _url):
                self.fetched = 0
                self.reqs = 0
                self._abort_cb = None
                self._log = None

            def read(self, offset, size):
                self.reqs += 1
                data = media[offset:offset + size]
                self.fetched += len(data)
                return data

            def close(self):
                pass

        with patch.object(embedded_extract, '_Source', Source):
            result = embedded_extract.cue_reference_profile(
                'https://media.invalid/no-extension', allow_http=True)
        self.assertEqual(result['starts'], [])
        self.assertTrue(result['cut_signature'].startswith('cut1:'))


if __name__ == '__main__':
    unittest.main()
