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
            self.assertEqual(code, 3, line)
            self.assertTrue(line.startswith('unavailable 6.10.07: official zip unusable'), line)
        self.assertEqual(json.loads(self.pin.read_text())['version'], '6.10.06')

    def test_a_failure_after_the_pin_was_written_restores_both_files(self):
        before = (self.pin.read_bytes(), self.upstream.read_bytes())
        with mock.patch.object(bump, 'set_upstream_pov', side_effect=ValueError('two pov lines')):
            code, _line = self.run_bump('6.10.07', pov_zip('6.10.07'))
        self.assertEqual(code, 2)
        self.assertEqual((self.pin.read_bytes(), self.upstream.read_bytes()), before)

    def test_a_beta_version_is_not_published(self):
        code, line = self.run_bump('6.11.0~beta1', pov_zip('6.11.0~beta1'))
        self.assertEqual(code, 2)
        self.assertIn('not a plain release version', line)

    def test_check_mode_reports_without_downloading(self):
        self.assertEqual(bump.pending(fetcher=lambda url: index('6.10.07')), ('6.10.06', '6.10.07'))
        self.assertEqual(bump.pending(fetcher=lambda url: index('6.10.06')), ('6.10.06', None))

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


class RepublishTests(unittest.TestCase):
    """Field (20 Oct 2026): POV 6.10.06 was replaced upstream under the same
    version, one Wizard hook lost its anchor and fresh installs stopped."""

    setUp = AutoBumpTests.setUp

    def check(self, data, verifier=lambda root, archive: print('audit ok'), latest='6.10.06'):
        return bump.republish_check(fetcher=lambda url: index(latest),
                                    getter=lambda url: data, verifier=verifier)

    def test_same_zip_is_quiet(self):
        data = pov_zip('6.10.06')
        self.pin.write_text(json.dumps(bump.pin_for('6.10.06', data, 'u')), 'utf-8')
        self.assertEqual(self.check(data, verifier=mock.Mock(side_effect=AssertionError)),
                         (0, 'same 6.10.06'))

    def test_republished_zip_is_audited_and_the_pin_stays(self):
        before = self.pin.read_bytes()
        data = pov_zip('6.10.06', extra={'plugin.video.pov/new.py': 'y = 2'})
        seen = []
        code, line = self.check(data, verifier=lambda root, archive: (
            seen.append(json.loads(self.pin.read_text('utf-8'))['sha256']), print('audit ok')))
        sha = bump.hashlib.sha256(data).hexdigest()
        self.assertEqual((code, line), (0, 'republished 6.10.06 %s fits: audit ok' % sha[:12]))
        self.assertEqual(seen, [sha])                  # the audit ran on the new zip
        self.assertEqual(self.pin.read_bytes(), before)  # and the pin is back

    def test_republished_zip_that_breaks_a_patch_is_reported(self):
        before = self.pin.read_bytes()
        def broken(root, archive):
            raise ValueError("Host patch audit failed: {'anchor_missing': 1}")
        code, line = self.check(pov_zip('6.10.06'), verifier=broken)
        self.assertEqual(code, 2)
        self.assertIn('blocked: Host patch audit failed', line)
        self.assertTrue(line.startswith('republished 6.10.06 '))
        self.assertEqual(self.pin.read_bytes(), before)

    def test_newer_version_is_left_to_the_pin_job(self):
        self.assertEqual(self.check(b'', verifier=mock.Mock(side_effect=AssertionError),
                                    latest='6.10.07'), (0, 'newer 6.10.07'))

    def test_unreachable_zip_is_transient(self):
        def down(url):
            raise OSError('timeout')
        code, line = bump.republish_check(fetcher=lambda url: index('6.10.06'), getter=down)
        self.assertEqual(code, 3)
        self.assertTrue(line.startswith('unavailable 6.10.06'))


if __name__ == '__main__':
    unittest.main()
