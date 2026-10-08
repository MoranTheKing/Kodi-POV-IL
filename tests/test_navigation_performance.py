"""Exception diagnostics and saved views must not block or steal navigation."""
import importlib.util
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PATCHES = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard/resources/libs/patches'


def load(name, modules):
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location('test_' + name, PATCHES / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class ExceptionTraceTests(unittest.TestCase):
    def check_events(self, threaded=False, nested=False):
        module = load('pov_content_logger', {'xbmc': types.SimpleNamespace(log=lambda *a: None, LOGWARNING=2)})
        events, logs = [], []
        local = module._local_tracer
        def observe(frame, event, arg):
            events.append(event)
            local(frame, event, arg)
            return observe
        module._local_tracer = observe
        module._log = logs.append
        def build_movie_content():
            result = 0
            for position in range(100):
                result += position
            try:
                raise ValueError('fixture swallowed error')
            except ValueError:
                pass
            return result
        previous = sys.gettrace()
        try:
            module.enable()
            if nested:
                module.enable()
                module.disable()
            if threaded:
                thread = threading.Thread(target=build_movie_content)
                thread.start()
                thread.join()
            else:
                self.assertEqual(build_movie_content(), 4950)
        finally:
            module.disable()
            sys.settrace(previous)
        self.assertEqual(events.count('exception'), 1)
        self.assertNotIn('line', events)
        self.assertEqual(len(logs), 1)
        self.assertIn('fixture swallowed error', logs[0])
        self.assertEqual(module._depth, 0)
    def test_exception_survives_without_line_callbacks(self): self.check_events()
    def test_worker_exception_survives_without_line_callbacks(self): self.check_events(threaded=True)
    def test_nested_scope_keeps_exception_diagnostics(self): self.check_events(nested=True)


class SavedViewTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0
        self.window = 10025
        self.skin = 'skin.estuary'
        self.profile = '/qa/master/'
        self.folder = 'plugin://plugin.video.pov/?action=popular&mode=movies'
        self.content = 'movies'
        self.updating = False
        self.visible = False
        self.supported = True
        self.aborted = False
        self.commands = []
        self.onwait = lambda: None
        def wait(seconds):
            self.clock += seconds
            self.onwait()
            return self.aborted
        def command(value):
            self.commands.append(value)
            self.visible = self.supported
        kodi = types.SimpleNamespace(
            getSkinDir=lambda: self.skin, getInfoLabel=lambda key: self.folder if key.endswith('FolderPath') else self.content,
            getCondVisibility=lambda key: self.updating if key=='Container.IsUpdating' else self.visible,
            executebuiltin=command, log=lambda *args: None, LOGWARNING=2,
            Monitor=lambda: types.SimpleNamespace(abortRequested=lambda: self.aborted, waitForAbort=wait))
        self.module = load('pov_view_mode', dict(xbmc=kodi,
            xbmcgui=types.SimpleNamespace(getCurrentWindowId=lambda: self.window),
            xbmcvfs=types.SimpleNamespace(translatePath=lambda _: self.profile)))
        self.module.time = types.SimpleNamespace(monotonic=lambda: self.clock)
        self.args = patch.object(sys, 'argv', ['plugin://plugin.video.pov/', '1', '?mode=movies&action=popular'])
        self.args.start()
        self.addCleanup(self.args.stop)

    def test_already_selected_returns_without_delay_or_gui_command(self):
        self.visible = True
        self.assertTrue(self.module.force_view('55','movies'))
        self.assertEqual((self.clock,self.commands),(0,[]))

    def test_change_applies_once_and_confirms_next_frame(self):
        self.assertTrue(self.module.force_view('55','movies'))
        self.assertEqual(self.commands,['Container.SetViewMode(55)'])
        self.assertLessEqual(self.clock,.05)

    def test_outgoing_same_content_is_never_modified(self):
        self.folder += '&page=old'
        self.assertFalse(self.module.force_view('55','movies'))
        self.assertEqual(self.commands,[])
        self.assertLess(self.clock,1.56)

    def test_incoming_directory_waits_for_finished_update(self):
        self.updating = True
        self.onwait = lambda: setattr(self,'updating',False)
        self.assertTrue(self.module.force_view('55','movies'))
        self.assertEqual(len(self.commands),1)

    def test_unavailable_skin_view_never_repeats_for_a_second(self):
        self.supported = False
        self.assertFalse(self.module.force_view('51','movies'))
        self.assertEqual(len(self.commands),2)
        self.assertLess(self.clock,.15)

    def test_back_wins_after_first_command(self):
        self.supported = False
        self.onwait = lambda: setattr(self,'window',10000)
        self.assertFalse(self.module.force_view('55','movies'))
        self.assertEqual(len(self.commands),1)

    def test_profile_switch_cancels_outstanding_view(self):
        self.supported=False
        self.onwait=lambda: setattr(self,'profile','/qa/child/')
        self.assertFalse(self.module.force_view('55','movies'))
        self.assertEqual(len(self.commands),1)

    def test_skin_switch_cancels_outstanding_view(self):
        self.supported=False
        self.onwait=lambda: setattr(self,'skin','skin.fentastic')
        self.assertFalse(self.module.force_view('55','movies'))
        self.assertEqual(len(self.commands),1)

    def test_abort_and_invalid_ids_do_not_change_gui(self):
        self.aborted=True
        for view in ('55',None,'invalid',-1):
            self.assertFalse(self.module.force_view(view,'movies'))
        self.assertEqual(self.commands,[])
