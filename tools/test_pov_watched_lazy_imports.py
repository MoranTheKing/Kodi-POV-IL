#!/usr/bin/env python3
"""Prove POV's watched backends are lazy without changing their calls."""

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
PATCHER = os.path.join(LIB, 'pov_watched_lazy_import_patcher.py')
SERVICE = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                       'service.py')

spec = importlib.util.spec_from_file_location('watched_lazy_test', PATCHER)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

FAIL = []


def check(label, condition, detail=''):
    print('{0:4} {1}{2}'.format(
        'ok' if condition else 'FAIL', label,
        (' -- ' + detail) if detail and not condition else ''))
    if not condition:
        FAIL.append(label)


IMPORT_BLOCK = '''from caches.mdbl_cache import clear_mdbl_collection_watchlist_data
from caches.trakt_cache import clear_trakt_collection_watchlist_data
from indexers import metadata
from indexers.local_api import local_get_hidden_items
from indexers.mdblist_api import mdbl_watched_unwatched, mdbl_progress, mdbl_get_hidden_items
from indexers.trakt_api import trakt_watched_unwatched, trakt_progress, trakt_get_hidden_items, trakt_official_status'''


def host_source(eol='\n'):
    text = ('from threading import Thread\n' + IMPORT_BLOCK
            + '\nfrom modules import kodi_utils, settings\nVALUE = 1\n')
    return text.replace('\n', eol)


print('=== narrow rewrite ===')
with tempfile.TemporaryDirectory(prefix='pov-watched-lazy-') as folder:
    path = os.path.join(folder, 'watched_cache.py')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(host_source())
    first = patcher._patch_file(path)
    once = open(path, 'rb').read()
    second = patcher._patch_file(path)
    twice = open(path, 'rb').read()
    text = once.decode('utf-8')
    tree = ast.parse(text)
    imported = {node.module for node in tree.body
                if isinstance(node, ast.ImportFrom)}
    check('the exact current POV block patches', first == 'patched', first)
    check('the patched module compiles', bool(compile(text, path, 'exec')))
    check('the marker appears exactly once',
          text.count(patcher.MARKER) == 1)
    check('metadata remains an eager dependency',
          'indexers' in imported and 'from indexers import metadata' in text)
    check('remote account modules are absent from top-level imports',
          not imported.intersection({
              'caches.mdbl_cache', 'caches.trakt_cache',
              'indexers.local_api', 'indexers.mdblist_api',
              'indexers.trakt_api'}), repr(imported))
    check('a second pass is byte-idempotent',
          second == 'unchanged' and once == twice, second)

    old_marker = patcher.MARKER.replace('_v1', '_v0')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(text.replace(patcher.MARKER, old_marker))
    upgraded = patcher._patch_file(path)
    upgraded_text = io.open(path, encoding='utf-8').read()
    check('an older generated block upgrades in place',
          upgraded == 'patched'
          and patcher.MARKER in upgraded_text
          and old_marker not in upgraded_text
          and upgraded_text.count('from indexers import metadata') == 1,
          upgraded)
    check('the upgraded module still compiles',
          bool(compile(upgraded_text, path, 'exec')))

    # Execute only the generated forwarders. This avoids depending on Kodi and
    # proves every positional/keyword argument and return value survives the
    # lazy boundary exactly.
    generated_names = {'_pov_lazy_watched_call'} | {
        name for name, _module in patcher._FORWARDERS}
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef)
             and node.name in generated_names]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'),
         namespace)
    saved = {}
    calls = []
    module_names = sorted(set(module for _name, module
                              in patcher._FORWARDERS))
    parent_names = sorted(set(name.split('.')[0] for name in module_names))
    try:
        for parent in parent_names:
            saved[parent] = sys.modules.get(parent)
            package = types.ModuleType(parent)
            package.__path__ = []
            sys.modules[parent] = package
        for module_name in module_names:
            saved[module_name] = sys.modules.get(module_name)
            module = types.ModuleType(module_name)
            sys.modules[module_name] = module
        for function_name, module_name in patcher._FORWARDERS:
            def target(*args, _name=function_name, **kwargs):
                calls.append((_name, args, kwargs))
                return ('returned', _name, args, kwargs)
            setattr(sys.modules[module_name], function_name, target)

        results = {}
        for index, (function_name, _module_name) in enumerate(
                patcher._FORWARDERS):
            args = (index, 'payload')
            kwargs = {'flag': True, 'index': index}
            results[function_name] = namespace[function_name](*args, **kwargs)
        check('every generated wrapper invokes its matching backend once',
              [name for name, _args, _kwargs in calls]
              == [name for name, _module in patcher._FORWARDERS],
              repr(calls))
        check('all wrapper arguments and return values are transparent',
              all(results[name]
                  == ('returned', name, (index, 'payload'),
                      {'flag': True, 'index': index})
                  for index, (name, _module) in enumerate(
                      patcher._FORWARDERS)), repr(results))
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old

with tempfile.TemporaryDirectory(prefix='pov-watched-unknown-') as folder:
    path = os.path.join(folder, 'watched_cache.py')
    unknown = host_source().replace(
        'trakt_official_status', 'future_upstream_status')
    with io.open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(unknown)
    before = open(path, 'rb').read()
    status = patcher._patch_file(path)
    check('an unknown upstream import shape is refused intact',
          status == 'unmatched' and open(path, 'rb').read() == before,
          status)

with tempfile.TemporaryDirectory(prefix='pov-watched-crlf-') as folder:
    path = os.path.join(folder, 'watched_cache.py')
    with open(path, 'wb') as handle:
        handle.write(host_source('\r\n').encode('utf-8'))
    status = patcher._patch_file(path)
    after = open(path, 'rb').read()
    check('the CRLF host shape patches', status == 'patched', status)
    check('the rewrite preserves CRLF without mixed line endings',
          after.count(b'\r\n') == after.count(b'\n'))


print('\n=== startup delivery ===')
service = io.open(SERVICE, encoding='utf-8').read()
registration = '_maybe_patch_pov_watched_lazy_imports,'
check('startup registers the repair exactly once',
      service.count(registration) == 1, str(service.count(registration)))
check('lazy imports settle before widget and AF3 menu work',
      service.index(registration)
      < service.index('_maybe_patch_pov_widget_budget,')
      < service.index('_maybe_patch_af3_home,'))


if FAIL:
    print('\nFAILED: ' + ', '.join(FAIL))
    raise SystemExit(1)
print('\nAll POV watched lazy-import checks passed.')
