"""The Onyx home's live TV row (Wizard pvr_row.py): the user's own channels, first on the right."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'

CHANNELS = {'channels': [
    {'channelid': 7, 'label': 'Channel One', 'hidden': False,
     'thumbnail': 'image://https%3a%2f%2flogos.example%2fone.png/', 'broadcastnow': {'title': 'News'}},
    {'channelid': 9, 'label': 'Hidden', 'hidden': True, 'thumbnail': ''},
    {'channelid': 12, 'label': 'Channel Two', 'hidden': False, 'thumbnail': '', 'broadcastnow': {}},
]}


class _Tag:
    def __init__(self):
        self.title = self.plot = ''

    def setTitle(self, title):
        self.title = title

    def setPlot(self, plot):
        self.plot = plot


class _Item:
    def __init__(self, label='', offscreen=False):
        self.label, self.art, self.props, self.tag = label, {}, {}, _Tag()

    def setArt(self, art):
        self.art.update(art)

    def getArt(self, key):
        return self.art.get(key, '')

    def setProperty(self, key, value):
        self.props[key] = value

    def getVideoInfoTag(self):
        return self.tag


class PvrRowTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.rpcs = [], []
        self.child = False
        self.reply = {'result': CHANNELS}
        self.details = {'result': {'channeldetails': {'channelid': 12, 'label': 'Channel Two'}}}
        calls, rpcs = self.calls, self.rpcs

        def rpc(text):
            request = json.loads(text)
            rpcs.append((request['method'], request['params']))
            if request['method'] == 'PVR.GetChannels':
                return json.dumps(self.reply)
            if request['method'] == 'PVR.GetChannelDetails':
                return json.dumps(self.details)
            return json.dumps({'result': 'OK'})
        fake = {
            'xbmc': types.SimpleNamespace(executeJSONRPC=rpc),
            'xbmcgui': types.SimpleNamespace(ListItem=_Item),
            'xbmcplugin': types.SimpleNamespace(
                addDirectoryItems=lambda h, items, n=0: calls.append(('items', items)),
                endOfDirectory=lambda h, **k: calls.append(('end',)),
                setResolvedUrl=lambda h, ok, item: calls.append(('resolved', ok))),
        }
        self.saved = {k: sys.modules.get(k) for k in fake}
        sys.modules.update(fake)
        spec = importlib.util.spec_from_file_location('qa_pvr_row', WIZARD / 'resources/libs/pvr_row.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.mod._child = lambda: self.child
        self.blurred = []
        self.mod._blur = self.blurred.append

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def items(self):
        self.mod.row(1)
        return next((c[1] for c in self.calls if c[0] == 'items'), [])

    def test_the_first_channel_is_last_in_the_list_so_on_the_right(self):
        items = self.items()
        self.assertEqual([i[1].label for i in items], ['Channel Two', 'Channel One'], 'hidden channels left out')
        self.assertTrue(all(i[1].props['povil_rtl'] == '1' and i[2] is False for i in items))
        one = items[-1][1]
        self.assertEqual(one.art['thumb'], 'https://logos.example/one.png', 'Kodi\'s wrapped art unwrapped')
        self.assertEqual((one.tag.title, one.tag.plot), ('Channel One', 'News'))
        self.assertEqual(self.blurred, [one], 'the soft wash only for a channel with a logo')
        query = dict(parse_qsl(items[-1][0].split('?', 1)[1]))
        self.assertEqual((query['mode'], query['id']), ('pvr_play', '7'))
        method, params = self.rpcs[0]
        self.assertEqual((method, params['channelgroupid'], params['limits']['end']), ('PVR.GetChannels', 'alltv', 200))

    def test_no_live_tv_or_a_kids_profile_lists_nothing(self):
        self.reply = {'error': {'code': -32100, 'message': 'Failed to execute method.'}}
        self.assertEqual(self.items(), [])
        self.assertIn(('end',), self.calls)
        self.calls.clear()
        self.reply = {'result': CHANNELS}
        self.child = True
        self.assertEqual(self.items(), [])

    def test_a_tap_plays_the_channel(self):
        self.mod.play(5, {'id': '12'})
        self.assertIn(('resolved', False), self.calls)
        self.assertEqual(self.rpcs[-2], ('PVR.GetChannelDetails', {'channelid': 12}))
        self.assertEqual(self.rpcs[-1], ('Player.Open', {'item': {'channelid': 12}}))
        # Kodi 21 crashes on Player.Open for a channel id while it has no live TV
        self.rpcs.clear()
        self.details = {'error': {'code': -32100, 'message': 'Failed to execute method.'}}
        self.mod.play(-1, {'id': '12'})
        self.assertEqual([m for m, _p in self.rpcs], ['PVR.GetChannelDetails'])
        self.details = {'result': {'channeldetails': {'channelid': 12}}}
        self.rpcs.clear()
        self.mod.play(-1, {'id': 'x'})
        self.assertEqual(self.rpcs, [])
        self.child = True
        self.mod.play(-1, {'id': '12'})
        self.assertEqual(self.rpcs, [])


if __name__ == '__main__':
    unittest.main()
