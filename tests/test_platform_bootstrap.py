"""Fresh platform installers must not carry a legacy profile or native deps."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

spec = importlib.util.spec_from_file_location('platform_seed',
    Path(__file__).resolve().parents[1] / '.github/scripts/build_platform_bootstrap.py')
seed = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed)


class PlatformBootstrapTests(unittest.TestCase):
    def fixture(self, directory, platform='', binary=False):
        source = Path(directory) / 'legacy.zip'; wizard = Path(directory) / 'wizard.zip'
        with ZipFile(source, 'w') as z:
            for aid in seed.DEPENDENCIES:
                z.writestr('addons/' + aid + '/addon.xml',
                    '<addon><extension point="xbmc.addon.metadata">' + platform + '</extension></addon>')
                z.writestr('addons/' + aid + '/lib/module.py', 'value=1')
            z.writestr('userdata/accounts.xml', 'must remain private')
            z.writestr('addons/plugin.video.pov/legacy.py', 'must not be installed')
            if binary: z.writestr('addons/script.module.requests/native.dll', b'not portable')
        with ZipFile(wizard, 'w') as z:
            z.writestr('plugin.program.kodipovilwizard/addon.xml', '<addon version="0.4.7"/>')
            for name in ('modular_updater.py', 'fresh_install.py'):
                z.writestr('plugin.program.kodipovilwizard/resources/libs/' + name, '# current')
        return source, wizard, Path(directory) / 'bootstrap.zip'

    def test_minimal_seed_accepts_kodi_default_platform_and_excludes_userdata(self):
        with tempfile.TemporaryDirectory() as directory:
            source, wizard, output = self.fixture(directory)
            seed.build(source, wizard, '0.4.7', output)
            with ZipFile(output) as z:
                self.assertEqual(z.testzip(), None)
                self.assertEqual({n for n in z.namelist() if n.startswith('userdata/')},
                    {'userdata/guisettings.xml', 'userdata/kodipovil.modular_install_started'})
                self.assertFalse(any(n.startswith('addons/plugin.video.') for n in z.namelist()))

    def test_rejects_native_or_platform_specific_dependencies(self):
        for platform, binary in [('<platform>windows</platform>', False), ('', True)]:
            with self.subTest(platform=platform, binary=binary), tempfile.TemporaryDirectory() as directory:
                source, wizard, output = self.fixture(directory, platform, binary)
                with self.assertRaises(ValueError): seed.build(source, wizard, '0.4.7', output)


if __name__ == '__main__': unittest.main()
