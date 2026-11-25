"""Wizard 0.5.52: the Trakt sign-in recovery fits POV 6.11.04.

POV 6.11.04 dropped trakt_sync_activities' monitor argument; the patch that hooks in right before that
function (pov_trakt_reauth_recovery) lost its anchor, and the pin job held every device on 6.11.03
(issue 442, 24 Nov 2026). The hook never used the argument: both signatures are anchors.
"""
import importlib.util
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WIZ = ROOT / 'plugin.program.kodipovilwizard'
REL = 'resources/lib/indexers/trakt_api.py'
BODY = ("from modules.kodi_utils import get_setting\n"
        "def trakt_sync_activities_thread(*args, **kwargs):\n"
        "\tpass\n\n"
        "%s\n"
        "\treturn 'no account'\n")
OLD = 'def trakt_sync_activities(force_update=False, init_callback=None, monitor=None):'
NEW = 'def trakt_sync_activities(force_update=False, init_callback=None):'


class TraktReauthAnchor(unittest.TestCase):
    def run_engine(self, signature):
        entry = [e for e in runpy.run_path(str(WIZ / 'resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
                 if e['id'] == 'pov_trakt_reauth_recovery']
        self.assertEqual(len(entry), 1)
        temp = Path(tempfile.mkdtemp(prefix='trakt-anchor-'))
        target = temp / REL
        target.parent.mkdir(parents=True)
        target.write_text(BODY % signature, encoding='utf-8')
        xbmc = types.ModuleType('xbmc')
        for index, name in enumerate(('LOGDEBUG', 'LOGINFO', 'LOGWARNING', 'LOGERROR')):
            setattr(xbmc, name, index)
        stubs = {'xbmc': xbmc,
                 'xbmcaddon': types.SimpleNamespace(Addon=lambda: types.SimpleNamespace(getSetting=lambda k: '')),
                 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p),
                 'resources.libs.common': types.SimpleNamespace(
                     logging=types.SimpleNamespace(log=lambda *a, **k: None))}
        with patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location('trakt_anchor_engine', WIZ / 'resources/libs/patch_engine.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            class Engine(module.PatchEngine):
                @staticmethod
                def _resolve_paths(addon_id, filename):
                    return str(temp), str(temp / filename)

            first, second = Engine(entry).run(), Engine(entry).run()
        text = target.read_text(encoding='utf-8')
        return first, second, text

    def test_pov_6_11_03_and_6_11_04_both_take_the_hook(self):
        for signature in (OLD, NEW):
            first, second, text = self.run_engine(signature)
            self.assertEqual((first['applied'], first['anchor_missing']), (1, 0), signature)
            self.assertEqual(second['skipped_current'], 1, signature)
            self.assertLess(text.index('pov_trakt_reauth.run(sys.modules[__name__])'), text.index(signature))
            compile(text, REL, 'exec')


if __name__ == '__main__':
    unittest.main()
