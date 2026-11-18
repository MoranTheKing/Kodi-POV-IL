"""Wizard 0.5.6: the logo hook in POV's art builder gave some titles no logo (patches_config.py, pov_logo_for_ui v3).

POV builds a list's titles in about twenty threads, and each asks the hook for its `povil_logo` art. The hook
looked its module up with sys.modules.get(): while the first thread was still importing it, the others got the
half-loaded module from there, failed on its missing function and -- the hook swallows errors -- left their
title without a logo. Seen in the QA Kodi, Nov 2026: two builds of one list differed in which ten titles had a
logo, so Onyx showed a plain title for some films and a logo for others, and every rebuild "changed".
"""
import importlib.util
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches/patches_config.py'


def clean_path():
    """sys.path without any folder that holds the real pov_logo_lang (other tests add the Wizard's patches folder)."""
    return mock.patch.object(sys, 'path', [p for p in sys.path if not os.path.isfile(os.path.join(p or '.', 'pov_logo_lang.py'))])


def hook():
    spec = importlib.util.spec_from_file_location('patches_config_logo_test', CONFIG)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}):
        spec.loader.exec_module(module)
    patches = next(v for v in vars(module).values() if isinstance(v, list) and v and isinstance(v[0], dict) and 'hook' in v[0])
    return next(p for p in patches if p['id'] == 'pov_logo_for_ui')


class LogoHookTests(unittest.TestCase):
    def test_every_thread_gets_its_logo_while_the_module_is_still_loading(self):
        patch = hook()
        self.assertEqual(patch['marker'], '# WIZARD_POV_LOGO_FOR_UI_v3', 'a new marker: devices take the new block')
        self.assertNotIn('sys.modules.get', patch['hook'])
        with tempfile.TemporaryDirectory() as folder:
            # a module that takes a while to load, as on a busy box
            (Path(folder) / 'pov_logo_lang.py').write_text(
                'import time\ntime.sleep(0.3)\ndef for_ui(meta, clearlogo):\n    return clearlogo\n', encoding='utf-8')
            scope = {}
            exec('def art_of(meta, clearlogo):\n\tart = {}\n' +
                 ''.join('\t' + line + '\n' for line in patch['hook'].splitlines()) + '\treturn art\n', scope)
            results = []

            def one(n):
                results.append(scope['art_of']({'title': 'Film'}, 'logo%d.png' % n))
            fake_vfs = types.SimpleNamespace(translatePath=lambda path: folder)
            saved = sys.modules.pop('pov_logo_lang', None)
            try:
                with mock.patch.dict(sys.modules, {'xbmcvfs': fake_vfs}), clean_path():
                    threads = [threading.Thread(target=one, args=(n,)) for n in range(12)]
                    threads[0].start()
                    # the others arrive while the first is in the middle of loading the module: it is in
                    # sys.modules already, without its function yet
                    for _ in range(200):
                        if 'pov_logo_lang' in sys.modules:
                            break
                        time.sleep(0.005)
                    self.assertIn('pov_logo_lang', sys.modules)
                    self.assertFalse(hasattr(sys.modules['pov_logo_lang'], 'for_ui'), 'still loading: the case under test')
                    for thread in threads[1:]:
                        thread.start()
                    for thread in threads:
                        thread.join(10)
            finally:
                sys.modules.pop('pov_logo_lang', None)
                if saved is not None:
                    sys.modules['pov_logo_lang'] = saved
                if folder in sys.path:
                    sys.path.remove(folder)
            self.assertEqual(sorted(r.get('povil_logo', 'MISSING') for r in results), sorted('logo%d.png' % n for n in range(12)))

    def test_a_missing_module_still_costs_the_title_nothing_else(self):
        patch = hook()
        scope = {}
        exec('def art_of(meta, clearlogo):\n\tart = {"poster": "p"}\n' +
             ''.join('\t' + line + '\n' for line in patch['hook'].splitlines()) + '\treturn art\n', scope)
        saved = sys.modules.pop('pov_logo_lang', None)
        try:
            with mock.patch.dict(sys.modules, {'xbmcvfs': types.SimpleNamespace(translatePath=lambda path: 'Z:/nowhere/')}), clean_path():
                self.assertEqual(scope['art_of']({}, 'logo.png'), {'poster': 'p'})
        finally:
            if saved is not None:
                sys.modules['pov_logo_lang'] = saved
            while 'Z:/nowhere/' in sys.path:
                sys.path.remove('Z:/nowhere/')


if __name__ == '__main__':
    unittest.main()
