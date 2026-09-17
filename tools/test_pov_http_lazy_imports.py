#!/usr/bin/env python3
"""Prove POV's catalogue HTTP stack stays cold until a cache miss.

The test is behavioural: it executes the generated proxies against a fake
``requests`` module, verifies that no Session exists while a cache hit would
be served, and then verifies the original retry/header/mount setup at the
first live call.  A deliberately eager mutant must fail that same property.
"""

import ast
import importlib.util
import io
import os
import sys
import tempfile
import types


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
PATCHER = os.path.join(LIB, 'pov_http_lazy_import_patcher.py')
SERVICE = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                       'service.py')

spec = importlib.util.spec_from_file_location('http_lazy_test', PATCHER)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

FAIL = []


def check(label, condition, detail=''):
    print('{0:4} {1}{2}'.format(
        'ok' if condition else 'FAIL', label,
        (' -- ' + detail) if detail and not condition else ''))
    if not condition:
        FAIL.append(label)


def host_source(kind, eol='\n'):
    stock = patcher._STOCK_SESSIONS[kind]
    source = (
        'import json\n'
        'import requests\n'
        'from threading import Thread\n'
        'from modules import kodi_utils\n\n'
        + stock + '\n\n'
        'def cached_or_live(cache):\n'
        '\tif cache is not None:\n'
        '\t\treturn cache\n'
        "\treturn session.get('https://example.invalid').json()\n"
        '\n'
        'def catches_request_error():\n'
        '\ttry:\n'
        "\t\treturn session.get('https://example.invalid')\n"
        '\texcept requests.RequestException:\n'
        '\t\treturn None\n')
    return source.replace('\n', eol)


print('=== narrow rewrite ===')
for kind in ('tmdb', 'trakt'):
    with tempfile.TemporaryDirectory(prefix='pov-http-lazy-') as folder:
        path = os.path.join(folder, kind + '_api.py')
        with io.open(path, 'w', encoding='utf-8', newline='') as handle:
            handle.write(host_source(kind))
        first = patcher._patch_file(path, kind)
        once = open(path, 'rb').read()
        second = patcher._patch_file(path, kind)
        twice = open(path, 'rb').read()
        text = once.decode('utf-8')
        tree = ast.parse(text)
        eager_requests = [
            node for node in tree.body
            if isinstance(node, ast.Import)
            and any(alias.name == 'requests' for alias in node.names)]
        check(kind + ' exact stock shape patches', first == 'patched', first)
        check(kind + ' patched module compiles',
              bool(compile(text, path, 'exec')))
        check(kind + ' marker appears exactly once',
              text.count(patcher.MARKER) == 1)
        check(kind + ' has no eager top-level requests import',
              not eager_requests, repr(eager_requests))
        check(kind + ' installs one lazy session proxy',
              text.count('session = _PovLazySession()') == 1)
        check(kind + ' second pass is byte-idempotent',
              second == 'unchanged' and once == twice, second)


with tempfile.TemporaryDirectory(prefix='pov-http-unknown-') as folder:
    path = os.path.join(folder, 'tmdb_api.py')
    unknown = host_source('tmdb').replace('pool_maxsize=100',
                                          'pool_maxsize=101')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(unknown)
    before = open(path, 'rb').read()
    status = patcher._patch_file(path, 'tmdb')
    check('an unknown upstream session shape is refused intact',
          status == 'unmatched' and open(path, 'rb').read() == before,
          status)


with tempfile.TemporaryDirectory(prefix='pov-http-phantom-') as folder:
    path = os.path.join(folder, 'tmdb_api.py')
    phantom = patcher.MARKER + '\n' + host_source('tmdb')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(phantom)
    before = open(path, 'rb').read()
    status = patcher._patch_file(path, 'tmdb')
    check('a quoted/stranded current marker cannot report false success',
          status == 'unmatched' and open(path, 'rb').read() == before,
          status)


with tempfile.TemporaryDirectory(prefix='pov-http-stranded-') as folder:
    path = os.path.join(folder, 'trakt_api.py')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(host_source('trakt'))
    patcher._patch_file(path, 'trakt')
    broken = io.open(path, encoding='utf-8').read().replace(
        'session = _PovLazySession()', 'session = None')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(broken)
    before = open(path, 'rb').read()
    status = patcher._patch_file(path, 'trakt')
    check('a stranded proxy block cannot report false success',
          status == 'unmatched' and open(path, 'rb').read() == before,
          status)


with tempfile.TemporaryDirectory(prefix='pov-http-mutated-block-') as folder:
    path = os.path.join(folder, 'tmdb_api.py')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(host_source('tmdb'))
    patcher._patch_file(path, 'tmdb')
    broken = io.open(path, encoding='utf-8').read().replace(
        '\t\t\t\t\tself._session = _session\n', '', 1)
    compile(broken, path, 'exec')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(broken)
    before = open(path, 'rb').read()
    status = patcher._patch_file(path, 'tmdb')
    check('a compile-valid mutation inside the generated block is refused',
          status == 'unmatched' and open(path, 'rb').read() == before,
          status)


with tempfile.TemporaryDirectory(prefix='pov-http-crlf-') as folder:
    path = os.path.join(folder, 'trakt_api.py')
    with open(path, 'wb') as handle:
        handle.write(host_source('trakt', '\r\n').encode('utf-8'))
    status = patcher._patch_file(path, 'trakt')
    after = open(path, 'rb').read()
    check('a CRLF host module patches successfully',
          status == 'patched', status)
    check('the rewrite preserves CRLF without mixed line endings',
          after.count(b'\r\n') == after.count(b'\n'))


print('\n=== marker upgrade ===')
with tempfile.TemporaryDirectory(prefix='pov-http-upgrade-') as folder:
    path = os.path.join(folder, 'tmdb_api.py')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(host_source('tmdb'))
    first = patcher._patch_file(path, 'tmdb')
    old_marker = patcher.MARKER
    patcher.MARKER = old_marker.replace('_v1', '_v2')
    try:
        upgraded = patcher._patch_file(path, 'tmdb')
        upgraded_text = io.open(path, encoding='utf-8').read()
        check('an older generated block upgrades in place',
              first == 'patched' and upgraded == 'patched'
              and patcher.MARKER in upgraded_text
              and old_marker not in upgraded_text
              and upgraded_text.count('session = _PovLazySession()') == 1,
              '{0}/{1}'.format(first, upgraded))
        check('the upgraded module still compiles',
              bool(compile(upgraded_text, path, 'exec')))
    finally:
        patcher.MARKER = old_marker


class FakeHeaders(dict):
    pass


class FakeSession:
    created = 0
    instances = []

    def __init__(self):
        type(self).created += 1
        type(self).instances.append(self)
        self.headers = FakeHeaders()
        self.mounts = []
        self.calls = []

    def mount(self, url, adapter):
        self.mounts.append((url, adapter))

    def get(self, *args, **kwargs):
        self.calls.append(('get', args, kwargs))
        return ('response', args, kwargs)

    def request(self, *args, **kwargs):
        self.calls.append(('request', args, kwargs))
        return ('response', args, kwargs)


class FakeRetry:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAdapter:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeRequestException(Exception):
    pass


def execute_generated(kind, eager=False):
    fake = types.ModuleType('requests')
    fake.Session = FakeSession
    fake.RequestException = FakeRequestException
    fake.adapters = types.SimpleNamespace(
        Retry=FakeRetry, HTTPAdapter=FakeAdapter)
    old_requests = sys.modules.get('requests')
    FakeSession.created = 0
    FakeSession.instances = []
    namespace = {
        'kodi_utils': types.SimpleNamespace(
            xbmc=types.SimpleNamespace(getUserAgent=lambda: 'Kodi-QA/21.3'))}
    source = (patcher._lazy_block(kind)
              + '\nsession = _PovLazySession()\n')
    if eager:
        source = source.replace('session = _PovLazySession()',
                                'session = requests.Session()')
    try:
        sys.modules['requests'] = fake
        exec(compile(source, '<generated-' + kind + '>', 'exec'), namespace)
        return namespace, FakeSession.created, FakeSession.instances
    finally:
        if old_requests is None:
            sys.modules.pop('requests', None)
        else:
            sys.modules['requests'] = old_requests


print('\n=== behavioural lazy boundary ===')
for kind in ('tmdb', 'trakt'):
    fake = types.ModuleType('requests')
    fake.Session = FakeSession
    fake.RequestException = FakeRequestException
    fake.adapters = types.SimpleNamespace(
        Retry=FakeRetry, HTTPAdapter=FakeAdapter)
    old_requests = sys.modules.get('requests')
    FakeSession.created = 0
    FakeSession.instances = []
    namespace = {
        'kodi_utils': types.SimpleNamespace(
            xbmc=types.SimpleNamespace(getUserAgent=lambda: 'Kodi-QA/21.3'))}
    try:
        sys.modules['requests'] = fake
        source = (patcher._lazy_block(kind)
                  + '\nsession = _PovLazySession()\n')
        exec(compile(source, '<generated-' + kind + '>', 'exec'), namespace)
        check(kind + ' creates no HTTP Session on module import',
              FakeSession.created == 0, str(FakeSession.created))
        check(kind + ' resolves requests exceptions without creating a Session',
              namespace['requests'].RequestException is FakeRequestException
              and FakeSession.created == 0, str(FakeSession.created))
        result = namespace['session'].get('https://example.test', timeout=7)
        instance = FakeSession.instances[0]
        check(kind + ' creates one Session at the first live call',
              FakeSession.created == 1
              and result[0] == 'response', str(FakeSession.created))
        namespace['session'].request('POST', 'https://example.test')
        check(kind + ' reuses that Session on later calls',
              FakeSession.created == 1, str(FakeSession.created))
        check(kind + ' keeps the original retry policy',
              len(instance.mounts) == 1
              and instance.mounts[0][1].kwargs['pool_maxsize'] == 100
              and instance.mounts[0][1].kwargs['max_retries'].kwargs
                  == {'total': None, 'status': 1,
                      'status_forcelist': (429, 502, 503, 504)},
              repr(instance.mounts))
        expected_mount = ('https://api.themoviedb.org' if kind == 'tmdb'
                          else 'https://api.trakt.tv')
        check(kind + ' keeps the original API mount',
              instance.mounts[0][0] == expected_mount,
              repr(instance.mounts))
        if kind == 'trakt':
            check('trakt keeps Kodi user-agent setup',
                  instance.headers.get('User-Agent') == 'Kodi-QA/21.3',
                  repr(instance.headers))
    finally:
        if old_requests is None:
            sys.modules.pop('requests', None)
        else:
            sys.modules['requests'] = old_requests

# This makes the central no-Session-on-cache-hit assertion capable of failing:
# swap only the final proxy construction for the eager equivalent.
namespace, eager_count, _instances = execute_generated('tmdb', eager=True)
check('an eager-session mutation is caught by the behavioural assertion',
      eager_count != 0, str(eager_count))


print('\n=== startup delivery ===')
service = io.open(SERVICE, encoding='utf-8').read()
registration = '_maybe_patch_pov_http_lazy_imports,'
check('startup registers the HTTP repair exactly once',
      service.count(registration) == 1, str(service.count(registration)))
check('HTTP imports settle before watched/widget and AF3 menu work',
      service.index(registration)
      < service.index('_maybe_patch_pov_watched_lazy_imports,')
      < service.index('_maybe_patch_pov_widget_budget,')
      < service.index('_maybe_patch_af3_home,'))


if FAIL:
    print('\nFAILED: ' + ', '.join(FAIL))
    raise SystemExit(1)
print('\nAll POV HTTP lazy-import checks passed.')
