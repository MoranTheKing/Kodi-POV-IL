"""Initial-load optimizations keep repair scans and child checks available."""
import ast
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class InitialLoadTests(unittest.TestCase):
    def test_startup_skips_only_the_redundant_local_scan_manual_check_retains_it(self):
        source = ast.parse((ROOT/'plugin.program.kodipovilwizard/resources/libs/db.py').read_text('utf8'))
        function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name=='forceUpdate')
        commands = []
        namespace = {'CONFIG':types.SimpleNamespace(FORCEUPDATEFAST_ONSTARTUP_NOTIFY='false'),
                     'xbmc':types.SimpleNamespace(executebuiltin=commands.append)}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<startup scan>','exec'), namespace)
        namespace['forceUpdate'](startup=True)
        self.assertEqual(commands,['UpdateAddonRepos()'])
        commands.clear()
        namespace['forceUpdate']()
        self.assertEqual(commands,['UpdateAddonRepos()','UpdateLocalAddons()'])

    def test_adult_guard_import_has_no_xml_parser_dependency(self):
        source = ast.parse((ROOT/'plugin.program.kodipovilwizard/resources/libs/patches/profile_age_guard.py').read_text('utf8'))
        top_imports = [n for n in source.body if isinstance(n,(ast.Import,ast.ImportFrom))]
        self.assertFalse(any('xml' in ast.unparse(n) for n in top_imports))
        locks = next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='locks_ready')
        self.assertTrue(any(isinstance(n,ast.Import) and n.names[0].name=='xml.etree.ElementTree'
                            for n in ast.walk(locks)))

    def test_all_architecture_artwork_policy_keeps_custom_values_and_existing_cache(self):
        path = ROOT/'service.subtitles.kodipovilai/resources/lib/kodi_32bit_artwork.py'
        spec = importlib.util.spec_from_file_location('build_artwork_test',path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cache = root/'Thumbnails/a/keep.jpg'
            cache.parent.mkdir(parents=True); cache.write_bytes(b'cached-user-image')
            settings = root/'advancedsettings.xml'
            original = b'<advancedsettings>\r\n<!-- custom comment --><imageres>9999</imageres><fanartres>1080</fanartres></advancedsettings>\r\n'
            settings.write_bytes(original)
            # Legacy callers still opt into the old architecture-specific API.
            self.assertEqual(module.ensure_optimized(str(settings),is_32bit=False),'not_32bit')
            self.assertEqual(settings.read_bytes(),original)
            self.assertEqual(module.ensure_build_default(str(settings)),'patched')
            self.assertEqual(settings.read_bytes(),original.replace(b'9999',b'720'))
            self.assertEqual(module.ensure_build_default(str(settings)),'already_optimized')
            self.assertEqual(cache.read_bytes(),b'cached-user-image')
            custom = original.replace(b'9999',b'1440')
            settings.write_bytes(custom)
            self.assertEqual(module.ensure_build_default(str(settings)),'custom_preserved')
            self.assertEqual(settings.read_bytes(),custom)
            broken = b'<advancedsettings><imageres>9999</advancedsettings>'
            settings.write_bytes(broken)
            self.assertEqual(module.ensure_build_default(str(settings)),'invalid_xml')
            self.assertEqual(settings.read_bytes(),broken)


if __name__ == '__main__': unittest.main()
