"""The timeout repair must survive earlier Windows patchers writing CRLF."""
import importlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_patcher_upgrade_path as harness
STOCK = Path(os.environ.get('POV_STOCK', '/nonexistent'))
REL = Path('resources/lib/indexers/tmdb_api.py')


def patch(home, stem):
    harness._install_stubs(str(home))
    mod = importlib.import_module('resources.lib.' + stem)
    mod.ensure_patched()
    return mod


class TimeoutTests(unittest.TestCase):
    def test_line_endings_and_existing_metadata_marker(self):
        for eol in (b'\n', b'\r\n'):
            with self.subTest(eol=eol), tempfile.TemporaryDirectory(prefix='meta-timeout-') as d:
                home = Path(d)
                target = home / 'addons/plugin.video.pov' / REL
                target.parent.mkdir(parents=True)
                before = b'# upstream\ntimeout = 3.05\ndef untouched(): return 7\n'.replace(b'\n', eol)
                target.write_bytes(before)
                mod = patch(home, 'pov_meta_blank_patcher')
                after = target.read_bytes()
                self.assertEqual(after, before.replace(b'timeout = 3.05', mod._TMDB_TIMEOUT_NEW.strip()))
                compile(after, str(target), 'exec')
                patch(home, 'pov_meta_blank_patcher')
                self.assertEqual(target.read_bytes(), after)
                # A device already carrying the metadata repair must still
                # receive the independent timeout repair on the next boot.
                metadata = target.with_name('metadata.py')
                metadata.write_text(mod.MARKER + '\n', encoding='utf-8')
                target.write_bytes(before)
                patch(home, 'pov_meta_blank_patcher')
                self.assertEqual(target.read_bytes(), after)

    def test_ambiguous_or_unknown_timeout_is_left_alone(self):
        for value in (b'\ntimeout = 3.05\n\ntimeout = 3.05\n', b'\ntimeout = 9.0\n'):
            with tempfile.TemporaryDirectory(prefix='meta-timeout-') as d:
                home = Path(d)
                target = home / 'addons/plugin.video.pov' / REL
                target.parent.mkdir(parents=True)
                target.write_bytes(value)
                patch(home, 'pov_meta_blank_patcher')
                self.assertEqual(target.read_bytes(), value)

    @unittest.skipUnless((STOCK / REL).is_file(), 'current POV tree not supplied for predecessor integration')
    def test_real_predecessor_chains(self):
        for predecessor in ('pov_combined_discover_patcher', 'pov_movie_networks_patcher'):
            with self.subTest(predecessor=predecessor), tempfile.TemporaryDirectory(prefix='meta-chain-') as d:
                home = Path(d)
                host = home / 'addons/plugin.video.pov'
                for rel in ('addon.xml', str(REL), 'resources/lib/indexers/metadata.py',
                            'resources/lib/menus/tmdb.py'):
                    dest = host / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(STOCK / rel, dest)
                target = host / REL
                patch(home, predecessor)
                after_predecessor = target.read_bytes()
                self.assertRegex(after_predecessor, rb'(?m)^timeout = 3\.05\r?$')
                mod = patch(home, 'pov_meta_blank_patcher')
                after = target.read_bytes()
                self.assertIn(mod._TMDB_TIMEOUT_NEW.strip(), after)
                compile(after, str(target), 'exec')
                eol = b'\r\n' if b'\r\n' in after_predecessor else b'\n'
                self.assertEqual(after, after_predecessor.replace(
                    mod._TMDB_TIMEOUT_OLD.replace(b'\n', eol),
                    mod._TMDB_TIMEOUT_NEW.replace(b'\n', eol), 1))
                patch(home, 'pov_meta_blank_patcher')
                self.assertEqual(target.read_bytes(), after)


if __name__ == '__main__':
    unittest.main()
