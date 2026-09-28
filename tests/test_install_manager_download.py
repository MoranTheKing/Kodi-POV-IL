"""Installer ZIP transfer must finish a short final HTTP chunk."""

import ast
import hashlib
import http.server
import os
import tempfile
import threading
import types
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1]
          / 'plugin.program.kodipovilwizard/resources/libs/gui/install_manager.py')


class DownloadTests(unittest.TestCase):
    def test_large_local_zip_with_short_final_chunk(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / 'fixture.zip'
            payload = bytes(range(256)) * 8192 + b'last 37 bytes are not a full chunk!----'
            source.write_bytes(payload)

            class Handler(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, directory=raw, **kwargs)

                def log_message(self, *_args):
                    pass

            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
            function = next(node for node in tree.body
                            if isinstance(node, ast.FunctionDef) and node.name == '_download')
            messages = []
            scope = {
                'os': os,
                'CONFIG': types.SimpleNamespace(USER_AGENT='Kodi POV IL transfer test'),
                'tools': types.SimpleNamespace(open_url=lambda *_a, **_kw: self.fail(
                    'direct local transfer unexpectedly fell back')),
                'logging': types.SimpleNamespace(log=lambda *args, **kw: messages.append((args, kw))),
                'xbmc': types.SimpleNamespace(LOGERROR=4, LOGWARNING=2),
            }
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE),
                         'exec'), scope)
            output = Path(raw) / 'received.zip'
            progress = []
            self.assertTrue(scope['_download'](
                'http://127.0.0.1:{}/fixture.zip'.format(server.server_port),
                str(output), progress.append, lambda: False))
            self.assertEqual(hashlib.sha256(output.read_bytes()).digest(),
                             hashlib.sha256(payload).digest())
            self.assertEqual(progress[-1], 100)
            self.assertFalse(messages)


if __name__ == '__main__':
    unittest.main()
