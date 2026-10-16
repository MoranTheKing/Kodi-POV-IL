"""SubSync's media-probe cache: one small file per entry, never one big file.

The old single subsync_probe_cache.json reached 11 MB and was parsed whole
about six times at the start of every episode. json.load never releases the
interpreter lock, so in QA Kodi each read held every other script for
0.12-0.15 s on a PC -- seconds on an Android box, where the "בחירת כתוביות"
button waited behind it.
"""

import importlib.util
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load_subsync():
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    ku.get_setting = lambda _k, default='': default
    lib = types.ModuleType('resources.lib')
    lib.__path__ = []
    lib.kodi_utils = ku
    pkg = types.ModuleType('resources')
    pkg.__path__ = []
    pkg.lib = lib
    with patch.dict(sys.modules, {'resources': pkg, 'resources.lib': lib,
                                  'resources.lib.kodi_utils': ku}):
        spec = importlib.util.spec_from_file_location('probe_split_subsync', LIB / 'subsync.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class ProbeCacheSplitTests(unittest.TestCase):
    def setUp(self):
        self.sub = _load_subsync()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.legacy = self.root / 'subsync_probe_cache.json'
        self.sub._probe_cache_path = lambda: str(self.legacy)
        self.folder = self.root / 'subsync_probe'

    def entry(self, n, ts=None):
        return {'pv': self.sub._PROBE_CACHE_VERSION, 'ts': ts or time.time(),
                'cues': [{'start': n, 'end': n + 900}]}

    def test_store_and_read_one_entry(self):
        self.assertTrue(self.sub._write_probe_cache('media:a', self.entry(1)))
        self.assertEqual(self.sub._read_probe_entry('media:a')['cues'][0]['start'], 1)
        self.assertIsNone(self.sub._read_probe_entry('media:b'))
        self.assertFalse(self.legacy.exists())
        self.assertEqual(len(list(self.folder.glob('*.json'))), 1)

    def test_a_lookup_parses_only_its_own_file(self):
        for n in range(5):
            self.sub._write_probe_cache('media:%d' % n, self.entry(n))
        loads = []
        real = json.load
        with patch.object(self.sub.json, 'load', side_effect=lambda f: loads.append(1) or real(f)):
            self.assertEqual(self.sub._read_probe_entry('media:3')['cues'][0]['start'], 3)
        self.assertEqual(len(loads), 1)

    def test_the_old_single_file_is_split_once_and_removed(self):
        old = {'media:x': self.entry(10, ts=1000.0), 'audio2:y': self.entry(20, ts=2000.0),
               'junk': 'not a dict'}
        self.legacy.write_text(json.dumps(old), encoding='utf-8')
        self.assertEqual(self.sub._read_probe_entry('audio2:y')['cues'][0]['start'], 20)
        self.assertFalse(self.legacy.exists())
        self.assertEqual(self.sub._read_probe_entry('media:x')['cues'][0]['start'], 10)
        self.assertIsNone(self.sub._read_probe_entry('junk'))
        # Migrated entries keep their age for pruning.
        self.assertAlmostEqual(os.path.getmtime(self.sub._probe_entry_path('media:x')), 1000.0, delta=2)

    def test_newer_entry_wins_over_a_stale_legacy_copy(self):
        self.sub._write_probe_cache('media:x', self.entry(99))
        self.legacy.write_text(json.dumps({'media:x': self.entry(1, ts=5.0)}), encoding='utf-8')
        self.assertEqual(self.sub._read_probe_entry('media:x')['cues'][0]['start'], 99)

    def test_the_cache_stays_bounded_keeping_the_newest(self):
        with patch.object(self.sub, '_MAX_PROBE_ENTRIES', 3):
            for n in range(6):
                self.sub._write_probe_cache('media:%d' % n, self.entry(n, ts=1000.0 + n))
        self.assertEqual(len(list(self.folder.glob('*.json'))), 3)
        self.assertIsNone(self.sub._read_probe_entry('media:0'))
        self.assertIsNotNone(self.sub._read_probe_entry('media:5'))

    def test_a_file_for_another_key_is_never_returned(self):
        self.sub._write_probe_cache('media:a', self.entry(1))
        path = self.sub._probe_entry_path('media:a')
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        doc['key'] = 'media:other'
        Path(path).write_text(json.dumps(doc), encoding='utf-8')
        self.assertIsNone(self.sub._read_probe_entry('media:a'))

    def test_no_reader_parses_the_whole_cache_anymore(self):
        src = (LIB / 'subsync.py').read_text(encoding='utf-8')
        self.assertNotIn('_read_probe_cache(', src)


if __name__ == '__main__':
    unittest.main()
