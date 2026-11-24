"""Wizard 0.5.50: what the continue-watching filter leaves out goes to the log; the sent-log window photographs well.

A viewer, Nov 2026 (no Trakt account): POV asked him "resume from ...?" on an episode of 9-1-1: Lone Star, so its
place was kept, yet "פרקים שהתחלתם" came back empty, before and after he watched on. The same row of the same
show listed in the QA Kodi; the log could not say whether his show was on the hidden list ("הסר מהמשך צפייה")
or the row failed later. Each list the filter sees now writes one line: rows in, rows kept, and the TMDb ids the
hidden list left out (or that the hidden list could not be read, which hides every show).

The owner, the same day: the sent-log window's link and the log names were in the Wizard's blue, dark on that
dark window, and hard to photograph. The link is white and bold now, the names a light amber.
"""
import ast
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

WIZ = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
CW = WIZ / 'resources/libs/patches/pov_continue_watching.py'
LOGGING = WIZ / 'resources/libs/common/logging.py'


def load_cw():
    spec = importlib.util.spec_from_file_location('continue_log_tests', CW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FilterLog(unittest.TestCase):
    def setUp(self):
        self.cw = load_cw()
        self.lines = []
        xbmc = types.ModuleType('xbmc')
        xbmc.LOGINFO = 1
        xbmc.log = lambda text, level=0: self.lines.append(text)
        self.modules = patch.dict(sys.modules, {'xbmc': xbmc})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def menu(self, list_type='in_progress', ids=('89393', '1399')):
        return types.SimpleNamespace(list_type=list_type, watched_indicators=0,
                                     list=[{'media_ids': {'tmdb': i}} for i in ids])

    def test_a_hidden_show_is_named_in_the_log(self):
        menu = self.menu()
        with patch.object(self.cw, 'dropped_info', return_value={89393}):
            self.cw.filter_episode_sources(menu)
        self.assertEqual(menu.list, [{'media_ids': {'tmdb': '1399'}}])
        self.assertEqual(self.lines, ['[POV IL continue] in_progress: 2 row(s), 1 kept, left out (hidden): 89393'])

    def test_nothing_left_out_says_so_in_one_line(self):
        menu = self.menu(list_type='next_episode_pov')
        with patch.object(self.cw, 'dropped_info', return_value=set()):
            self.cw.filter_episode_sources(menu)
        self.assertEqual(len(menu.list), 2)
        self.assertEqual(self.lines, ['[POV IL continue] next_episode_pov: 2 row(s), 2 kept'])

    def test_an_unreadable_hidden_list_says_why_every_show_is_left_out(self):
        menu = self.menu()
        with patch.object(self.cw, 'dropped_info', return_value=self.cw._UnknownHidden()):
            self.cw.filter_episode_sources(menu)
        self.assertEqual(menu.list, [])
        self.assertIn('left out (the hidden list could not be read): 1399,89393', self.lines[0])

    def test_lists_the_filter_does_not_touch_write_nothing(self):
        menu = self.menu(list_type='trakt_calendar')
        self.cw.filter_episode_sources(menu)
        self.assertEqual(self.lines, [])

    def test_the_shows_in_progress_write_their_line_too(self):
        menu = types.SimpleNamespace(action='in_progress_tvshows', watched_indicators=0, list=['89393', '1399'])
        with patch.object(self.cw, 'dropped_info', return_value={1399}):
            self.cw.filter_show_sources(menu)
        self.assertEqual(menu.list, ['89393'])
        self.assertEqual(self.lines, ['[POV IL continue] in_progress_tvshows: 2 row(s), 1 kept, left out (hidden): 1399'])

    def test_a_log_that_fails_never_breaks_the_list(self):
        sys.modules['xbmc'].log = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no log'))
        menu = self.menu()
        with patch.object(self.cw, 'dropped_info', return_value={89393}):
            self.cw.filter_episode_sources(menu)
        self.assertEqual(menu.list, [{'media_ids': {'tmdb': '1399'}}])


class SentLogColors(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(LOGGING.read_text('utf8'))
        nodes = [n for n in tree.body if isinstance(n, ast.Assign) and any(
            getattr(t, 'id', '').startswith('SENT_') for t in n.targets)]
        nodes += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'sent_message']
        self.scope = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(LOGGING), 'exec'), self.scope)

    def test_the_link_is_white_and_bold_on_a_line_of_its_own(self):
        msg = self.scope['sent_message']('kodi.log + kodi.old.log', 'https://paste.kodi.tv/fixture')
        self.assertTrue(msg.endswith('[CR][COLOR FFFFFFFF][B]https://paste.kodi.tv/fixture[/B][/COLOR]'))

    def test_the_log_names_are_amber_and_nothing_is_blue(self):
        msg = self.scope['sent_message']('kodi.log', 'https://paste.kodi.tv/fixture')
        self.assertIn('([COLOR FFFFD54F]kodi.log[/COLOR])', msg)
        self.assertNotIn('blue', msg.lower())
        # in the build's Hebrew: "the log was sent ... send the link or a photo of the code"
        self.assertTrue(msg.startswith('הלוג נשלח'))

    def test_the_upload_uses_it(self):
        source = LOGGING.read_text('utf8')
        self.assertIn('msg = sent_message(name, result)', source)
        self.assertEqual(len(re.findall(r'CONFIG\.COLOR1, name, CONFIG\.COLOR1', source)), 0)


if __name__ == '__main__':
    unittest.main()
