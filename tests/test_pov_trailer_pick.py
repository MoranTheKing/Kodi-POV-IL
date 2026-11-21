"""Wizard 0.5.7: which of a title's trailers POV names (patches/pov_trailer_pick.py).

A viewer, Nov 2026: "for a series, when the only Hebrew trailer is a later season's, prefer the original
trailer -- there usually is one for the first season". The owner: "first of all a trailer translated to Hebrew
when there is one -- for the season itself on a season's poster, for a film in general -- and for series as he
wrote".
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
spec = importlib.util.spec_from_file_location('pov_trailer_pick_test', WIZARD / 'resources/libs/patches/pov_trailer_pick.py')
tp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tp)


def video(key, lang, name, published='2020-01-01T00:00:00.000Z', kind='Trailer', site='YouTube'):
    return {'key': key, 'iso_639_1': lang, 'name': name, 'published_at': published, 'type': kind, 'site': site}


SEASONS = [{'season_number': 0, 'air_date': '2019-12-01'}, {'season_number': 1, 'air_date': '2019-07-04'},
           {'season_number': 2, 'air_date': '2021-06-10'}, {'season_number': 3, 'air_date': '2023-05-01'}]
SHOW = {'seasons': SEASONS}


def first(*args):
    """The trailer named first (what follows it in the address are its alternatives)."""
    named = tp.pick(*args)
    return named.split('&')[0] if named else None


def patches():
    spec_c = importlib.util.spec_from_file_location('patches_config_trailer_test', WIZARD / 'resources/libs/patches/patches_config.py')
    config = importlib.util.module_from_spec(spec_c)
    with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}):
        spec_c.loader.exec_module(config)
    found = next(v for v in vars(config).values() if isinstance(v, list) and v and isinstance(v[0], dict) and 'hook' in v[0])
    return {p['id']: p for p in found}


class SeasonOfATrailer(unittest.TestCase):
    def test_its_name_says_which(self):
        for name, season in (('Season 2 | Official Trailer', 2), ('SEASON 03 Teaser', 3), ('עונה 3 | טריילר רשמי מתורגם', 3),
                             ('טריילר העונה השנייה', 2), ('The Final Season | Trailer', tp.LAST), ('Official Trailer S4', 4),
                             ('Series 2 Trailer', 2), ('First Season Recap Trailer', 1), ('העונה האחרונה - טריילר', tp.LAST),
                             ('Official Trailer', None), ('טריילר רשמי מתורגם', None), ('Trailer 2', None), ('', None), (None, None)):
            self.assertEqual(tp.named_season(name), season, name)

    def test_or_the_season_it_was_published_for(self):
        # (0.5.40: '2021-09-01' -- three months into season 2, twenty before season 3 -- is no season's: it was 3's)
        for published, season in (('2019-05-20', 1), ('2019-07-30', 1), ('2021-04-01', 2), ('2021-07-01', 2), ('2021-09-01', None),
                                  ('2022-06-01', 3), ('2023-04-01', 3), ('2023-09-01', 3)):
            self.assertEqual(tp.dated_season(published + 'T10:00:00.000Z', SEASONS), season, published)
        # published more than a year after the last season began (an old series, uploaded later): the date tells nothing
        self.assertIsNone(tp.dated_season('2025-01-01', SEASONS))
        self.assertIsNone(tp.dated_season('', SEASONS))
        self.assertIsNone(tp.dated_season('2020-01-01', []))
        # one season only: every trailer is its own
        self.assertEqual(tp.season_of(video('a', 'en', 'Official Trailer', '2030-01-01'), [{'season_number': 1, 'air_date': '2019-01-01'}]), 1)
        # the name wins over the date
        self.assertEqual(tp.season_of(video('a', 'he', 'עונה 3', '2019-06-01'), SEASONS), 3)

    def test_a_trailer_out_long_before_the_next_season_is_the_series_own(self):
        # Law & Order (1990), the owner, Nov 2026: its one trailer on TMDb came out in 2016, between season 20 (2009) and
        # the revival's season 21 (2022) -- the channel's post called it "season 21's trailer" on the series' own poster
        seasons = [{'season_number': n, 'air_date': '%d-09-20' % (1989 + n)} for n in range(1, 21)]
        seasons += [{'season_number': 21, 'air_date': '2022-02-24'}, {'season_number': 22, 'air_date': '2022-09-22'},
                    {'season_number': 25, 'air_date': '2025-09-25'}, {'season_number': 26, 'air_date': '2026-10-08'}]
        trailer = video('RzN8cPlcMTU', 'en', 'Law and Order Trailer', '2016-06-22T00:00:00.000Z')
        self.assertIsNone(tp.season_of(trailer, seasons))
        self.assertEqual(first([trailer], {'seasons': seasons}, 'he', 'tvshow'), 'RzN8cPlcMTU')
        # season 21's poster has no trailer of its own: the series' stands (for_season None)
        self.assertIsNone(tp.for_season({'all_trailers': [trailer], 'season_data': seasons, 'tmdb_id': 549}, 21))
        # a season's own trailer, a few months before it, is still that season's
        self.assertEqual(tp.season_of(video('b', 'en', 'Law & Order | Official Trailer', '2021-12-01T00:00:00.000Z'), seasons), 21)


class TheChoice(unittest.TestCase):
    def test_a_film_hebrew_first_else_the_original(self):
        videos = [video('en1', 'en', 'Official Trailer'), video('he1', 'he', 'טריילר מתורגם'), video('en2', 'en', 'Teaser', kind='Teaser')]
        self.assertEqual(first(videos, {}, 'he', 'movie'), 'he1')
        self.assertEqual(first(videos[:1] + videos[2:], {}, 'he', 'movie'), 'en1', 'a title with no Hebrew trailer has one now')
        self.assertEqual(first([video('en2', 'en', 'Teaser', kind='Teaser'), video('en1', 'en', 'Trailer')], {}, 'he', 'movie'), 'en1',
                         'a trailer before a teaser')
        self.assertIsNone(first([video('x', 'en', 'Clip', kind='Clip'), video('v', 'he', 'Trailer', site='Vimeo')], {}, 'he', 'movie'))
        self.assertIsNone(first([], {}, 'he', 'movie'))
        self.assertIsNone(first(None, None, None, 'movie'))

    def test_a_series_its_first_season_before_a_later_one(self):
        he3 = video('he3', 'he', 'עונה 3 | טריילר רשמי מתורגם', '2023-04-01')
        he1 = video('he1', 'he', 'טריילר רשמי מתורגם', '2019-06-01')
        en1 = video('en1', 'en', 'Official Trailer', '2019-05-15')
        en2 = video('en2', 'en', 'Season 2 Official Trailer', '2021-05-01')
        # the viewer's case: the only Hebrew trailer is a later season's -> the original first-season trailer
        self.assertEqual(first([he3, en2, en1], SHOW, 'he', 'tvshow'), 'en1')
        # a Hebrew trailer of the first season is there: it comes first
        self.assertEqual(first([he3, en1, he1], SHOW, 'he', 'tvshow'), 'he1')
        # nothing of the first season at all: a Hebrew trailer before an original one
        self.assertEqual(first([en2, he3], SHOW, 'he', 'tvshow'), 'he3')
        self.assertEqual(first([en2], SHOW, 'he', 'tvshow'), 'en2')
        # a later season told only by its date
        late = video('late', 'he', 'טריילר רשמי מתורגם', '2023-04-10')
        self.assertEqual(first([late, en1], SHOW, 'he', 'tvshow'), 'en1')
        # an old series whose trailers were uploaded years later: the Hebrew one, as before
        old = {'seasons': [{'season_number': 1, 'air_date': '1994-09-22'}, {'season_number': 2, 'air_date': '1995-09-21'}]}
        self.assertEqual(first([video('en', 'en', 'Trailer', '2012-03-01'), video('he', 'he', 'טריילר', '2015-01-01')], old, 'he', 'tvshow'), 'he')
        # the cached form of a series (POV's own meta) carries the seasons under another name
        self.assertEqual(first([he3, en1], {'season_data': SEASONS}, 'he', 'tvshow'), 'en1')
        # a series TMDb gives no seasons for: nothing to tell by, Hebrew first
        self.assertEqual(first([en1, he1], {}, 'he', 'tvshow'), 'he1')

    def test_a_season_gets_its_own_trailer_hebrew_first(self):
        meta = {'season_data': SEASONS, 'all_trailers': [
            video('en1', 'en', 'Official Trailer', '2019-05-15'), video('en3', 'en', 'Season 3 Trailer', '2023-03-01'),
            video('he3', 'he', 'עונה 3 | טריילר מתורגם', '2023-04-01'), video('en2', 'en', 'Season 2 Official Trailer', '2021-05-01')]}
        address = 'plugin://plugin.video.youtube/play/?video_id=%s'
        self.assertEqual(tp.for_season(meta, 3), address % 'he3&povil_alt=en3', 'the Hebrew one, the original as its alternative')
        self.assertEqual(tp.for_season(meta, 2), address % 'en2')
        self.assertEqual(tp.for_season(meta, '1'), address % 'en1')
        self.assertIsNone(tp.for_season(meta, 4), "no trailer of that season: the series' own stands")
        self.assertIsNone(tp.for_season(meta, 0))
        self.assertIsNone(tp.for_season({}, 1))
        self.assertIsNone(tp.for_season(None, 'x'))


class TheAlternatives(unittest.TestCase):
    def test_the_address_carries_the_next_trailers_in_the_same_order_of_preference(self):
        # the owner: "the trailers are really short -- surely a film has several; play the regular or the long
        # ones, not a ten-second clip". TMDb does not say how long a video is: the home's trailer desk learns it
        # when it reads the stream, and needs the alternatives to choose among
        videos = [video('en1', 'en', 'Official Trailer'), video('he1', 'he', 'ספוט'), video('en2', 'en', 'Final Trailer'),
                  video('he2', 'he', 'טריילר מתורגם'), video('en3', 'en', 'Teaser', kind='Teaser'), video('en4', 'en', 'Trailer 3')]
        self.assertEqual(tp.ranked(videos, {}, 'he', 'movie'), ['he1', 'he2', 'en1', 'en2', 'en4', 'en3'])
        self.assertEqual(tp.pick(videos, {}, 'he', 'movie'), 'he1&povil_alt=he2.en1.en2', 'the first, then three more at most')
        self.assertEqual(tp.pick(videos[:1], {}, 'he', 'movie'), 'en1', 'one trailer only: nothing is added')
        self.assertEqual(tp.ALTERNATIVES, 3)
        # a series: its first season's trailers first, the later seasons' after them
        he3 = video('he3', 'he', 'עונה 3 | טריילר', '2023-04-01')
        en1 = video('en1', 'en', 'Official Trailer', '2019-05-15')
        self.assertEqual(tp.pick([he3, en1], SHOW, 'he', 'tvshow'), 'en1&povil_alt=he3')


class TheHooks(unittest.TestCase):
    def test_tmdb_is_asked_for_hebrew_and_original_videos_in_the_same_request(self):
        found = patches()
        for pid, what, append in (('pov_trailer_videos_movie', 'movie', 'movies_append'), ('pov_trailer_videos_tv', 'tv', 'tvshows_append')):
            patch = found[pid]
            self.assertEqual((patch['action'], patch['target_file'], patch.get('optional')), ('append_after', 'resources/lib/indexers/tmdb_api.py', True))
            self.assertEqual(patch['anchor'].strip(), "url = '/3/%s/%%s?language=%%s&append_to_response=%%s' %% (tmdb_id, language, %s)" % (what, append))
            for language, tail in (('he', '&include_video_language=he,en,null'), ('pt-BR', '&include_video_language=pt,en,null'), ('en', ''), ('en-US', '')):
                scope = {'language': language, 'url': '/3/x'}
                exec(patch['hook'], scope)
                self.assertEqual(scope['url'], '/3/x' + tail, language)

    def test_povs_own_choice_is_asked_first_and_stands_when_the_wizard_has_none(self):
        patch = patches()['pov_trailer_pick']
        self.assertEqual((patch['action'], patch['target_file']), ('prepend_before', 'resources/lib/indexers/metadata.py'))
        source = ("def get_trailer(self, videos):\n" +
                  ''.join('\t' + line + '\n' for line in patch['hook'].rstrip('\n').split('\n')) +
                  "\t" + patch['anchor'] + "\n\ttrailer_key = next(trailer_key, '')\n\tif trailer_key: return youtube_url % trailer_key\n\treturn trailer_key\n")
        scope = {'youtube_url': 'plugin://plugin.video.youtube/play/?video_id=%s', 'trailers_test': ('Trailer', 'Teaser')}
        exec(source, scope)
        me = types.SimpleNamespace(data=SHOW, lang='he', mediatype='tvshow')
        videos = [video('he3', 'he', 'עונה 3', '2023-04-01'), video('en1', 'en', 'Official Trailer', '2019-05-15')]
        with mock.patch.dict(sys.modules, {'pov_trailer_pick': tp, 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}):
            self.assertEqual(scope['get_trailer'](me, videos), scope['youtube_url'] % 'en1&povil_alt=he3')
            self.assertEqual(scope['get_trailer'](me, []), '')
        # the Wizard's module missing or failing: POV's own choice, as before
        broken = types.ModuleType('pov_trailer_pick')
        with mock.patch.dict(sys.modules, {'pov_trailer_pick': broken, 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}):
            self.assertEqual(scope['get_trailer'](me, videos), scope['youtube_url'] % 'he3')

    def test_a_season_item_is_given_its_seasons_trailer(self):
        patch = patches()['pov_trailer_season']
        self.assertEqual((patch['action'], patch['target_file'], patch['anchor']),
                         ('append_after', 'resources/lib/menus/seasons.py', 'infotag.setCast(make_cast_list(show.cast))'))
        set_to = []
        scope = {'infotag': types.SimpleNamespace(setTrailer=set_to.append), 'season_number': 3,
                 'show': types.SimpleNamespace(meta={'season_data': SEASONS, 'all_trailers': [video('he3', 'he', 'עונה 3')]})}
        with mock.patch.dict(sys.modules, {'pov_trailer_pick': tp, 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}):
            exec(patch['hook'], scope)
            scope['season_number'] = 2
            exec(patch['hook'], scope)
        self.assertEqual(set_to, ['plugin://plugin.video.youtube/play/?video_id=he3'], 'only when that season has one')


class TheRefresh(unittest.TestCase):
    def test_the_cached_series_and_the_films_with_no_trailer_are_let_go_once(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(tp.purge_once(folder), 'no cache yet: nothing to do, and nothing is marked')
            self.assertFalse(os.path.exists(os.path.join(folder, tp.PURGE_FLAG)))
            con = sqlite3.connect(os.path.join(folder, 'metacache.db'))
            con.execute('CREATE TABLE metadata (db_type TEXT not null, tmdb_id TEXT not null, imdb_id TEXT, tvdb_id TEXT, expires INTEGER, meta TEXT, UNIQUE (db_type, tmdb_id))')
            con.executemany('INSERT INTO metadata (db_type, tmdb_id, meta) VALUES (?, ?, ?)',
                            [('tvshow', '1', 'x'), ('tvshow', '2', 'x'),
                             ('movie', '3', '{"title": "a", "trailer": "plugin://plugin.video.youtube/play/?video_id=he1"}'),
                             ('movie', '4', '{"title": "b", "trailer": ""}'), ('movie', '5', '{"title": "c"}'),
                             ('movie', '6', 'not json: left alone'),
                             ('movie', '7', '{"title": "d", "trailer": "plugin://plugin.video.youtube/play/?video_id=he1&povil_alt=en1"}')])
            con.commit()
            con.close()
            said = []
            self.assertEqual(tp.purge_once(folder, log=said.append), 5)
            con = sqlite3.connect(os.path.join(folder, 'metacache.db'))
            # a film stays only when its trailer was already named with its alternatives (or it cannot be read)
            self.assertEqual(con.execute('SELECT db_type, tmdb_id FROM metadata ORDER BY tmdb_id').fetchall(), [('movie', '6'), ('movie', '7')])
            self.assertEqual(said, ['trailer pick: 2 series and 3 films will be asked again'])
            con.execute("INSERT INTO metadata (db_type, tmdb_id, meta) VALUES ('tvshow', '9', 'x')")
            con.commit()
            con.close()
            self.assertEqual(len(said), 1)
            self.assertIsNone(tp.purge_once(folder), 'once per device')
            con = sqlite3.connect(os.path.join(folder, 'metacache.db'))
            self.assertEqual(con.execute("SELECT count(*) FROM metadata WHERE db_type = 'tvshow'").fetchone()[0], 1)
            con.close()
        # the saved lists hold each title's trailer: the mark written after the refresh is one of the files
        # they depend on, so they build again behind their first showing
        with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(log=lambda *a: None, LOGINFO=1, LOGWARNING=2)}):
            spec_s = importlib.util.spec_from_file_location('snap_trailer_test', WIZARD / 'resources/libs/patches/pov_list_snapshot.py')
            snap = importlib.util.module_from_spec(spec_s)
            spec_s.loader.exec_module(snap)
        self.assertIn(tp.PURGE_FLAG, snap.HASHED_FILES)
        startup = (WIZARD / 'startup.py').read_text('utf-8')
        self.assertIn("_pick.purge_once(xbmcvfs.translatePath('special://profile/addon_data/plugin.video.pov/'),", startup)
        self.assertIn("Thread(target=_trailer_pick_refresh, name='POVILTrailerPick', daemon=True).start()", startup, 'off the start-up path')


if __name__ == '__main__':
    unittest.main()
