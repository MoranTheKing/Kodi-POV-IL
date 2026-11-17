"""Keep unchanged artwork cheap and leave old artwork intact on copy errors."""

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'plugin.program.orderfavourites-hebrew/resources/lib/media_installer.py'
spec = importlib.util.spec_from_file_location('media_installer', MODULE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class _VFS:
    def __init__(self, media):
        self.media = media
        self.calls = 0
        self.fail = False

    def translatePath(self, _path):
        return str(self.media)

    def copy(self, src, dst):
        self.calls += 1
        if self.fail:
            return False
        shutil.copyfile(src, dst)
        return True


class MediaInstallerTests(unittest.TestCase):
    def test_repeat_run_changed_same_size_and_failed_copy(self):
        addon = MODULE.parents[2]
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw)
            vfs = _VFS(media)
            asset_count = sum(1 for path in (addon / 'resources/media').rglob('*')
                              if path.is_file())
            original = installer.xbmcvfs
            installer.xbmcvfs = vfs
            try:
                self.assertEqual(installer._install_assets(str(addon)), asset_count)
                self.assertEqual(installer._install_assets(str(addon)), 0)
                self.assertEqual(vfs.calls, asset_count)

                target = media / 'povil_icons/My_Movies_MDBList.png'
                expected = target.read_bytes()
                target.write_bytes(b'X' * len(expected))
                self.assertEqual(installer._install_assets(str(addon)), 1)
                self.assertEqual(target.read_bytes(), expected)

                target.write_bytes(b'Y' * len(expected))
                vfs.fail = True
                self.assertEqual(installer._install_assets(str(addon)), 0)
                self.assertEqual(target.read_bytes(), b'Y' * len(expected))
                self.assertEqual(list(media.rglob('.povil-media-*')), [])
            finally:
                installer.xbmcvfs = original

    def test_an_unchanged_asset_is_not_read_again(self):
        """Every Kodi start runs this: what did not change costs two stats, not two reads."""
        addon = MODULE.parents[2]
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw)
            original, compare = installer.xbmcvfs, installer._same_file
            installer.xbmcvfs = _VFS(media)
            reads = []
            installer._same_file = lambda src, dst: reads.append(dst) or compare(src, dst)
            try:
                count = installer._install_assets(str(addon))
                self.assertTrue((media / 'povil_media.stamp').is_file())
                del reads[:]
                self.assertEqual(installer._install_assets(str(addon)), 0)
                self.assertEqual(reads, [], 'nothing changed: no file is opened')

                # a copy that was touched since is compared again, and only that one
                target = media / 'povil_icons/My_Movies_MDBList.png'
                stat = target.stat()
                os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2000000000))
                self.assertEqual(installer._install_assets(str(addon)), 0)
                self.assertEqual(reads, [str(target)])
                del reads[:]
                self.assertEqual(installer._install_assets(str(addon)), 0)
                self.assertEqual(reads, [], 'and it is trusted again once its bytes were compared')

                # a copy that is gone is put back
                target.unlink()
                self.assertEqual(installer._install_assets(str(addon)), 1)
                self.assertTrue(target.is_file())

                # no stamp (an older version's install, a wiped folder): one full comparison
                (media / 'povil_media.stamp').unlink()
                del reads[:]
                self.assertEqual(installer._install_assets(str(addon)), 0)
                self.assertEqual(len(reads), count)
                self.assertTrue((media / 'povil_media.stamp').is_file())

                # a damaged stamp is no stamp
                (media / 'povil_media.stamp').write_text('{not json')
                del reads[:]
                self.assertEqual(installer._install_assets(str(addon)), 0)
                self.assertEqual(len(reads), count)
            finally:
                installer.xbmcvfs, installer._same_file = original, compare

    def test_a_failed_copy_is_not_stamped_as_done(self):
        addon = MODULE.parents[2]
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw)
            vfs = _VFS(media)
            original = installer.xbmcvfs
            installer.xbmcvfs = vfs
            try:
                installer._install_assets(str(addon))
                target = media / 'povil_icons/My_Movies_MDBList.png'
                expected = target.read_bytes()
                target.write_bytes(b'Z' * len(expected))
                stat = target.stat()
                os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2000000000))
                vfs.fail = True
                self.assertEqual(installer._install_assets(str(addon)), 0)
                vfs.fail = False
                self.assertEqual(installer._install_assets(str(addon)), 1, 'the next start tries again')
                self.assertEqual(target.read_bytes(), expected)
            finally:
                installer.xbmcvfs = original

    def test_the_strict_gate_heals_a_copy_the_stamp_calls_unchanged(self):
        """Bytes gone bad under the same size and time: the per-start pass cannot see it, the gate must."""
        addon = MODULE.parents[2]
        with tempfile.TemporaryDirectory() as raw:
            media = Path(raw)
            original = installer.xbmcvfs
            installer.xbmcvfs = _VFS(media)
            try:
                installer._install_assets(str(addon))
                target = media / 'povil_icons/My_Movies_MDBList.png'
                expected = target.read_bytes()
                stat = target.stat()
                target.write_bytes(b'\0' * len(expected))
                os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                self.assertEqual(installer._install_assets(str(addon)), 0, 'the figures say unchanged')
                self.assertEqual(installer._install_assets(str(addon), trust_stamp=False), 1)
                self.assertEqual(target.read_bytes(), expected)
            finally:
                installer.xbmcvfs = original
        source = MODULE.read_text('utf-8')
        gate = source[source.index('def install_and_verify_global_media_assets'):]
        self.assertIn('_install_assets(addon_path, trust_stamp=False)', gate[:gate.index('def install_global_media_assets')])

    def test_the_ratings_service_starts_without_its_web_stack(self):
        """It starts under every skin and serves one: requests and sqlite wait for the first rating."""
        source = (ROOT / 'script.fentastic.helper/resources/lib/service.py').read_text('utf-8')
        head = source[:source.index('class RatingsService')]
        self.assertNotIn('MDbList', head)
        self.assertIn('from modules.MDbList import MDbListAPI', source[source.index('def set_ratings'):])


if __name__ == '__main__':
    unittest.main()
