"""High-volume patch diagnostics must not block Wizard startup on file I/O."""

import ast
import os
import tempfile
import time
import types
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1]
          / 'plugin.program.kodipovilwizard/resources/libs/common/logging.py')


class WizardLoggingTests(unittest.TestCase):
    def test_patch_messages_only_use_native_log(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        log_node = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == 'log')
        native = []
        file_writes = []
        xbmc = types.SimpleNamespace(
            LOGINFO=1, LOGWARNING=2, log=lambda message, level: native.append((message, level)))
        tools = types.SimpleNamespace(
            get_date=lambda **kwargs: '2026-09-28 00:00:00',
            write_to_file=lambda *args, **kwargs: file_writes.append((args, kwargs)))
        with tempfile.TemporaryDirectory() as raw:
            config = types.SimpleNamespace(ADDONTITLE='Wizard', DEBUGLEVEL='1',
                                           ENABLEWIZLOG='true', CLEANWIZLOG='false',
                                           WIZLOG=os.path.join(raw, 'wizard.log'))
            scope = {'xbmc': xbmc, 'CONFIG': config, 'tools': tools,
                     'os': os, 'time': time}
            exec(compile(ast.Module(body=[log_node], type_ignores=[]),
                         str(SOURCE), 'exec'), scope)
            scope['log']('[PatchEngine] Saved patched plugin.video.pov/sources.py')
            self.assertEqual(len(native), 1)
            self.assertEqual(file_writes, [])
            scope['log']('[quick_update] Complete')
            self.assertEqual(len(native), 2)
            self.assertEqual(len(file_writes), 1)


if __name__ == '__main__':
    unittest.main()
