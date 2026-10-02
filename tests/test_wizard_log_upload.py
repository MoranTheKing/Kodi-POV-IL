"""Exercise upload/result/error paths with synthetic logs and offline transports."""
import ast
import importlib.util
import os
import re
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
SOURCE = ROOT / 'resources/libs/common/logging.py'


class LogUploadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dialog = Mock()
        self.window = types.ModuleType('resources.libs.gui.window')
        self.window.show_qr_code = Mock()
        self.gui = types.ModuleType('resources.libs.gui')
        self.gui.window = self.window
        self.vfs = types.SimpleNamespace(File=Mock())
        self.config = types.SimpleNamespace(
            ADDONTITLE='Wizard', ADDON_ICON='icon.jpg', COLOR1='blue', COLOR2='yellow',
            PLUGIN_DATA=self.folder.name, LOGPATH=self.folder.name,
            WIZLOG=os.path.join(self.folder.name, 'wizard.log'),
            KEEPOLDLOG=False, KEEPWIZLOG=False, KEEPCRASHLOG=False,
            ADDON_ID='plugin.program.kodipovilwizard', ADDON_VERSION='0.4.11')
        self.scope = dict(os=os, re=re, time=time, CONFIG=self.config,
                          xbmc=types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=3),
                          xbmcgui=types.SimpleNamespace(Dialog=lambda: self.dialog),
                          xbmcvfs=self.vfs, tools=types.SimpleNamespace())
        tree = ast.parse(SOURCE.read_text('utf8'))
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign))]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), self.scope)
        self.scope['log'] = Mock()
        # Load the exact vendored runtime rather than an installed QR library.
        spec = importlib.util.spec_from_file_location(
            'segno', ROOT / 'segno/__init__.py',
            submodule_search_locations=[str(ROOT / 'segno')])
        segno = importlib.util.module_from_spec(spec)
        self.modules = patch.dict(sys.modules, {'segno': segno,
            'resources.libs.gui': self.gui, 'resources.libs.gui.window': self.window})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec.loader.exec_module(segno)
        self.segno = segno

    def prepare_upload(self, read=(True, 'synthetic log'), post=(True, 'https://paste.kodi.tv/fixture')):
        self.scope['get_files'] = Mock(return_value=[['log', '/synthetic/kodi.log']])
        self.scope['read_log'] = Mock(return_value=read)
        self.scope['post_log'] = Mock(return_value=post)

    def test_successful_upload_displays_real_png_and_link_then_removes_temp_file(self):
        self.prepare_upload()
        captured = []
        def inspect(layout, filename, message):
            self.assertEqual(layout, 'loguploader.xml')
            self.assertTrue(Path(filename).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertIn('https://paste.kodi.tv/fixture', message)
            captured.append(filename)
        self.window.show_qr_code.side_effect = inspect
        self.scope['upload_log']()
        self.scope['post_log'].assert_called_once_with('synthetic log', 'kodi.log')
        self.assertEqual(len(captured), 1)
        self.assertFalse(Path(captured[0]).exists())
        self.dialog.ok.assert_not_called()

    def test_qr_generation_failure_keeps_uploaded_link_in_native_dialog(self):
        self.prepare_upload()
        with patch.object(self.segno, 'make_qr', side_effect=RuntimeError('QR unavailable')):
            self.scope['upload_log']()
        self.assertIn('https://paste.kodi.tv/fixture', self.dialog.ok.call_args.args[1])
        self.assertEqual(list(Path(self.folder.name).rglob('*.png')), [])

    def test_qr_window_failure_keeps_link_and_removes_image(self):
        self.prepare_upload()
        self.window.show_qr_code.side_effect = RuntimeError('window unavailable')
        self.scope['upload_log']()
        self.assertIn('https://paste.kodi.tv/fixture', self.dialog.ok.call_args.args[1])
        self.assertEqual(list(Path(self.folder.name).rglob('*.png')), [])

    def test_upload_failure_shows_server_error_without_qr(self):
        self.prepare_upload(post=(False, 'offline'))
        self.scope['upload_log']()
        self.assertIn('offline', self.dialog.ok.call_args.args[1])
        self.window.show_qr_code.assert_not_called()

    def test_unreadable_and_empty_log_do_not_use_an_unassigned_result(self):
        for error in ('Unable to Read File', 'File is Empty'):
            self.dialog.reset_mock()
            self.prepare_upload(read=(False, error))
            self.scope['upload_log']()
            self.scope['post_log'].assert_not_called()
            self.assertIn(error, self.dialog.ok.call_args.args[1])

    def test_missing_log_directory_reports_no_file_without_upload(self):
        self.config.LOGPATH = os.path.join(self.folder.name, 'not-created')
        self.scope['post_log'] = Mock()
        self.scope['upload_log']()
        self.scope['post_log'].assert_not_called()
        self.dialog.ok.assert_called_once_with('Wizard', 'No log file found')

    def test_all_existing_credential_filters_are_applied(self):
        value = 'https://alice:secret@example.invalid/ <user>alice</user> <pass>secret</pass>'
        clean = self.scope['clean_log'](value)
        self.assertNotIn('alice', clean)
        self.assertNotIn('secret', clean)
        self.assertIn('<user>USER</user>', clean)
        self.assertIn('<pass>PASSWORD</pass>', clean)

    def test_vfs_handle_closes_on_success_empty_and_read_exception(self):
        for value in ('synthetic log', '', OSError('unreadable')):
            handle = Mock()
            if isinstance(value, Exception):
                handle.read.side_effect = value
            else:
                handle.read.return_value = value
            self.vfs.File.return_value = handle
            success, data = self.scope['read_log']('/synthetic/kodi.log')
            self.assertEqual(success, value == 'synthetic log')
            handle.close.assert_called_once()

    def test_official_paste_success_does_not_send_to_fallback_services(self):
        transport = types.ModuleType('requests')
        transport.post = Mock(return_value=types.SimpleNamespace(status_code=200,
            json=lambda: {'key': 'fixture'}))
        with patch.dict(sys.modules, {'requests': transport}):
            self.assertEqual(self.scope['post_log']('synthetic log', 'kodi.log'),
                             (True, 'https://paste.kodi.tv/fixture'))
        self.assertEqual(transport.post.call_count, 1)

    def test_fallback_and_all_services_unavailable_are_handled(self):
        transport = types.ModuleType('requests')
        transport.post = Mock(side_effect=[TimeoutError('offline'),
            types.SimpleNamespace(status_code=200, text='https://0x0.st/fixture')])
        with patch.dict(sys.modules, {'requests': transport}):
            self.assertEqual(self.scope['post_log']('synthetic log', 'kodi.log'),
                             (True, 'https://0x0.st/fixture'))
        transport.post = Mock(side_effect=TimeoutError('offline'))
        with patch.dict(sys.modules, {'requests': transport}):
            success, message = self.scope['post_log']('synthetic log', 'kodi.log')
        self.assertFalse(success)
        self.assertIn('all paste services failed', message)
        self.assertEqual(transport.post.call_count, 3)


if __name__ == '__main__':
    unittest.main()
