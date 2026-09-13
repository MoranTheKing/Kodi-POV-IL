"""Exercise the real background handler's early-return subtitle delivery."""
import ast
import base64
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

DEFAULT = Path(__file__).resolve().parents[1] / 'addons/service.subtitles.kodipovilai/default.py'


class CachedPickerDelivery(unittest.TestCase):
    def run_handler(self, mode='cache', source='source1'):
        with tempfile.TemporaryDirectory() as root:
            canonical = Path(root) / 'translated.ar.he.srt'
            canonical.write_text('1\n00:00:01,000 --> 00:00:02,000\nשלום\n', encoding='utf-8')
            props = {}
            window = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
                setProperty=lambda k, v: props.__setitem__(k, v),
                clearProperty=lambda k: props.pop(k, None))
            state = {'owner': True, 'media': 'movie-a', 'streams': ['English']}
            deliveries = []
            def deliver(path):
                deliveries.append(Path(path).read_text(encoding='utf-8'))
                state['streams'].append('Hebrew')
            player = types.SimpleNamespace(getPlayingFile=lambda: state['media'],
                setSubtitles=deliver, showSubtitles=Mock(),
                getAvailableSubtitleStreams=lambda: state['streams'], setSubtitleStream=Mock())
            ku = types.ModuleType('resources.lib.kodi_utils')
            ku.current_video_info=lambda: {'imdb_id': 'test'}
            ku.cache_dir=lambda: root
            ku.safe_release_filename=lambda value: value
            ku.notify=Mock()
            tr = types.ModuleType('resources.lib.translate')
            def resolve(link, info, progressive_cb, extract_progress_cb):
                if mode == 'new-job': state['owner'] = False
                if mode == 'new-pick': props['ai_subs.live_translate_active'] = '0'
                if mode == 'new-source': props['ai_subs.live_translate_source'] = 'different'
                if mode == 'new-player': state['media'] = 'movie-b'
                if mode == 'stopped': state['media'] = ''
                if mode == 'done':
                    progressive_cb('done', {'success': True, 'path': str(canonical), 'source_id': source})
                return str(canonical)
            tr.resolve=resolve
            lib=types.ModuleType('resources.lib'); lib.kodi_utils=ku; lib.translate=tr
            pkg=types.ModuleType('resources'); pkg.lib=lib
            tree=ast.parse(DEFAULT.read_text(encoding='utf-8'))
            fn=next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name=='_handle_bg_translate_picker')
            env={'os': os, 'base64': base64,
                'xbmc': types.SimpleNamespace(Player=lambda: player, sleep=lambda n: None),
                'xbmcgui': types.SimpleNamespace(Window=lambda n: window),
                '_safe_log': Mock(), '_new_translation_job': lambda: 'job',
                '_owns_translation_job': lambda token: state['owner'],
                '_clear_translation_job': Mock(), '_playing_now': lambda: bool(state['media']),
                '_progressive_cleanup_patterns': lambda *a: []}
            real_replace = os.replace
            def replace_and_change_player(src, dst):
                real_replace(src, dst)
                if mode == 'change-during-copy':
                    state['media'] = 'movie-b'
            with patch.object(os, 'replace', replace_and_change_player), patch.dict(sys.modules, {'resources': pkg, 'resources.lib': lib,
                    'resources.lib.kodi_utils': ku, 'resources.lib.translate': tr}):
                exec(compile(ast.Module(body=[fn], type_ignores=[]), str(DEFAULT), 'exec'), env)
                env['_handle_bg_translate_picker']({'link_b64': base64.b64encode(b'link').decode(),
                    'source_id_b64': base64.b64encode(source.encode()).decode()})
            return deliveries

    def test_cache_hit_delivers_hebrew(self):
        self.assertEqual(len(self.run_handler()), 1)
        self.assertIn('שלום', self.run_handler()[0])

    def test_embedded_cache_hit_without_source_id_delivers(self):
        self.assertEqual(len(self.run_handler(source='')), 1)

    def test_done_callback_does_not_deliver_twice(self):
        self.assertEqual(len(self.run_handler('done')), 1)

    def test_new_selection_and_player_changes_prevent_delivery(self):
        for mode in ('new-job', 'new-pick', 'new-source', 'new-player', 'stopped', 'change-during-copy'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_handler(mode), [])


if __name__ == '__main__':
    unittest.main()
