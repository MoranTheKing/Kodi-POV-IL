"""Native dependency eligibility and scoped GUI retention hooks."""
import importlib.util
import json
import os
import re
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from test_provisioning_gate import _load_function, ROOT

LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'


class PlatformSkinIncidents(unittest.TestCase):
    def test_home_bootstrap_cannot_interrupt_pending_skin_confirmation(self):
        kodi = types.SimpleNamespace(executebuiltin=lambda _: self.fail('unexpected reload'))
        requested = ['skin.povil.nox']
        gui = types.SimpleNamespace(Window=lambda _: types.SimpleNamespace(
            getProperty=lambda _: requested[0]), getCurrentWindowDialogId=lambda: 10100)
        fn = _load_function(ROOT / 'plugin.program.kodipovilwizard/profile_bootstrap.py',
                            'resume', dict(xbmc=kodi, xbmcgui=gui))
        self.assertFalse(fn())
        requested[0] = ''  # Kodi's own manual skin picker has no scoped request.
        self.assertFalse(fn())

    def platform(self, folder, apple=True, version=None, enabled=True):
        state = {'version': version, 'enabled': enabled}; calls = []; notifications = []; properties = {}
        def rpc(raw):
            request = json.loads(raw); calls.append(request)
            if request['method'] == 'Addons.SetAddonEnabled':
                state['enabled'] = True; return '{"result":"OK"}'
            return json.dumps({'result': {'addon': state}} if state['version'] else {'error': {}})
        modules = dict(xbmc=types.SimpleNamespace(getCondVisibility=lambda cond: apple and cond.endswith('TVOS'),
            executeJSONRPC=rpc, getInfoLabel=lambda _: '21.3', log=lambda *args: None, LOGWARNING=2),
            xbmcgui=types.SimpleNamespace(Window=lambda _: types.SimpleNamespace(
                getProperty=lambda key: properties.get(key, ''), setProperty=properties.__setitem__),
                Dialog=lambda: types.SimpleNamespace(notification=lambda *args, **kwargs: notifications.append(args))),
            xbmcvfs=types.SimpleNamespace(translatePath=lambda _: str(folder / 'receipt.json')))
        with patch.dict('sys.modules', modules):
            spec = importlib.util.spec_from_file_location('qa_youtube_platform', LIBS / 'youtube_platform.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module, state, calls, notifications

    def test_incompatible_apple_dependency_defers_only_youtube_once(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            module, state, calls, notes = self.platform(folder)
            ids = ['plugin.video.pov', 'plugin.video.youtube', 'skin.povil.nox']
            for version in (None, '18.9.0'):
                state['version'] = version
                self.assertEqual(module.eligible(ids), [ids[0], ids[2]])
                self.assertEqual(module.eligible(ids), [ids[0], ids[2]])
            self.assertEqual(len(notes), 2)  # one per actual capability change
            self.assertEqual(ids[1], 'plugin.video.youtube')  # caller untouched
            self.assertTrue((folder / 'receipt.json').exists())
            state['version'] = '21.5.25'
            self.assertEqual(module.eligible(ids), ids)
            self.assertFalse((folder / 'receipt.json').exists())

    def test_native_binary_resolution_is_retained_on_windows_android(self):
        with tempfile.TemporaryDirectory() as raw:
            module, _, _, notes = self.platform(Path(raw), apple=False)
            ids = ['plugin.video.youtube']
            self.assertEqual(module.eligible(ids), ids)
            self.assertEqual(notes, [])

    def test_compatible_disabled_adaptive_is_enabled_before_youtube(self):
        with tempfile.TemporaryDirectory() as raw:
            module, state, calls, notes = self.platform(Path(raw), version='19.0.0', enabled=False)
            self.assertEqual(module.eligible(['plugin.video.youtube']), ['plugin.video.youtube'])
            self.assertTrue(state['enabled'])
            self.assertEqual(calls[-1]['method'], 'Addons.SetAddonEnabled')
            self.assertEqual(notes, [])

    def test_read_only_profile_does_not_block_other_provisioning(self):
        with tempfile.TemporaryDirectory() as raw:
            module, _, _, notes = self.platform(Path(raw))
            with patch.object(module.os, 'makedirs', side_effect=OSError('read only')):
                self.assertEqual(module.eligible(['plugin.video.youtube','plugin.video.pov']), ['plugin.video.pov'])
                self.assertEqual(module.eligible(['plugin.video.youtube','plugin.video.pov']), ['plugin.video.pov'])
            self.assertEqual(len(notes), 1)

    def test_skin_switch_waits_for_gui_confirmation_and_never_certifies_pending_setting(self):
        properties = {}; actual = ['skin.estuary']; visible = [False]; polls = [0]; saved = []
        home = types.SimpleNamespace(getProperty=lambda key: properties.get(key, ''),
            setProperty=properties.__setitem__, clearProperty=lambda key: properties.pop(key,None))
        def wait(seconds):
            polls[0] += 1
            visible[0] = polls[0] < 4
            return False
        def rpc(method, params):
            if method.endswith('GetSettingValue'): return {'value': actual[0]}
            actual[0] = params['value'];return True
        def confirm(target):
            if polls[0] >= 3: properties['POVIL.SkinConfirmed'] = target
        fn = _load_function(LIBS / 'build_skin.py', 'activate', dict(
            SKINS=('skin.fentastic',), enable_skin=lambda _:True, rpc=rpc,
            threading=types.SimpleNamespace(Event=threading.Event,
                Thread=lambda **_:types.SimpleNamespace(start=lambda:None,join=lambda _:None)),
            confirm_requested_skin=confirm, persist_live_settings=lambda:saved.append(polls[0]) or True,
            xbmcgui=types.SimpleNamespace(Window=lambda _:home),
            xbmc=types.SimpleNamespace(getSkinDir=lambda:actual[0], getCondVisibility=lambda _:visible[0],
                Monitor=lambda:types.SimpleNamespace(abortRequested=lambda:False,waitForAbort=wait))))
        self.assertTrue(fn('skin.fentastic'))
        self.assertEqual(saved, [4])
        self.assertEqual(properties,{})
        actual[0] = 'skin.estuary';polls[0] = 0;saved.clear()
        fn.__globals__['confirm_requested_skin'] = lambda _:None
        self.assertFalse(fn('skin.fentastic'))
        self.assertEqual(saved, [])
        self.assertEqual(properties,{})


if __name__ == '__main__':
    unittest.main()
