"""Regression tests for release-aware timing on every AI delivery path."""
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import urllib.parse
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
    def test_resolve_binds_to_the_link_that_started_it(self):
        tree = ast.parse(TRANSLATE.read_text(encoding='utf-8'))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == 'resolve')
        snapshots = [node for node in ast.walk(function)
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute)
                     and node.func.attr == 'current_subtitle_selection']
        self.assertTrue(snapshots)
        self.assertTrue(any(
            any(k.arg == 'expected_link'
                and isinstance(k.value, ast.Name) and k.value.id == 'link'
                for k in call.keywords)
            for call in snapshots))

        # The foreground click still invalidates the old service marker before
        # it publishes the new current-selection token.
        tree = ast.parse(DEFAULT.read_text(encoding='utf-8'))
        handler = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == '_handle_download')
        calls = [node for node in ast.walk(handler)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == 'cancel_pending']
        self.assertTrue(calls)

    def test_helper_forwards_only_real_source_release_and_is_fail_open(self):
        calls = []
        subsync = types.ModuleType('resources.lib.subsync')
        subsync.process = lambda info, path, release, selection=None: (
            calls.append((info, path, release, selection)) or (path + '.fixed',
                                                    {'status': 'FIXABLE'}))
        ku = types.SimpleNamespace(
            log=Mock(),
            current_subtitle_selection=lambda: {
                'token': 'selection-token', 'link_hash': 'link-hash',
                'stream_hash': 'stream-hash'},
            stage_subtitle_delivery=Mock(return_value=True),
            set_subtitle_sync_status=Mock(return_value=True))
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
            self.assertIsNone(calls[0][3])
            # Embedded/extracted AI already owns the playing-file cue skeleton.
            self.assertEqual(
                helper({}, 'embedded.srt', 'SOURCE', embedded_timing=True),
                'embedded.srt')
            self.assertEqual(len(calls), 1)
            ku.stage_subtitle_delivery.assert_called_once_with(
                'embedded.srt', selection={
                    'token': 'selection-token', 'link_hash': 'link-hash',
                    'stream_hash': 'stream-hash'},
                status='confirmed', source='embedded')
            ku.set_subtitle_sync_status.assert_not_called()
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

    def test_embedded_file_is_staged_instead_of_published_before_delivery(self):
        tree = ast.parse(TRANSLATE.read_text(encoding='utf-8'))
        resolve = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == 'resolve')

        def is_embedded_sync(node):
            return (isinstance(node, ast.If)
                    and isinstance(node.test, ast.Compare)
                    and any(isinstance(value, ast.Constant)
                            and value.value == 'embedded_sync'
                            for value in node.test.comparators))

        branch = next(node for node in resolve.body if is_embedded_sync(node))
        file_branch = next(node for node in branch.body
                           if isinstance(node, ast.If)
                           and any(isinstance(ret, ast.Return)
                                   and isinstance(ret.value, ast.Name)
                                   and ret.value.id == '_out'
                                   for ret in ast.walk(node)))
        staged = [call for call in ast.walk(file_branch)
                  if isinstance(call, ast.Call)
                  and isinstance(call.func, ast.Attribute)
                  and call.func.attr == 'stage_subtitle_delivery']
        early_publish = [call for call in ast.walk(file_branch)
                         if isinstance(call, ast.Call)
                         and isinstance(call.func, ast.Name)
                         and call.func.id == '_publish_timing_status']
        self.assertTrue(staged)
        self.assertEqual(early_publish, [])

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
                    embedded_timing=False, selection=None: (
                forwarded.append((path, source_release, embedded_timing))
                or str(fixed))
            ku = types.ModuleType('resources.lib.kodi_utils')
            ku.notify = Mock()
            ku.subtitle_sync_registration_baseline = Mock(return_value=3)
            ku.confirm_subtitle_sync_registration = Mock(return_value=True)
            ku.abandon_subtitle_selection = Mock(return_value=True)
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
            ku.confirm_subtitle_sync_registration.assert_called_once_with(
                str(fixed), selection=None, before=3)

            # Kodi can reject an addDirectoryItem without raising. A staged
            # correction must not become FIXED in that case.
            ku.confirm_subtitle_sync_registration.reset_mock()
            plugin.addDirectoryItem = lambda **_kw: False
            with patch.dict(sys.modules, {
                    'resources': resources, 'resources.lib': lib,
                    'resources.lib.kodi_utils': ku,
                    'resources.lib.translate': tr,
                    'resources.lib.cache': cache,
                    'resources.lib.srt': srt}):
                self.assertTrue(fast(7, json.dumps({'x': 1}),
                                     {'imdb_id': 'tt1'}))
            ku.confirm_subtitle_sync_registration.assert_not_called()
            ku.abandon_subtitle_selection.assert_called_once_with(None)

    def test_embedded_switches_are_guarded_before_and_after_apply(self):
        tree = ast.parse(TRANSLATE.read_text(encoding='utf-8'))
        resolve = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == 'resolve')
        guarded = []
        for node in ast.walk(resolve):
            if not isinstance(node, ast.If):
                continue
            select_calls = [call for call in ast.walk(node.test)
                            if isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == 'select_embedded']
            if not select_calls:
                continue
            current_checks = [call for call in ast.walk(node.test)
                              if isinstance(call, ast.Call)
                              and isinstance(call.func, ast.Name)
                              and call.func.id == '_selection_current']
            guarded.append(len(current_checks))
        self.assertGreaterEqual(len(guarded), 2)
        self.assertTrue(all(count >= 2 for count in guarded), guarded)

    def test_failed_fallback_cannot_overwrite_a_manual_pick(self):
        def encoded(name):
            return urllib.parse.quote(json.dumps({
                'type': 'engine', 'source': name, 'filename': name}))

        failed, candidate_a, candidate_c = (
            encoded('failed'), encoded('A'), encoded('C'))
        state = {'link': failed, 'token': 'tok-0', 'seq': 0}
        calls = []
        ku = types.ModuleType('resources.lib.kodi_utils')

        def set_current(link):
            if link != state['link']:
                state['seq'] += 1
                state['token'] = 'tok-%d' % state['seq']
                state['link'] = link

        def snapshot(expected_link=None):
            if expected_link is not None and expected_link != state['link']:
                return {}
            return {'token': state['token'], 'link_hash': state['link'],
                    'stream_hash': 'stream'}

        ku.set_current_subtitle = set_current
        ku.current_subtitle_selection = snapshot
        ku.subtitle_selection_matches = lambda token, link_hash, stream_hash: (
            token == state['token'] and link_hash == state['link']
            and stream_hash == 'stream')
        ku.notify = Mock()
        tr = types.ModuleType('resources.lib.translate')
        tr._decode_link = lambda link: json.loads(urllib.parse.unquote(link))
        tr.list_candidates = lambda *_a, **_k: [
            {'language': 'he', 'link': candidate_a},
            {'language': 'he', 'link': candidate_c}]

        def resolve(link, _info, selection=None):
            calls.append(link)
            if link == candidate_a:
                set_current('manual-user-choice-B')
            return None

        tr.resolve = resolve
        resources = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        resources.lib = lib
        lib.kodi_utils, lib.translate = ku, tr
        env = {'os': os}
        with patch.dict(sys.modules, {
                'resources': resources, 'resources.lib': lib,
                'resources.lib.kodi_utils': ku,
                'resources.lib.translate': tr}):
            fallback = _function(DEFAULT, '_try_next_hebrew', env)
            result = fallback(
                failed, {}, owner_selection=snapshot(expected_link=failed))
        self.assertIsNone(result)
        self.assertEqual(state['link'], 'manual-user-choice-B')
        self.assertEqual(calls, [candidate_a])


if __name__ == '__main__':
    unittest.main()
