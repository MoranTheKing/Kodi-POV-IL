"""Wizard 0.5.13: trailers and YouTube videos play past their first minute.

The owner, Nov 2026 (his phone, Wizard 0.5.12): "the trailer starts and gets stuck / stutters after about fifteen
seconds". His log and the QA Kodi: YouTube refused every read past about a minute of a stream named by the YouTube
add-on's "android_vr" client (403), inputstream.adaptive stopped reading, the picture stood still. The add-on (7.4.4)
plays the addresses of that client (its issues 1481 and 1483, open since Aug 2026).
"""
import importlib.util
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WIZ = ROOT / 'plugin.program.kodipovilwizard/resources/libs'

spec = importlib.util.spec_from_file_location('trailers_whole_test', WIZ / 'trailers.py')
trailers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trailers)

# the YouTube add-on 7.4.4's groups of clients (player_client.py, YouTubePlayerClient._client_groups)
GROUPS = (
    ('custom', ()),
    ('auth_enabled|initial_request|no_playable_streams', ('tv_unplugged', 'tv')),
    ('auth_disabled|kids|av1|vp9|vp9.2|avc1|stereo_sound|multi_audio', ('ios_testsuite_params',)),
    ('auth_disabled|kids|av1|vp9.2|avc1|surround_sound|multi_audio', ('android_testsuite_params',)),
    ('auth_enabled|no_kids|av1|vp9.2|avc1|surround_sound', ('android_vr',)),
    ('mpd', ()),
    ('ask', ()),
)

# the shape of the add-on's loop around the patch's anchor (player_client.py 7.4.4, load_stream_info), its
# anchor line at its real depth
LOOP = '''
def load(answers):
    responses = {}
    client_data = {}
    video_details = {}
    auth_client = None
    for _client_name, _has_auth in answers:
        if True:
            if True:
                if not auth_client and _has_auth:
                    auth_client = {'client': _client_name}
                responses[_client_name] = {
                    'client': {},
                    'progressive_fmts': ['18'],
                    'adaptive_fmts': ['140', '136'],
                    'mpd_manifest': None,
                    'hls_manifest': 'hls',
                }

                if (not client_data.get('_auth_required')
                        and video_details.get('isPrivate')):
                    client_data['_auth_required'] = True
    return responses, auth_client
'''


class WholeStreamsTests(unittest.TestCase):
    def test_the_trailer_desk_does_not_ask_the_client_youtube_cuts_short(self):
        self.assertEqual(trailers.CUT_SHORT, ('android_vr',))
        kept = trailers.whole_streams(GROUPS)
        self.assertEqual([name for name, _clients in kept], [name for name, _clients in GROUPS], 'every group stays, in its order')
        self.assertNotIn('android_vr', [client for _name, clients in kept for client in clients])
        self.assertEqual(dict(kept)['auth_disabled|kids|av1|vp9|vp9.2|avc1|stereo_sound|multi_audio'], ('ios_testsuite_params',))
        self.assertEqual(trailers.whole_streams(kept), kept)

        # light_streams sets it on the client object of its own interpreter, before asking
        asked = []

        class Client(object):
            _client_groups = GROUPS

            def load_stream_info(self, video_id):
                asked.append([c for _n, clients in self._client_groups for c in clients])
                return [{'url': 'u', 'sort': (1, 1)}], None

        class Settings(object):
            def mpd_video_qualities(self):
                return [{'nom_height': 720}]

            def stream_features(self, raw_values=False):
                return frozenset(('avc1', 'mp4a'))

        class Context(object):
            def ipc_exec(self, target, timeout=None):
                return True

            def get_settings(self):
                return Settings()

        client = Client()

        class Provider(object):
            def get_client(self, context):
                return client
        self.assertEqual(trailers.light_streams('hoRHBV0m1hw', Provider, Context, 'w'), [{'url': 'u', 'sort': (1, 1)}])
        self.assertNotIn('android_vr', asked[0])
        self.assertIn('android_testsuite_params', asked[0])

    def test_the_add_on_keeps_the_clients_answer_but_not_its_adaptive_streams(self):
        modules = {'xbmc': types.SimpleNamespace(log=lambda *a, **k: None, LOGINFO=1, LOGWARNING=2, LOGERROR=3),
                   'xbmcaddon': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p),
                   'resources': types.ModuleType('resources'), 'resources.libs': types.ModuleType('resources.libs'),
                   'resources.libs.common': types.SimpleNamespace(logging=types.SimpleNamespace(log=lambda *a, **k: None))}
        with mock.patch.dict(sys.modules, modules):
            espec = importlib.util.spec_from_file_location('yt_whole_engine', WIZ / 'patch_engine.py')
            engine_module = importlib.util.module_from_spec(espec)
            espec.loader.exec_module(engine_module)
        engine = engine_module.PatchEngine([])
        config = runpy.run_path(str(WIZ / 'patches/patches_config.py'))['PATCH_CONFIG']
        entry = next(e for e in config if e['id'] == 'youtube_whole_streams')
        self.assertEqual((entry['addon_id'], entry['enabled'], entry['optional']), ('plugin.video.youtube', True, True))
        self.assertEqual(entry['target_file'], 'resources/lib/youtube_plugin/youtube/client/player_client.py')

        source, changed, status = engine._apply_single_patch(LOOP, entry, '\n')
        self.assertEqual((changed, status), (True, 'applied'))
        self.assertEqual(engine._apply_single_patch(source, entry, '\n'), (source, False, 'skipped_current'))
        scope = {}
        exec(compile(source, 'player_client_excerpt', 'exec'), scope)
        responses, auth_client = scope['load']([('tv', None), ('ios_testsuite_params', False), ('android_vr', True)])
        self.assertIsNone(responses['android_vr']['adaptive_fmts'], 'the streams YouTube cuts short are not played')
        self.assertEqual(responses['android_vr']['progressive_fmts'], ['18'], 'the rest of its answer stays')
        self.assertEqual(responses['android_vr']['hls_manifest'], 'hls')
        self.assertEqual(responses['ios_testsuite_params']['adaptive_fmts'], ['140', '136'])
        self.assertEqual(auth_client, {'client': 'android_vr'}, "a signed-in viewer's watch history still rides on it")
        # an add-on whose code moved: the optional patch finds no anchor and leaves the file alone
        self.assertEqual(engine._apply_single_patch('def load():\n    pass\n', entry, '\n')[2], 'anchor_missing')


if __name__ == '__main__':
    unittest.main()
