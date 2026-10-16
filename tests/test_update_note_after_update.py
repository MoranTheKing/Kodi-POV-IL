"""An update note pops up only after this device has the update it describes.

User report 16 Oct 2026: the note appeared at start-up BEFORE the modular
update check had installed anything.
"""

import ast
import json
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STARTUP = ROOT / 'plugin.program.kodipovilwizard' / 'startup.py'
UPDATER = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs' / 'modular_updater.py'


def _load_notice_functions(userdata, note, noteid='704', dismissed='true'):
    src = STARTUP.read_text('utf-8-sig')
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in ('_note_waited', 'show_notification'))
            or (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in ('NOTE_MAX_WAIT_BOOTS', 'NOTE_WAIT_FILE')
                                                  for t in n.targets))]
    shown, settings = [], {'noteid': noteid}
    config = types.SimpleNamespace(
        USERDATA=str(userdata), NOTIFICATION='url', NOTEID=noteid, NOTEDISMISS=dismissed,
        set_setting=lambda k, v: settings.__setitem__(k, v))
    window = types.SimpleNamespace(split_notify=lambda url: note, show_notification=shown.append)
    ns = {'os': __import__('os'), 'CONFIG': config, 'window': window,
          'logging': types.SimpleNamespace(log=lambda *a, **k: None),
          'xbmc': types.SimpleNamespace(LOGINFO=1)}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(STARTUP), 'exec'), ns)
    return ns, shown, settings


class UpdateNoteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_a_current_device_sees_the_new_note_at_once(self):
        ns, shown, settings = _load_notice_functions(self.dir, ('712', 'msg'))
        ns['show_notification'](build_current=True)
        self.assertEqual(shown, ['msg'])
        self.assertEqual(settings['noteid'], '712')

    def test_a_device_still_updating_waits_then_sees_it_on_the_third_start(self):
        for start in (1, 2):
            ns, shown, settings = _load_notice_functions(self.dir, ('712', 'msg'))
            ns['show_notification'](build_current=False)
            self.assertEqual(shown, [], 'start %d' % start)
            self.assertEqual(settings['noteid'], '704')      # not consumed
        ns, shown, settings = _load_notice_functions(self.dir, ('712', 'msg'))
        ns['show_notification'](build_current=False)
        self.assertEqual(shown, ['msg'])
        self.assertEqual(settings['noteid'], '712')

    def test_the_wait_counter_restarts_for_a_newer_note(self):
        (self.dir / 'kodipovil.note_wait.json').write_text(json.dumps({'id': '711', 'count': 2}))
        ns, shown, _settings = _load_notice_functions(self.dir, ('712', 'msg'))
        ns['show_notification'](build_current=False)
        self.assertEqual(shown, [])

    def test_a_damaged_wait_file_never_breaks_start_up(self):
        for raw in ('[]', 'null', '{"id": "712", "count": "x"}', 'not json'):
            (self.dir / 'kodipovil.note_wait.json').write_text(raw)
            ns, shown, _settings = _load_notice_functions(self.dir, ('712', 'msg'))
            ns['show_notification'](build_current=False)       # no exception
            self.assertEqual(shown, [], raw)

    def test_a_note_that_cannot_count_starts_is_shown_at_once(self):
        ns, shown, _settings = _load_notice_functions(self.dir / 'missing-dir', ('712', 'msg'))
        ns['show_notification'](build_current=False)
        self.assertEqual(shown, ['msg'])

    def test_the_note_is_shown_after_the_modular_update_gate(self):
        src = STARTUP.read_text('utf-8-sig')
        call = src.index("show_notification(build_current=bool(getattr(_mu, 'build_current', False)))")
        self.assertLess(src.index('_mu.run_update_check()'), call)
        calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'show_notification']
        self.assertEqual(len(calls), 1)                       # only the post-update call

    def test_the_updater_reports_whether_the_device_is_current(self):
        src = UPDATER.read_text('utf-8-sig')
        self.assertEqual(src.count('self.build_current = bool(self._record_build_identity(manifest))'), 2)


if __name__ == '__main__':
    unittest.main()
