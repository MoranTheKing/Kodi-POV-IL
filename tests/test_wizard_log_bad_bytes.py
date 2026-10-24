"""Wizard 0.4.81: a kodi.log with a byte that is not UTF-8 no longer breaks
the main menu, View Log and Upload Log.

Field report (24 Oct 2026, LG webOS TV, Wizard 0.4.80): after Kodi's debug
logging was switched on, the main menu, View Log and Upload Log failed with
"UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc6", so no log could be
sent. Every Kodi log read now replaces such a byte instead of failing.
"""
import ast
import importlib.util
import os
import re
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
LOGGING = ROOT / 'resources/libs/common/logging.py'
TOOLS = ROOT / 'resources/libs/common/tools.py'

BAD = (b'2026-10-24 10:00:00.000 T:1 info <general>: caf\xc6 menu\n'
       b'-->Python callback/script returned the following error<--\n'
       b'Error Type: <class \'KeyError\'>\n'
       b'-->End of Python script error report<--\n')


def _read_from_file():
    tree = ast.parse(TOOLS.read_text('utf8'))
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == 'read_from_file')
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(TOOLS), 'exec'), scope)
    return scope['read_from_file']


class BadBytesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.log = os.path.join(self.folder.name, 'kodi.log')
        with open(self.log, 'wb') as f:
            f.write(BAD)
        config = types.SimpleNamespace(
            ADDONTITLE='Wizard', ADDON_ICON='icon.jpg', COLOR1='blue', COLOR2='yellow',
            LOGPATH=self.folder.name, WIZLOG=os.path.join(self.folder.name, 'wizard.log'),
            HOME=self.folder.name)
        self.file_bytes = BAD
        vfs = types.SimpleNamespace(File=lambda path: types.SimpleNamespace(
            readBytes=lambda: bytearray(self.file_bytes),
            read=lambda: self.file_bytes.decode('utf-8'),   # strict, as Kodi's
            close=lambda: None))
        self.scope = dict(os=os, re=re, time=time, CONFIG=config,
                          xbmc=types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=3),
                          xbmcgui=types.SimpleNamespace(Dialog=Mock),
                          xbmcvfs=vfs,
                          tools=types.SimpleNamespace(read_from_file=_read_from_file()))
        tree = ast.parse(LOGGING.read_text('utf8'))
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign))]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(LOGGING), 'exec'), self.scope)
        self.scope['log'] = Mock()
        self.scope['log_notify'] = Mock()

    def test_main_menu_error_count(self):
        self.assertEqual(1, self.scope['error_checking'](count=True))

    def test_view_log_text(self):
        text = self.scope['grab_log']()
        self.assertIn('caf� menu', text)

    def test_upload_reads_the_log(self):
        ok, content = self.scope['read_log'](self.log)
        self.assertTrue(ok)
        self.assertIn('caf� menu', content)

    def test_the_log_viewer_window_reads_leniently(self):
        src = (ROOT / 'resources/libs/gui/window.py').read_text('utf8')
        self.assertIn("tools.read_from_file(self.log_file, errors='replace')", src)


if __name__ == '__main__':
    unittest.main()
