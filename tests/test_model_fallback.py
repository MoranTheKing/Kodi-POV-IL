"""A translation whose chosen model does not answer goes on with the default
model (MoranSubs 0.3.78).

Field report, Nov 2026: "Gemini is busy all the time and does not translate;
the point is subtitles when you start watching, not when you finish".
Measured that night: gemini-3.5-flash-lite (the default) answered a 40-line
request in 2 s; every full Flash model (3.5, 3.6, 3.7, 3.8) answered 503 or
nothing within 90 s; gemini-3.1-flash, gemini-2.5-flash and
gemini-2.5-flash-lite -- three of the five ids in the settings list -- were
404 for the key. A viewer on any of those got a five-step backoff per chunk
(230 s) or three 90 s timeouts, and then Google Translate."""
import importlib.util
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'
TRANSLATE = (LIB / 'translate.py').read_text('utf-8')
SETTINGS = (ROOT / 'service.subtitles.kodipovilai/resources/settings.xml').read_text('utf-8')


def load_translate():
    """translate.py's module-level helpers, without Kodi."""
    props = {}
    window = types.SimpleNamespace(
        getProperty=lambda name: props.get(name, ''),
        setProperty=lambda name, value: props.__setitem__(name, value),
        clearProperty=lambda name: props.pop(name, None))
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.Window = lambda ident: window
    stubs = {name: types.ModuleType(name) for name in ('xbmc', 'xbmcaddon', 'xbmcvfs', 'xbmcplugin')}
    stubs['xbmcgui'] = xbmcgui
    # A private copy of the package: other test modules hold their own
    # `resources.lib` objects, and replacing those under them breaks every
    # patch they apply afterwards (test_search_provider_skins did).
    def ours(name):
        return name == 'resources' or name.startswith('resources.')
    kept = {name: sys.modules.pop(name) for name in list(sys.modules) if ours(name)}
    try:
        with patch.dict(sys.modules, stubs):
            sys.path.insert(0, str(ROOT / 'service.subtitles.kodipovilai'))
            try:
                from resources.lib import translate
            finally:
                sys.path.pop(0)
    finally:
        for name in list(sys.modules):
            if ours(name):
                del sys.modules[name]
        sys.modules.update(kept)
    return translate, props, xbmcgui


class Rules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t, cls.props, cls.gui = load_translate()

    def setUp(self):
        self.props.clear()
        self.patcher = patch.dict(sys.modules, {'xbmcgui': self.gui})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_the_chosen_model_is_asked_first(self):
        m = self.t._ModelFallback('gemini-3.8-flash')
        self.assertEqual((m.model, m.why, m.chosen), ('gemini-3.8-flash', '', 'gemini-3.8-flash'))

    def test_a_failed_chosen_model_gives_way_to_the_default_once(self):
        m = self.t._ModelFallback('gemini-3.8-flash')
        self.assertTrue(m.give_up('gemini-3.8-flash', 'busy'))
        self.assertEqual((m.model, m.why), ('gemini-3.5-flash-lite', 'busy'))
        # a chunk whose request was already out to the old model: send it again
        self.assertTrue(m.give_up('gemini-3.8-flash', 'slow'))
        self.assertEqual(m.why, 'busy')
        # the default model itself has nothing behind it
        self.assertFalse(m.give_up('gemini-3.5-flash-lite', 'busy'))
        self.assertEqual(m.model, 'gemini-3.5-flash-lite')

    def test_the_default_model_never_falls_back(self):
        for chosen in ('gemini-3.5-flash-lite', '', None):
            m = self.t._ModelFallback(chosen)
            self.assertEqual(m.model, 'gemini-3.5-flash-lite')
            self.assertFalse(m.give_up('gemini-3.5-flash-lite', 'busy'))
            self.assertEqual(m.why, '')
        self.assertEqual(self.props, {})

    def test_the_next_translations_start_on_the_default_for_a_while(self):
        t = self.t
        t._ModelFallback('gemini-3.8-flash').give_up('gemini-3.8-flash', 'busy')
        again = t._ModelFallback('gemini-3.8-flash')
        self.assertEqual((again.model, again.why), ('gemini-3.5-flash-lite', 'busy'))
        # another model is not touched by it
        self.assertEqual(t._ModelFallback('gemini-3.6-flash').model, 'gemini-3.6-flash')

    def test_how_long_each_reason_lasts(self):
        t = self.t
        self.assertEqual(t._MODEL_OUT_S, {'busy': 600, 'slow': 600, 'quota': 10800, 'gone': 21600})
        for why, seconds in t._MODEL_OUT_S.items():
            t._model_out_note('gemini-x', why, now=1000.0)
            self.assertEqual(t._model_out('gemini-x', now=1000.0 + seconds - 1), why)
            self.assertEqual(t._model_out('gemini-x', now=1000.0 + seconds + 1), '')

    def test_a_damaged_or_foreign_note_reads_as_none(self):
        t = self.t
        for raw in ('', 'x', '99999999999|', '99999999999|other', 'abc|busy', '|busy'):
            self.props[t._model_out_key('gemini-x')] = raw
            self.assertEqual(t._model_out('gemini-x', now=1.0), '', raw)

    def test_no_kodi_window_is_no_note_and_no_crash(self):
        t = self.t
        broken = types.ModuleType('xbmcgui')
        with patch.dict(sys.modules, {'xbmcgui': broken}):
            t._model_out_note('gemini-x', 'busy')
            self.assertEqual(t._model_out('gemini-x'), '')
            m = t._ModelFallback('gemini-3.8-flash')
            self.assertTrue(m.give_up('gemini-3.8-flash', 'busy'))
            self.assertEqual(m.model, 'gemini-3.5-flash-lite')

    def test_two_chunks_failing_together_switch_once(self):
        notes = []
        m = self.t._ModelFallback('gemini-3.8-flash',
                                  note=lambda model, why, api_key='': notes.append((model, why)))
        barrier = threading.Barrier(8)
        results = []

        def chunk():
            barrier.wait()
            results.append(m.give_up('gemini-3.8-flash', 'busy'))
        threads = [threading.Thread(target=chunk) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results, [True] * 8)
        self.assertEqual(notes, [('gemini-3.8-flash', 'busy')])

    def test_the_note_belongs_to_the_api_key_that_was_refused(self):
        t = self.t
        t._ModelFallback('gemini-3.8-flash', api_key='key-one').give_up('gemini-3.8-flash', 'quota')
        self.assertEqual(t._ModelFallback('gemini-3.8-flash', api_key='key-one').model, 'gemini-3.5-flash-lite')
        self.assertEqual(t._ModelFallback('gemini-3.8-flash', api_key='key-two').model, 'gemini-3.8-flash')
        self.assertEqual(t._ModelFallback('gemini-3.8-flash').model, 'gemini-3.8-flash')
        self.assertFalse(any('key-one' in name for name in self.props))      # never the key itself

    def test_a_model_that_is_gone_is_said_even_when_toasts_are_quiet(self):
        t = self.t
        shown = []
        with patch.object(t.kodi_utils, 'notify', lambda msg, **kw: shown.append(msg), create=True), \
                patch.object(t, '_QUIET', True):
            t._model_fallback_notice('gemini-3.1-flash', 'gone')
            t._model_fallback_notice('gemini-3.8-flash', 'busy')
            t._model_fallback_notice('gemini-3.8-flash', 'quota')
        self.assertEqual(len(shown), 1)
        self.assertIn('כבר לא זמין אצל Google', shown[0])
        with patch.object(t.kodi_utils, 'notify', lambda msg, **kw: shown.append(msg), create=True), \
                patch.object(t, '_QUIET', False):
            t._model_fallback_notice('gemini-3.8-flash', 'busy')
        self.assertEqual(len(shown), 2)

    def test_what_the_viewer_is_told(self):
        t = self.t
        self.assertEqual(t._model_label('gemini-3.8-flash'), '3.8 Flash')
        self.assertEqual(t._model_label('gemini-3.5-flash-lite'), '3.5 Flash Lite')
        self.assertEqual(t._model_label(''), 'Gemini')
        busy = t._model_fallback_message('gemini-3.8-flash', 'busy')
        self.assertEqual(busy, 'AI: 3.8 Flash עמוס כרגע — ממשיך עם 3.5 Flash Lite')
        self.assertEqual(t._model_fallback_message('gemini-3.8-flash', 'slow'), busy)
        self.assertIn('נגמרה המכסה היומית של 3.8 Flash', t._model_fallback_message('gemini-3.8-flash', 'quota'))
        gone = t._model_fallback_message('gemini-3.1-flash', 'gone')
        self.assertIn('המודל 3.1 Flash כבר לא זמין אצל Google', gone)
        self.assertIn('אפשר להחליף מודל בהגדרות', gone)


class GeminiClient(unittest.TestCase):

    def test_a_404_is_its_own_error_and_still_a_gemini_error(self):
        spec = importlib.util.spec_from_file_location('gemini_404_test', LIB / 'gemini.py')
        gem = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {name: types.ModuleType(name) for name in ('xbmc', 'xbmcaddon', 'xbmcvfs')}):
            spec.loader.exec_module(gem)
        self.assertTrue(issubclass(gem.ModelUnavailable, gem.GeminiError))
        self.assertFalse(issubclass(gem.ModelUnavailable, (gem.OverloadError, gem.InvalidKey)))
        reply = types.SimpleNamespace(status_code=404, text='models/gemini-3.1-flash is not found', json=lambda: {})
        gem.requests = types.SimpleNamespace(post=lambda *a, **k: reply, RequestException=Exception)
        with self.assertRaises(gem.ModelUnavailable) as raised:
            gem.generate('key', 'gemini-3.1-flash', 'hi')
        self.assertIn('HTTP 404', str(raised.exception))
        self.assertFalse(raised.exception.answered)


class Wiring(unittest.TestCase):
    """The chunk loop is one long closure with no harness of its own; these
    pin that each failure reaches the fallback before its old retries."""

    def between(self, start, end):
        a = TRANSLATE.index(start)
        return TRANSLATE[a:TRANSLATE.index(end, a)]

    def test_the_job_starts_on_the_model_that_answers(self):
        self.assertIn("    model = _models.model\n", TRANSLATE)
        self.assertEqual(TRANSLATE.count('= _ModelFallback('), 1)

    def test_every_request_remembers_which_model_it_asked(self):
        loop = self.between('            _asked_model = model\n', '    # Parallel chunk dispatch.')
        self.assertEqual(loop.count('_go_on_with_fallback(_asked_model,'), 3)

    def test_quota_falls_back_before_it_aborts(self):
        block = self.between('            except gemini.QuotaExceeded:\n                # the chosen',
                             '            except gemini.InvalidKey as e:')
        self.assertLess(block.index("_go_on_with_fallback(_asked_model, 'quota')"), block.index("_AbortTranslation('quota'"))

    def test_a_busy_chosen_model_gets_no_second_try(self):
        block = self.between('            except gemini.OverloadError as e:\n                # No second try',
                             '            except gemini.GeminiError as e:')
        self.assertIn("                if ((_asked_model != model or not _paid_mode\n"
                      "                     or overload_attempts >= 1)\n"
                      "                        and _go_on_with_fallback(_asked_model, 'busy')):\n"
                      "                    overload_attempts = 0\n                    continue\n", block)
        self.assertLess(block.index('_go_on_with_fallback'), block.index('OVERLOAD_BACKOFF[overload_attempts]'))

    def test_a_chosen_model_gets_a_shorter_wait_than_the_default(self):
        self.assertIn("_CHOSEN_MODEL_TIMEOUT = 60\n", TRANSLATE)
        self.assertIn("timeout=gemini_timeout or (\n"
                      "                        gemini.REQUEST_TIMEOUT if model == _models.fallback\n"
                      "                        else _CHOSEN_MODEL_TIMEOUT),", TRANSLATE)

    def test_a_404_and_a_timeout_fall_back_at_once_and_a_dead_connection_does_not(self):
        block = self.between('            except gemini.GeminiError as e:\n                # Not served',
                             '    # Parallel chunk dispatch.')
        self.assertIn("'gone' if isinstance(e, gemini.ModelUnavailable)", block)
        self.assertIn("else 'slow' if (getattr(e, 'transport', False)\n"
                      "                                        and getattr(e, 'answered', False))", block)
        self.assertLess(block.index('_go_on_with_fallback'), block.index('GENERIC_BACKOFF[generic_attempts]'))

    def test_the_switch_moves_the_pace_and_the_thinking_setting_with_the_model(self):
        block = self.between('    def _go_on_with_fallback(asked, why):', '    # Per-chunk translator.')
        self.assertIn('nonlocal model, thinking_level, thinking_budget, _rpm_interval', block)
        self.assertIn('thinking_level, thinking_budget = _thinking_for(model)', block)
        self.assertIn('_gemini_free_rpm_cap(model)', block)

    def test_the_switch_frees_the_rate_gate_and_is_announced_once(self):
        block = self.between('    def _go_on_with_fallback(asked, why):', '    # Per-chunk translator.')
        self.assertIn('        with _switch_lock:\n            if model == _models.model:\n'
                      '                return True', block)
        self.assertIn('_GEMINI_NEXT_SLOT[0] = min(_GEMINI_NEXT_SLOT[0],\n'
                      '                                           time.monotonic())', block)
        self.assertEqual(block.count('_model_fallback_notice(asked, why)'), 1)

    def test_a_spent_day_is_noted_under_the_model_of_the_setting(self):
        self.assertIn('gemini_quota.note_exhausted(_models.chosen)', TRANSLATE)
        self.assertNotIn('gemini_quota.note_exhausted(model)', TRANSLATE)

    def test_the_settings_list_offers_no_model_google_does_not_have(self):
        self.assertNotIn('>gemini-3.1-flash</option>', SETTINGS)       # 404 for every key
        self.assertIn('>gemini-3.8-flash</option>', SETTINGS)
        self.assertIn('<default>gemini-3.5-flash-lite</default>', SETTINGS)


class StoredSetting(unittest.TestCase):
    """A stored 'gemini-3.1-flash' is moved to the default model, once."""

    def run_migration(self, stored, done=''):
        settings = {'model': stored, '_gemini_model_bump_v4': done}
        kodi = types.SimpleNamespace(
            get_setting=lambda key, default='': settings.get(key, default),
            set_setting=lambda key, value: settings.__setitem__(key, value),
            log=lambda *args, **kwargs: None)
        source = (ROOT / 'service.subtitles.kodipovilai/service.py').read_text('utf-8')
        start = source.index('def _maybe_retire_gemini_31_flash():')
        body = source[start:source.index('\ndef ', start + 10)]
        lib = types.ModuleType('resources.lib')
        lib.kodi_utils = kodi
        resources = types.ModuleType('resources')
        resources.lib = lib
        scope = {}
        with patch.dict(sys.modules, {'resources': resources, 'resources.lib': lib,
                                      'resources.lib.kodi_utils': kodi}):
            exec(body, scope)
            scope['_maybe_retire_gemini_31_flash']()
        return settings

    def test_it_moves_only_that_id_and_only_once(self):
        self.assertEqual(self.run_migration('gemini-3.1-flash'),
                         {'model': 'gemini-3.5-flash-lite', '_gemini_model_bump_v4': '1'})
        for kept in ('gemini-3.8-flash', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-3.5-flash-lite', ''):
            self.assertEqual(self.run_migration(kept)['model'], kept)
        self.assertEqual(self.run_migration('gemini-3.1-flash', done='1')['model'], 'gemini-3.1-flash')

    def test_the_service_runs_it(self):
        source = (ROOT / 'service.subtitles.kodipovilai/service.py').read_text('utf-8')
        self.assertIn('    _maybe_bump_gemini_model_38()\n    _maybe_retire_gemini_31_flash()\n',
                      source.replace('\r\n', '\n'))


if __name__ == '__main__':
    unittest.main()
