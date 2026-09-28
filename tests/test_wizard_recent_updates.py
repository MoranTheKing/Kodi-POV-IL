"""Exercise the two public update-note entry points without a Kodi install."""

import ast
import re
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    self_contained = ast.Module(body=nodes, type_ignores=[])
    exec(compile(self_contained, str(path), 'exec'), namespace)
    return namespace


class WizardRecentUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.archive_url = 'https://example.invalid/recent_updates.txt'
        self.config = types.SimpleNamespace(
            RECENT_UPDATES_URL=self.archive_url, THEME3='[B]{0}[/B]',
            ADDONTITLE='POV IL', COLOR2='yellow')
        self.tools = types.SimpleNamespace(open_url=Mock())
        self.dialog = Mock()
        self.log = types.SimpleNamespace(log=Mock(), log_notify=Mock())
        self.ns = load_functions(
            ROOT / 'resources/libs/gui/window.py',
            {'split_notify', 'recent_updates_text', 'show_recent_updates'},
            {'CONFIG': self.config, 'tools': self.tools, 'logging': self.log,
             'show_text_box': self.dialog, 're': re})

    def test_click_shows_ten_real_notes_and_preserves_separator_in_body(self):
        notes = []
        for number in range(667, 656, -1):
            body = 'תודה למנחם פורגס ||| על העזרה' if number == 667 else 'שינוי'
            notes.append('{0}|||עדכון #{0}\r\n{1}\r\n'.format(number, body))
        self.tools.open_url.return_value = types.SimpleNamespace(
            text=''.join(notes))
        self.assertTrue(self.ns['show_recent_updates']())
        self.tools.open_url.assert_called_once_with(self.archive_url)
        self.dialog.assert_called_once()
        title, text = self.dialog.call_args.args
        self.assertEqual(title, '10 העדכונים האחרונים')
        self.assertIn('תודה למנחם פורגס ||| על העזרה', text)
        self.assertIn('עדכון #658', text)
        self.assertNotIn('עדכון #657', text)
        self.assertEqual(text.count('[B]עדכון #'), 10)

    def test_archive_failure_reports_it_without_opening_an_empty_dialog(self):
        self.tools.open_url.side_effect = TimeoutError('offline')
        self.assertFalse(self.ns['show_recent_updates']())
        self.dialog.assert_not_called()
        self.log.log_notify.assert_called_once()

    def test_single_notification_does_not_split_body_on_separator(self):
        self.tools.open_url.return_value = types.SimpleNamespace(
            text='667|||שדרוג\nתודה ||| למנחם')
        note_id, body = self.ns['split_notify']('https://example.invalid/note')
        self.assertEqual(note_id, '667')
        self.assertEqual(body, 'שדרוג[CR]תודה ||| למנחם')

    def test_new_notice_is_shown_once_and_keeps_the_existing_dismissal(self):
        tree = ast.parse((ROOT / 'uservar.py').read_text(encoding='utf-8'))
        values = {target.id: node.value.value
                  for node in tree.body if isinstance(node, ast.Assign)
                  for target in node.targets if isinstance(target, ast.Name)
                  and isinstance(node.value, ast.Constant)}
        self.assertEqual(values['ENABLE'], 'Yes')
        self.assertTrue(values['NOTIFICATION'].endswith('/quick_update.txt'))

        class Config:
            NOTIFICATION = values['NOTIFICATION']
            NOTEID = '666'
            NOTEDISMISS = 'true'

            def __init__(self):
                self.saved = {}

            def set_setting(self, key, value):
                self.saved[key] = value

        config = Config()
        window = types.SimpleNamespace(
            split_notify=Mock(return_value=('667', 'תודה למנחם')),
            show_notification=Mock())
        startup = load_functions(
            ROOT / 'startup.py', {'show_notification'},
            {'CONFIG': config, 'window': window,
             'logging': types.SimpleNamespace(log=Mock()),
             'xbmc': types.SimpleNamespace(LOGINFO=1)})
        startup['show_notification']()
        self.assertEqual(config.saved,
                         {'noteid': '667', 'notedismiss': 'false'})
        window.show_notification.assert_called_once_with('תודה למנחם')
        config.NOTEID = '667'
        config.NOTEDISMISS = 'true'
        startup['show_notification']()
        window.show_notification.assert_called_once()


if __name__ == '__main__':
    unittest.main()
