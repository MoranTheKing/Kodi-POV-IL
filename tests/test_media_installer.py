"""Keep unchanged artwork cheap and leave old artwork intact on copy errors."""

import importlib.util
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


if __name__ == '__main__':
    unittest.main()
