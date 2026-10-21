"""The shared-HTTP proxy is enabled by session.py's digest; POV's callers are audited.

Wizard 0.4.71 dropped the hand-kept POV version list from pov_http_session:
the digest pins the session module, and the release automation now moves
the POV pin by itself. How POV's other files use that module is not covered
by the digest, so the pin verifier (verify_pov_patches.audit_session_callers)
stops a POV whose callers use the proxy in a shape it does not imitate.
"""
import hashlib
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = runpy.run_path(str(ROOT / '.github/scripts/verify_pov_patches.py'))
audit = VERIFY['audit_session_callers']
FIXTURE = ROOT / 'tests/fixtures/http_session/session.py'

OK_CALLER = '''from modules.session import session, HTTPAdapter, Retry
retry = Retry(total=None, status=1, status_forcelist=(429,), backoff_factor=1)
session.mount('https://api', HTTPAdapter(pool_maxsize=100, max_retries=retry))
session.mount('https://other', HTTPAdapter(max_retries=Retry(total=2)))

def get(url):
    try: return session.request('get', url, timeout=5)
    except session.CUSTOM_ERRORS: return None

def again(response):
    return session.send(response.request)
'''
OK_HTTP = '''from modules.session import http
def fetch(url):
    return http.request('GET', url)
'''


class SessionCallerAudit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.host = Path(tmp.name)
        modules = self.host / 'resources/lib/modules'
        modules.mkdir(parents=True)
        (modules / '__init__.py').write_text('')
        (modules / 'session.py').write_bytes(FIXTURE.read_bytes())
        self.digest = hashlib.sha256(FIXTURE.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        self.indexers = self.host / 'resources/lib/indexers'
        self.indexers.mkdir()
        (self.indexers / 'tmdb_api.py').write_text(OK_CALLER)
        (self.indexers / 'imdb_api.py').write_text(OK_HTTP)

    def problems(self, extra=None):
        if extra is not None:
            (self.indexers / 'new_api.py').write_text(extra)
        return audit(self.host, self.digest)

    def test_the_shapes_pov_uses_pass(self):
        self.assertEqual(self.problems(), [])

    def test_the_fixture_is_the_wizards_verified_session(self):
        self.assertEqual(self.digest, VERIFY['_session_digest'](ROOT))

    def test_the_real_digest_check_switches_the_audit_off(self):
        # A changed session.py keeps the proxy off on devices: nothing to audit.
        self.assertEqual(audit(self.host, '0' * 64), [])
        (self.indexers / 'bad.py').write_text('from modules.session import session\nx = session\n')
        self.assertEqual(audit(self.host, '0' * 64), [])
        self.assertTrue(audit(self.host, self.digest))

    def test_unsupported_shapes_stop_the_pin(self):
        cases = {
            'from modules.session import session\nclient = session\n': 'session other than',
            'from modules.session import session\nwith session: pass\n': 'session other than',
            'from modules.session import http\nuse(http)\n': 'http other than',
            'from modules.session import HTTPAdapter\nadapter = HTTPAdapter()\n': 'outside session.mount',
            'from modules.session import HTTPAdapter\nisinstance(x, HTTPAdapter)\n': 'other than by calling',
            'from modules.session import Retry\nclass R(Retry): pass\n': 'other than by calling',
            'from modules.session import http, Retry\nhttp.request("GET", u, retries=Retry(total=1))\n':
                'outside HTTPAdapter',
            'from modules.session import http, Retry\nr = Retry(total=1)\nhttp.request("GET", u, retries=r)\n':
                'Retry(...) value outside',
            'import modules.session\n': 'imports the module',
            'from session import session as s\nf(s)\n': 'session other than',
            'from modules import session as s\nisinstance(a, s.HTTPAdapter)\n': 'imports the module session',
            'from modules.session import *\nisinstance(a, Retry)\n': 'imports *',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                found = self.problems(source)
                self.assertEqual(len(found), 1, found)
                self.assertIn(expected, found[0])
                self.assertTrue(found[0].startswith('resources/lib/indexers/new_api.py:'), found[0])

    def test_relative_imports_inside_the_modules_package(self):
        # 6.10.19 made `modules` a regular package: `from .session import`
        # is the likeliest refactor, and it reaches the proxy too.
        modules = self.host / 'resources/lib/modules'
        for source, expected in {
                'from .session import session\nx = session\n': 'session other than',
                'from . import session\nisinstance(a, session.Retry)\n': 'imports the module session',
                'from .session import session, HTTPAdapter\nsession.mount("u", HTTPAdapter())\n': None}.items():
            with self.subTest(source=source):
                (modules / 'helper.py').write_text(source)
                found = audit(self.host, self.digest)
                if expected is None:
                    self.assertEqual(found, [])
                else:
                    self.assertEqual(len(found), 1, found)
                    self.assertIn(expected, found[0])
                    self.assertTrue(found[0].startswith('resources/lib/modules/helper.py:'), found[0])
        # one level up from a sibling package resolves to modules/session.py too
        (modules / 'helper.py').unlink()
        (self.indexers / 'up.py').write_text('from ..modules.session import http\nf(http)\n')
        found = audit(self.host, self.digest)
        self.assertEqual(len(found), 1, found)
        self.assertIn('http other than', found[0])


if __name__ == '__main__':
    unittest.main()
