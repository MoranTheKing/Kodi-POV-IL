"""MoranSubs 0.3.96: with "Google Translate" (or "no translation") chosen, no text request is made to Gemini.

A viewer, Nov 2026: "with Google Translate chosen it still tries to translate with AI and runs into 'busy' --
it has to be Google only".
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'


def load_gemini(mode):
    """gemini.py as a module of a package whose kodi_utils answers the translation mode."""
    package = types.ModuleType('povil_gm_test')
    package.__path__ = [str(LIB)]
    kodi_utils = types.ModuleType('povil_gm_test.kodi_utils')
    kodi_utils.get_setting = lambda key, default='': mode if key == 'translation_mode' else default
    kodi_utils.log = lambda *a, **k: None
    spec = importlib.util.spec_from_file_location('povil_gm_test.gemini', LIB / 'gemini.py')
    gemini = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {'povil_gm_test': package, 'povil_gm_test.kodi_utils': kodi_utils,
                                       'povil_gm_test.gemini': gemini}):
        spec.loader.exec_module(gemini)
    return gemini, package, kodi_utils


class GoogleModeTests(unittest.TestCase):
    def ask(self, mode):
        gemini, package, kodi_utils = load_gemini(mode)
        sent = []

        class Requests(object):
            def post(self, *args, **kwargs):
                sent.append(args)
                raise RuntimeError('reached the network')
        gemini.requests = Requests()
        with mock.patch.dict(sys.modules, {'povil_gm_test': package, 'povil_gm_test.kodi_utils': kodi_utils,
                                           'povil_gm_test.gemini': gemini}):
            try:
                gemini.generate('key', 'gemini-3.5-flash-lite', 'prompt')
            except gemini.GeminiError as exc:
                return sent, str(exc)
            except Exception as exc:
                return sent, 'other: %s' % exc
        return sent, 'answered'

    def test_nothing_is_asked_of_gemini_in_the_google_and_the_none_modes(self):
        for mode in ('google', 'none'):
            sent, said = self.ask(mode)
            self.assertEqual(sent, [], mode)
            self.assertIn('no request is made', said, mode)

    def test_the_ai_mode_asks_as_always(self):
        sent, said = self.ask('ai')
        self.assertEqual(len(sent), 1, 'the request went out: %s' % said)
        sent, said = self.ask('')
        self.assertEqual(len(sent), 1, 'a setting never written is the AI mode, the default')

    def test_the_proofread_is_not_due_outside_the_ai_mode(self):
        source = (LIB / 'translate.py').read_text('utf-8')
        body = source[source.index('def _gp_models_left('):source.index('def _proofread_due(')]
        self.assertLess(body.index("get_setting('translation_mode', 'ai') or 'ai') != 'ai'"), body.index('gender_proofread.exhausted_today'))
        due = source[source.index('def _proofread_due('):source.index('def _proofread_stopper(')]
        self.assertIn('_gp_models_left', due, 'the one test every proofread goes through')


if __name__ == '__main__':
    unittest.main()
