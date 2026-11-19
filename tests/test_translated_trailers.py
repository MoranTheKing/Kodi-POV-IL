"""Wizard 0.5.16: a trailer with a Hebrew translation in the picture, found on YouTube when TMDb has none.

The owner, Nov 2026: "in the series the trailers are in English with no Hebrew translation ... find the
trailer with a Hebrew translation, exactly like the original" -- and not a machine translation. TMDb lists a
Hebrew trailer for few series; Israeli distributors and channels upload many to YouTube ("טריילר מתורגם").
"""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('trailers_translated_test', ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py')
trailers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trailers)


def renderer(video, title, length, channel):
    return {'videoRenderer': {'videoId': video, 'title': {'runs': [{'text': title}]},
                              'lengthText': {'simpleText': length}, 'ownerText': {'runs': [{'text': channel}]}}}


ANSWER = {'contents': {'twoColumnSearchResultsRenderer': {'primaryContents': {'sectionListRenderer': {'contents': [
    {'itemSectionRenderer': {'contents': [
        renderer('AAAAAAAAAA1', 'Tulsa King | Official Trailer | Paramount+', '2:12', 'Paramount Plus'),
        renderer('AAAAAAAAAA2', 'טולסה קינג עונה 4 (2026) | טריילר מתורגם HD| בקרוב', '1:49', 'sly Israel'),
        renderer('AAAAAAAAAA3', 'טולסה קינג 3 | טריילר מתורגם| 24 לספטמבר', '1:59', 'HiT'),
        renderer('AAAAAAAAAA4', 'קינג טולסה | הטריילר הרשמי של עונה 4 | פרמאונט+', '1:49', 'Paramount Plus'),
        renderer('AAAAAAAAAA5', 'טולסה קינג | ביקורת עם תרגום', '6:10', 'someone'),
        renderer('AAAAAAAAAA6', 'טולסה קינג | טיזר מתורגם', '0:15', 'HiT'),
        {'shelfRenderer': {'content': {'verticalListRenderer': {'items': [
            renderer('AAAAAAAAAA7', 'Tulsa King trailer with Hebrew subtitles מתורגם', '2:00', 'fan')]}}}},
    ]}}]}}}}}


class TranslatedTests(unittest.TestCase):
    def test_a_search_answer_is_read_to_its_videos(self):
        found = trailers.search_results(ANSWER)
        self.assertEqual([f[2] for f in found], ['AAAAAAAAAA%d' % n for n in range(1, 8)])
        self.assertEqual(found[1], ('טולסה קינג עונה 4 (2026) | טריילר מתורגם HD| בקרוב', 109, 'AAAAAAAAAA2', 'sly Israel'))
        self.assertEqual([trailers.seconds_of(t) for t in ('1:49', '1:02:03', '', 'LIVE', '1:x')], [109, 3723, None, None, None])

    def test_only_a_translated_trailer_of_this_title_and_a_distributors_first(self):
        query, names = trailers.translated_query({'title': 'טולסה קינג', 'original_title': 'Tulsa King'})
        self.assertEqual(query, 'טולסה קינג טריילר מתורגם')
        self.assertEqual(names, ('טולסה קינג', 'tulsa king'))
        picked = trailers.translated_pick(trailers.search_results(ANSWER), names)
        # HiT's first, then the other channel's; never the English one, a machine-translated title (no "מתורגם"),
        # a review, or a 15-second teaser
        self.assertEqual(picked, ['AAAAAAAAAA3', 'AAAAAAAAAA2'])
        self.assertEqual(trailers.translated_pick(trailers.search_results(ANSWER), names, most=5),
                         ['AAAAAAAAAA3', 'AAAAAAAAAA2', 'AAAAAAAAAA7'])
        # another title's translated trailer is not this one's
        self.assertEqual(trailers.translated_pick(trailers.search_results(ANSWER), ('מרשלים', 'marshals')), [])
        # a title with no Hebrew name is asked for by its original one
        self.assertEqual(trailers.translated_query({'title': 'Slow Horses', 'original_title': 'Slow Horses'})[0],
                         'Slow Horses טריילר מתורגם')
        self.assertEqual(trailers.translated_query({}), (None, ()))
        # a video that sells a way to watch is no trailer (Coco's, on the owner's device: "watch Coco free, built-in
        # translation, the link in the description"); a Hebrew-dubbed trailer is a Hebrew one
        scams = [('קוקו לצפייה ישירה בחינם מתורגם', 120, 'CCCCCCCCCC1', 'x'), ('קוקו מתורגם - הלינק בתיאור', 90, 'CCCCCCCCCC2', 'x'),
                 ('Coco full movie מתורגם', 200, 'CCCCCCCCCC3', 'x'), ('קוקו - טריילר מדובב חדש', 104, 'CCCCCCCCCC4', 'Disney Israel')]
        self.assertEqual(trailers.translated_pick(scams, ('קוקו', 'coco')), ['CCCCCCCCCC4'])
        self.assertTrue(trailers.selling('קוקו לצפייה ישירה בחינם'))
        # "now to watch directly on yes VOD" is how yes and HOT name real trailers: alone it sells nothing, and a
        # small channel's is not taken by the search
        self.assertFalse(trailers.selling('טולסה קינג | טריילר מתורגם | עכשיו לצפייה ישירה ב-yes VOD'))
        self.assertFalse(trailers.selling('טולסה קינג | טריילר מתורגם | עכשיו לצפייה ישירה ב-yes VOD', 'yes'))
        self.assertTrue(trailers.selling('טולסה קינג | טריילר מתורגם | לצפייה ישירה', 'seret box'))
        # the very upload 0.5.16 took for Coco (its YouTube title says "translation" and names the film)
        self.assertTrue(trailers.selling('קוקו לצפייה ישירה עם תרגום מובנה בחינם'))
        self.assertEqual(trailers.translated_pick([('קוקו לצפייה ישירה עם תרגום מובנה בחינם', 141, 'DDDDDDDDDD1', 'seret box'),
                                                   ('טריילר מדובב קוקו | COCO', 63, 'DDDDDDDDDD2', 'Disney Israel')], ('קוקו', 'coco')),
                         ['DDDDDDDDDD2'])
        self.assertFalse(trailers.selling('קוקו - טריילר מדובב חדש'))
        self.assertFalse(trailers.selling('Coco | Official Final Trailer'))
        self.assertFalse(trailers.selling('דקסטר | טריילר מתורגם | זמין לצפייה ב-yes'), 'available to watch on a service: a trailer')
        self.assertFalse(trailers.selling('מואנה 2 | צפו עכשיו ב-Disney+ | טריילר מדובב'))
        self.assertFalse(trailers.selling('The Download | Official Trailer'[:0] + 'Hachiko | Official Trailer'))
        # whole words: a short name is not a part of another word
        short = [('היא חוזרת | טריילר מתורגם', 100, 'BBBBBBBBBB1', 'x'), ('איזו היאנה | טריילר מתורגם', 100, 'BBBBBBBBBB2', 'x')]
        self.assertEqual(trailers.translated_pick(short, ('היא',)), ['BBBBBBBBBB1'])
        self.assertTrue(trailers.trusted('HiT'))
        self.assertTrue(trailers.trusted('Netflix Israel'))
        self.assertFalse(trailers.trusted('History is Told'), 'a whole word only (HiT is not "History")')

    def test_the_title_a_trailer_belongs_to_and_whether_its_own_trailer_is_hebrew(self):
        address = 'plugin://plugin.video.youtube/play/?video_id=x8UAUAuKNcU&povil_alt=bbbbbbbbbbb'
        rows = [('tvshow', 1, json.dumps({'title': 'other', 'all_trailers': [{'key': 'x8UAUAuKNcU', 'iso_639_1': 'en'}]})),
                ('tvshow', 84773, json.dumps({'title': 'שר הטבעות: טבעות הכוח', 'trailer': address,
                                              'all_trailers': [{'key': 'x8UAUAuKNcU', 'iso_639_1': 'en'}]})),
                ('movie', 5, 'not json')]
        meta, hebrew = trailers.title_of(rows, address)
        self.assertEqual((meta['povil_id'], meta['title'], hebrew), ('tvshow:84773', 'שר הטבעות: טבעות הכוח', False))
        rows[1] = ('tvshow', 84773, json.dumps({'title': 'x', 'trailer': address, 'all_trailers': [{'key': 'x8UAUAuKNcU', 'iso_639_1': 'he'}]}))
        self.assertTrue(trailers.title_of(rows, address)[1], 'its own trailer is Hebrew: nothing is searched')
        self.assertEqual(trailers.title_of(rows[:1], address)[0]['povil_id'], 'tvshow:1', 'else one that lists it')
        self.assertEqual(trailers.title_of([], address), (None, False))

    def test_the_desk_tries_a_translated_trailer_first(self):
        class Home(object):
            def __init__(self, **values):
                self.values = dict(values)

            def getProperty(self, key):
                return self.values.get(key, '')

            def setProperty(self, key, value):
                self.values[key] = value

            def clearProperty(self, key):
                self.values.pop(key, None)

        class Player(object):
            calls, playing = [], None

            def play(self, url, item, windowed):
                self.calls.append(url)
                self.playing = url

            def isPlaying(self):
                return bool(self.playing)

            def getPlayingFile(self):
                return self.playing or ''

        address = 'plugin://plugin.video.youtube/play/?video_id=x8UAUAuKNcU&povil_alt=bbbbbbbbbbb'
        asked = []
        player = Player()
        desk = trailers.Desk(Home(**{trailers.ASK: address}), player,
                             lambda video: (asked.append(video), [{'url': 'http://x/%s.mpd' % video}])[1],
                             lambda url, stream: url, lambda: True, translated=lambda key: ['ccccccccccc'], halt=lambda: None)
        desk.born = 0.0
        self.assertTrue(desk.asked()())
        self.assertEqual(asked, ['ccccccccccc'], 'found translated: played, nothing else asked of YouTube')
        self.assertEqual(player.calls, ['http://x/ccccccccccc.mpd'])
        # a video that sells a way to watch is skipped at play time too -- whatever named it (TMDb as well)
        asked.clear()
        said = []
        streams = {'ccccccccccc': {'url': 'http://x/c.mpd', 'meta': {'title': 'קוקו לצפייה ישירה בחינם'}},
                   'x8UAUAuKNcU': {'url': 'http://x/x.mpd', 'meta': {'title': 'Coco | Official Final Trailer'}}}
        player = Player()
        player.calls = []
        desk = trailers.Desk(Home(**{trailers.ASK: address}), player, lambda video: (asked.append(video), [streams.get(video, {'url': 'u'})])[1],
                             lambda url, stream: url, lambda: True, translated=lambda key: ['ccccccccccc'], halt=lambda: None,
                             log=said.append)
        desk.born = 0.0
        self.assertTrue(desk.asked()())
        self.assertEqual(asked, ['ccccccccccc', 'x8UAUAuKNcU'])
        self.assertEqual(player.calls, ['http://x/x.mpd'])
        self.assertIn('not a trailer (it sells a way to watch): ccccccccccc', said)
        # a search that fails leaves the title's own trailers
        asked.clear()
        desk = trailers.Desk(Home(**{trailers.ASK: address}), Player(), lambda video: (asked.append(video), [{'url': 'u'}])[1],
                             lambda url, stream: url, lambda: True, translated=lambda key: 1 / 0, halt=lambda: None)
        desk.born = 0.0
        self.assertTrue(desk.asked()())
        self.assertEqual(asked, ['x8UAUAuKNcU'])

    def test_no_subtitles_are_asked_of_youtube(self):
        # its own are speech recognition or a machine translation, and they were refused when asked for every
        # trailer (429 in the QA Kodi)
        source = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py').read_text('utf-8')
        for gone in ('translate.googleapis', 'SUBTITLE_SELECTIONS', 'get_subtitle_selection', 'setSubtitles', 'tlang'):
            self.assertNotIn(gone, source, gone)


if __name__ == '__main__':
    unittest.main()
