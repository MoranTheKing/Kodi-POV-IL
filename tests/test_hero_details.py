"""The Onyx hero's details for Israeli shows (Wizard hero_details.py): Keshet 12 and Kan 11."""
import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from urllib.parse import quote_plus, urlencode

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'

MAKO_PAGE = '<html><script id="__NEXT_DATA__" type="application/json">%s</script></html>' % json.dumps({
    'props': {'pageProps': {'data': {
        'seo': {'description': 'seo text', 'image': 'https://img.mako.co.il/seo_i_re.jpg'},
        'hero': {'description': 'The summary', 'logo': 'https://img.mako.co.il/logo_e.png',
                 'pics': [{'picUrl': 'https://img.mako.co.il/wide_x5_re.jpg'}]}}}}})
KAN_LIST = {'entry': [
    {'id': 11486, 'media_group': [{'media_item': [
        {'key': 'image_base', 'src': 'https://mobapi.kan.org.il/media/a/wide.jpg?width=480'},
        {'key': 'image_base_2x3', 'src': 'https://mobapi.kan.org.il/media/b/poster.jpg?width=480'}]}]},
    {'id': 7, 'media_group': [{'media_item': []}]}]}


def idan(module, url):
    # as Idan Plus's addDir builds it: url= quoted, then the whole query encoded again
    return 'plugin://plugin.video.idanplus/?' + urlencode({'name': 'x, y', 'url': quote_plus(url), 'mode': 2, 'module': module})


class _Reply:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        if isinstance(self.body, Exception):
            raise self.body

    def json(self):
        return self.body

    @property
    def text(self):
        return self.body


class HeroDetailsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='povil-details-'))
        self.props = {}
        self.fetched = []
        self.answers = {'www.mako.co.il': MAKO_PAGE, 'mobapi.kan.org.il': KAN_LIST}
        props, fetched = self.props, self.fetched

        def get(url, headers=None, timeout=None):
            fetched.append(url)
            host = url.split('/')[2]
            return _Reply(self.answers[host])
        fake = {
            'xbmcgui': types.SimpleNamespace(Window=lambda _id: types.SimpleNamespace(
                getProperty=lambda k: props.get(k, ''), setProperty=props.__setitem__)),
            'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: str(self.tmp) + '/'),
            'requests': types.SimpleNamespace(get=get),
        }
        self.saved = {k: sys.modules.get(k) for k in fake}
        sys.modules.update(fake)
        spec = importlib.util.spec_from_file_location('qa_hero_details', WIZARD / 'resources/libs/hero_details.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_keshet_gets_its_summary_picture_and_logo_from_mako(self):
        key = idan('keshet', 'https://www.mako.co.il/mako-vod-keshet/eretz_nehederet')
        self.props['povil.details.key'] = key
        self.mod.run()
        self.assertEqual(self.props['povil.details.plot'], 'The summary')
        self.assertEqual(self.props['povil.details.fanart'], 'https://img.mako.co.il/wide_x5_re.jpg')
        self.assertEqual(self.props['povil.details.logo'], 'https://img.mako.co.il/logo_e.png')
        self.assertEqual(self.props['povil.details.for'], key)
        self.assertEqual(self.fetched, ['https://www.mako.co.il/mako-vod-keshet/eretz_nehederet'])
        self.mod.run()
        self.assertEqual(len(self.fetched), 1, 'kept a week: the second visit fetches nothing')

    def test_kan_gets_its_wide_picture_from_the_programme_list(self):
        self.props['povil.details.key'] = idan('kan', 'https://www.kan.org.il/content/kan/kan-11/p-11486/')
        self.mod.run()
        self.assertEqual(self.props['povil.details.fanart'], 'https://mobapi.kan.org.il/media/a/wide.jpg?width=1280')
        self.assertEqual(self.props['povil.details.plot'], '', 'Idan already gives Kan its summary')
        self.props['povil.details.key'] = idan('kan', 'https://www.kan.org.il/content/kan/kan-11/p-7/')
        self.mod.run()
        self.assertEqual(self.props['povil.details.fanart'], '')
        self.assertEqual(len(self.fetched), 1, "Kan's list is kept a day")

    def test_a_failure_leaves_nothing_and_waits_an_hour(self):
        self.answers['www.mako.co.il'] = ValueError('blocked')
        key = idan('keshet', 'https://www.mako.co.il/mako-vod-keshet/x')
        self.props['povil.details.key'] = key
        self.mod.run()
        self.assertEqual((self.props['povil.details.fanart'], self.props['povil.details.for']), ('', key))
        self.mod.run()
        self.assertEqual(len(self.fetched), 1)

    def test_a_slow_answer_never_wipes_a_newer_items_details(self):
        a = idan('keshet', 'https://www.mako.co.il/mako-vod-keshet/a')
        b = idan('keshet', 'https://www.mako.co.il/mako-vod-keshet/b')
        self.props.update({'povil.details.key': a, 'povil.details.for': b, 'povil.details.fanart': 'B'})
        original = sys.modules['requests'].get

        def slow(url, headers=None, timeout=None):
            self.props['povil.details.key'] = b     # the user went back to B meanwhile
            return original(url, headers, timeout)
        sys.modules['requests'].get = slow
        self.mod.run()
        self.assertEqual((self.props['povil.details.for'], self.props['povil.details.fanart']), (b, 'B'))
        sys.modules['requests'].get = original
        self.props['povil.details.key'] = a
        self.mod.run()
        self.assertEqual(self.fetched.count('https://www.mako.co.il/mako-vod-keshet/a'), 1, 'kept for the revisit')
        self.assertEqual(self.props['povil.details.for'], a)

    def test_a_page_without_its_data_or_a_failed_kan_list_is_tried_again_later(self):
        self.answers['www.mako.co.il'] = '<html>a check page</html>'
        self.props['povil.details.key'] = idan('keshet', 'https://www.mako.co.il/mako-vod-keshet/c')
        self.mod.run()
        stored = [json.loads(p.read_text(encoding='utf-8')) for p in self.tmp.iterdir() if p.name != 'kan_wide.json']
        self.assertEqual([s['ok'] for s in stored], [False], 'an hour, not a week')
        self.answers['mobapi.kan.org.il'] = ValueError('down')
        for n in ('1', '2'):
            self.props['povil.details.key'] = idan('kan', 'https://www.kan.org.il/content/kan/kan-11/p-%s/' % n)
            self.mod.run()
        self.assertEqual(sum(1 for u in self.fetched if 'mobapi' in u), 1, 'a failed list waits an hour too')
        kan_shows = [json.loads(p.read_text(encoding='utf-8')) for p in self.tmp.iterdir()
                     if p.name != 'kan_wide.json' and 'kan' not in p.name]
        self.assertTrue(all(not k['ok'] for k in kan_shows), 'a show met while the list was down: again in an hour, not a week')

    def test_the_neighbours_are_ready_for_a_step_and_keshet_is_kept_for_the_rows(self):
        key = idan('keshet', 'https://www.mako.co.il/mako-vod-keshet/a')
        near = [idan('keshet', 'https://www.mako.co.il/mako-vod-keshet/n%d' % i) for i in range(5)]
        self.props['povil.details.key'] = key
        self.props['povil.details.near'] = ' '.join(near[:4] + [key])
        self.mod.run()
        self.assertEqual(self.props['povil.details.for'], key)
        for slot in (1, 2, 3, 4):
            self.assertEqual(self.props['povil.details.%d.for' % slot], near[slot - 1])
            self.assertEqual(self.props['povil.details.%d.plot' % slot], 'The summary')
        self.assertEqual(len(self.fetched), 5, 'the item and its four neighbours, nothing more')
        index = json.loads((self.tmp / 'index.json').read_text(encoding='utf-8'))
        self.assertEqual(index[key]['fanart'], 'https://img.mako.co.il/wide_x5_re.jpg')
        self.assertEqual(len(index), 5)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.name.endswith('.tmp')], [])
        # an entry lost to another run's write comes back on the next visit, with no fetch
        del index[key]
        (self.tmp / 'index.json').write_text(json.dumps(index), encoding='utf-8')
        self.props['povil.details.near'] = ''
        self.mod._index = None      # a new run: every RunPlugin is an interpreter of its own
        self.mod.run()
        self.assertIn(key, json.loads((self.tmp / 'index.json').read_text(encoding='utf-8')))
        self.assertEqual(len(self.fetched), 5)

    def test_kan_is_read_ahead_when_the_israeli_tab_opens(self):
        self.mod.warm()
        self.assertEqual(sum(1 for u in self.fetched if 'mobapi' in u), 1)
        kept = json.loads((self.tmp / 'kan_wide.json').read_text(encoding='utf-8'))
        self.assertEqual(kept['wide']['11486'], 'https://mobapi.kan.org.il/media/a/wide.jpg?width=1280')
        self.assertFalse((self.tmp / 'kan_wide.lock').exists())

    def test_anything_else_fetches_nothing(self):
        for key in ('plugin://plugin.video.pov/?mode=x', idan('reshet', 'https://13tv.co.il/x'), idan('keshet', 'http://evil/x'),
                    idan('keshet', 'https://evil.example/mako.co.il')):
            self.props['povil.details.key'] = key
            self.mod.run()
            self.assertEqual(self.props['povil.details.for'], key)
        self.assertEqual(self.fetched, [])


if __name__ == '__main__':
    unittest.main()
