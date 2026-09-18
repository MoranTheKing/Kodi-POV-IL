"""Regression tests for release-aware timing on every AI delivery path."""
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
TRANSLATE = ROOT / 'addons/service.subtitles.kodipovilai/resources/lib/translate.py'
DEFAULT = ROOT / 'addons/service.subtitles.kodipovilai/default.py'


def _function(path, name, globals_):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(item for item in tree.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'),
         globals_)
    return globals_[name]


class AiDeliverySyncTests(unittest.TestCase):
    def test_all_selection_entry_points_cancel_an_older_timing_job(self):
        expectations = [
            (TRANSLATE, 'resolve', 'relative'),
            (DEFAULT, '_handle_download', 'absolute'),
        ]
        for path, function_name, import_kind in expectations:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            function = next(node for node in tree.body
                            if isinstance(node, ast.FunctionDef)
                            and node.name == function_name)
            calls = [node for node in ast.walk(function)
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute)
                     and node.func.attr == 'cancel_pending']
            self.assertTrue(calls, '%s does not cancel stale SubSync work'
                            % function_name)
            first_branch = min(node.lineno for node in ast.walk(function)
                               if isinstance(node, ast.If))
            self.assertLess(calls[0].lineno, first_branch,
                            '%s cancels only after an early-return branch'
                            % function_name)

    def test_helper_forwards_only_real_source_release_and_is_fail_open(self):
        calls = []
        subsync = types.ModuleType('resources.lib.subsync')
        subsync.process = lambda info, path, release: (
            calls.append((info, path, release)) or (path + '.fixed',
                                                    {'status': 'FIXABLE'}))
        ku = types.SimpleNamespace(log=Mock())
        env = {'os': os, 'kodi_utils': ku, '__package__': 'resources.lib'}
        resources = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        resources.lib = lib
        with patch.dict(sys.modules, {
                'resources': resources, 'resources.lib': lib,
                'resources.lib.subsync': subsync}):
            helper = _function(TRANSLATE, '_sync_hebrew_delivery', env)
            self.assertEqual(
                helper({'release': 'PLAYING'}, 'canonical.srt',
                       source_release='SOURCE.WEB-DL'),
                'canonical.srt.fixed')
            self.assertEqual(calls[0][2], 'SOURCE.WEB-DL')
            # Embedded/extracted AI already owns the playing-file cue skeleton.
            self.assertEqual(
                helper({}, 'embedded.srt', 'SOURCE', embedded_timing=True),
                'embedded.srt')
            self.assertEqual(len(calls), 1)
            subsync.process = Mock(side_effect=RuntimeError('boom'))
            self.assertEqual(helper({}, 'original.srt', ''), 'original.srt')

    def test_resolve_has_no_raw_completed_ai_return(self):
        tree = ast.parse(TRANSLATE.read_text(encoding='utf-8'))
        resolve = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == 'resolve')
        raw = []
        for node in ast.walk(resolve):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Name):
                if node.value.id in {'translated', 'translated_by_content',
                                     'gpath'}:
                    raw.append((node.lineno, node.value.id))
        self.assertEqual(raw, [], 'completed AI path bypasses _deliver: %r' % raw)

    def test_every_file_based_hebrew_route_uses_shared_gate(self):
        tree = ast.parse(TRANSLATE.read_text(encoding='utf-8'))
        resolve = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == 'resolve')

        def compared_kind(node):
            if not isinstance(node.test, ast.Compare):
                return None
            values = [item.value for item in node.test.comparators
                      if isinstance(item, ast.Constant)
                      and isinstance(item.value, str)]
            return values[0] if values else None

        branches = {compared_kind(node): node for node in resolve.body
                    if isinstance(node, ast.If) and compared_kind(node)}
        for kind in ('passthrough', 'pool', 'engine'):
            calls = [node for node in ast.walk(branches[kind])
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name)
                     and node.func.id == '_sync_hebrew_delivery']
            self.assertTrue(calls, '%s bypasses shared Hebrew timing gate' % kind)

    def test_native_picker_cache_hit_delivers_synced_copy(self):
        with tempfile.TemporaryDirectory() as root:
            cached = Path(root) / 'canonical.srt'
            cached.write_text('canonical bytes', encoding='utf-8')
            fixed = Path(root) / 'fixed.srt'
            fixed.write_text('fixed bytes', encoding='utf-8')
            forwarded = []
            tr = types.ModuleType('resources.lib.translate')
            tr._decode_link = lambda _link: {
                'type': 'ai', 'source_lang': 'en',
                'local_path': str(Path(root) / 'source.srt'),
                'release': 'SOURCE.RELEASE'}
            tr._source_id_for_ai = lambda _payload: 'source-id'
            tr._sync_hebrew_delivery = lambda info, path, source_release='', \
                    embedded_timing=False: (
                forwarded.append((path, source_release, embedded_timing))
                or str(fixed))
            ku = types.ModuleType('resources.lib.kodi_utils')
            ku.notify = Mock()
            cache = types.ModuleType('resources.lib.cache')
            cache.translated_path = lambda *a, **k: str(cached)
            srt = types.ModuleType('resources.lib.srt')
            lib = types.ModuleType('resources.lib')
            lib.kodi_utils, lib.translate, lib.cache, lib.srt = ku, tr, cache, srt
            resources = types.ModuleType('resources')
            resources.lib = lib
            delivered = []
            plugin = types.SimpleNamespace(
                addDirectoryItem=lambda **kw: delivered.append(kw['url']),
                endOfDirectory=Mock())
            gui = types.SimpleNamespace(ListItem=lambda label: label)
            env = {'os': os, 'xbmcplugin': plugin, 'xbmcgui': gui,
                   '_safe_log': Mock()}
            with patch.dict(sys.modules, {
                    'resources': resources, 'resources.lib': lib,
                    'resources.lib.kodi_utils': ku,
                    'resources.lib.translate': tr,
                    'resources.lib.cache': cache,
                    'resources.lib.srt': srt}):
                fast = _function(DEFAULT, '_try_fast_download', env)
                self.assertTrue(fast(7, json.dumps({'x': 1}),
                                     {'imdb_id': 'tt1'}))
            self.assertEqual(delivered, [str(fixed)])
            self.assertEqual(forwarded,
                             [(str(cached), 'SOURCE.RELEASE', False)])
            self.assertEqual(cached.read_text(encoding='utf-8'),
                             'canonical bytes')


if __name__ == '__main__':
    unittest.main()
