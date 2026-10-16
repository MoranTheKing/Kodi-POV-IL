"""The clean-host POV pin follows upstream POV, but only onto a POV our patches fit.

A pin behind the POV that Kodi already installed stops every legacy device's
move to the modular build (field log 16 Oct 2026: "Installed POV is newer than
the pinned clean host; refusing downgrade").
"""

import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('auto_bump_pov_pin', ROOT / 'tools' / 'auto_bump_pov_pin.py')
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


def pov_zip(version, addon_id='plugin.video.pov', extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('plugin.video.pov/addon.xml',
                   '<addon id="%s" version="%s" name="POV"></addon>' % (addon_id, version))
        z.writestr('plugin.video.pov/resources/lib/entry.py', 'x = 1\n')
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    return buf.getvalue()


def index(version):
    return '<addons><addon id="plugin.video.pov" version="%s"/></addons>' % version


class AutoBumpTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.pin = self.dir / 'pin.json'
        self.upstream = self.dir / 'UPSTREAM_VERSIONS.txt'
        self.pin.write_bytes(json.dumps(bump.pin_for('6.10.06', b'old', 'https://kodifitzwell.github.io/repo/'
                                                     'plugin.video.pov/plugin.video.pov-6.10.06.zip'),
                                        indent=2).encode().replace(b'\n', b'\r\n') + b'\r\n')
        self.upstream.write_bytes(b'# header\r\nplugin.video.pov: 6.10.06\r\nplugin.video.otaku: 5.3.3\r\n')
        for name, value in (('PIN', self.pin), ('UPSTREAM', self.upstream)):
            patcher = mock.patch.object(bump, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.out = self.dir / 'out'

    def run_bump(self, latest, data, verifier=lambda root, archive: None):
        return bump.run(self.out, fetcher=lambda url: index(latest),
                        getter=lambda url: data, verifier=verifier)

    def test_nothing_to_do_when_the_pin_is_current(self):
        code, line = self.run_bump('6.10.06', pov_zip('6.10.06'))
        self.assertEqual((code, line), (0, 'current 6.10.06'))
        self.assertFalse(self.out.exists())

    def test_a_newer_pov_that_our_patches_fit_moves_the_pin(self):
        data = pov_zip('6.10.07')
        seen = []
        code, line = self.run_bump('6.10.07', data,
                                   verifier=lambda root, archive: seen.append(
                                       (json.loads(self.pin.read_text())['version'], archive)))
        self.assertEqual(code, 0)
        self.assertTrue(line.startswith('bumped 6.10.06 6.10.07 '), line)
        self.assertEqual(seen, [('6.10.07', data)])      # verified against the NEW pin
        pin = json.loads(self.pin.read_text())
        self.assertEqual(pin['version'], '6.10.07')
        self.assertEqual(pin['size'], len(data))
        self.assertTrue(pin['zip'].endswith('/addons-latest/official-plugin.video.pov-6.10.07.zip'))
        self.assertIn(b'\r\n', self.pin.read_bytes())    # line endings kept
        self.assertEqual(self.upstream.read_bytes(),
                         b'# header\r\nplugin.video.pov: 6.10.07\r\nplugin.video.otaku: 5.3.3\r\n')
        self.assertEqual((self.out / 'official-plugin.video.pov-6.10.07.zip').read_bytes(), data)

    def test_a_pov_our_patches_do_not_fit_leaves_everything_untouched(self):
        before = (self.pin.read_bytes(), self.upstream.read_bytes())

        def fail(root, archive):
            raise ValueError("Host patch audit failed: {'anchor_missing': 3}")
        code, line = self.run_bump('6.10.07', pov_zip('6.10.07'), verifier=fail)
        self.assertEqual(code, 2)
        self.assertIn('patches do not fit', line)
        self.assertEqual((self.pin.read_bytes(), self.upstream.read_bytes()), before)
        self.assertFalse(self.out.exists())

    def test_a_package_that_is_not_that_pov_is_refused(self):
        for data in (pov_zip('6.10.08'), pov_zip('6.10.07', addon_id='plugin.video.other'),
                     pov_zip('6.10.07', extra={'evil/../x.py': ''}), b'<html>404</html>'):
            code, line = self.run_bump('6.10.07', data)
            self.assertEqual(code, 2, line)
            self.assertIn('official zip unusable', line)
        self.assertEqual(json.loads(self.pin.read_text())['version'], '6.10.06')

    def test_an_older_upstream_never_moves_the_pin_back(self):
        code, line = self.run_bump('6.10.05', pov_zip('6.10.05'))
        self.assertEqual((code, line), (0, 'current 6.10.06'))

    def test_the_new_pin_passes_the_manifest_generator_validation(self):
        gen_spec = importlib.util.spec_from_file_location('gen_manifest_for_bump',
                                                          ROOT / '.github' / 'scripts' / 'gen_manifest.py')
        gen = importlib.util.module_from_spec(gen_spec)
        gen_spec.loader.exec_module(gen)
        self.run_bump('6.10.07', pov_zip('6.10.07'))
        with mock.patch.object(gen, 'POV_HOST_MIGRATION', str(self.pin)):
            self.assertEqual(gen._pov_host_migration()['version'], '6.10.07')


if __name__ == '__main__':
    unittest.main()
