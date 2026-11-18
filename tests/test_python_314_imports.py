"""MoranSubs 0.3.96: nothing the add-ons ship calls a function Python 3.14 removed.

Nov 2026: the build's test run failed the day the build machines' image moved to Ubuntu 26 -- the subtitle
engine's title parser called pkgutil.find_loader, removed in Python 3.14, and every test that loads the engine
failed at that import. The same import fails in a Kodi that runs on a system Python 3.14.
"""
import importlib.util
import re
import sys
import unittest
import warnings
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ('service.subtitles.kodipovilai', 'plugin.program.kodipovilwizard')
# removed in Python 3.12-3.14 (each was a working call on the Python the build was written on)
GONE = (r'\bpkgutil\.(find_loader|get_loader)\(', r'\bimp\.(load_source|load_module|find_module|reload)\(', r'^\s*import imp\s*$',
        r'\bast\.(Str|Num|Bytes|NameConstant|Ellipsis)\b', r'^\s*(from|import) distutils\b', r'\basyncio\.get_child_watcher\(',
        r'\bimportlib\.abc\.(ResourceReader|Traversable)\b', r'\bsqlite3\.(OptimizedUnicode|enable_shared_cache)\b',
        r'\bunittest\.makeSuite\(', r'\bdatetime\.utcnow\(\)\.utcfromtimestamp')


class Python314Tests(unittest.TestCase):
    def test_no_shipped_module_calls_a_removed_function(self):
        found = []
        for folder in SHIPPED:
            for path in sorted((ROOT / folder).rglob('*.py')):
                text = path.read_text('utf-8', errors='replace')
                for pattern in GONE:
                    for match in re.finditer(pattern, text, re.M):
                        line = text.count('\n', 0, match.start()) + 1
                        found.append('%s:%d %s' % (path.relative_to(ROOT).as_posix(), line, match.group(0).strip()))
        self.assertEqual(found, [])

    def test_the_title_parser_loads_and_parses_without_pkgutil(self):
        folder = ROOT / 'service.subtitles.kodipovilai/resources/lib/subs_engine/_libs/parse_torrent_title'
        spec = importlib.util.spec_from_file_location('ptn_314_test', folder / '__init__.py', submodule_search_locations=[str(folder)])
        module = importlib.util.module_from_spec(spec)

        class NoLookup(object):
            def __getattr__(self, name):
                raise AttributeError("module 'pkgutil' has no attribute %r" % name)      # what Python 3.14 answers
        loaded = dict((name, sys.modules[name]) for name in list(sys.modules) if name.startswith('ptn_314_test'))
        with mock.patch.dict(sys.modules, dict(loaded, ptn_314_test=module, pkgutil=NoLookup())), warnings.catch_warnings():
            warnings.simplefilter('ignore', SyntaxWarning)       # (upstream's patterns are not raw strings)
            spec.loader.exec_module(module)
            self.assertIs(module.re, re, "the standard 're', what the lookup always ended with on Python 3")
            parsed = module.parse('The.Show.S02E05.1080p.WEB-DL.x264-GROUP')
        self.assertEqual((parsed.get('season'), parsed.get('episode'), parsed.get('resolution')), (2, 5, '1080p'))


if __name__ == '__main__':
    unittest.main()
