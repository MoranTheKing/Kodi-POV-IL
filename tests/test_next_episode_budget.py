"""Recent-history previews are bounded without selecting arbitrary shows."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard/resources/libs/patches/pov_widget_budget.py'
spec = importlib.util.spec_from_file_location('next_episode_budget',path)
budget = importlib.util.module_from_spec(spec);spec.loader.exec_module(budget)


class NextEpisodeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'last_played':'2026-10-08T%02d:00:00' % i,'id':i} for i in range(24)]
        self.obj = types.SimpleNamespace(is_widget=True,list_type='next_episode_pov',
            params={'widget_limit':'12'},resinsert='2000-01-01',list=self.rows,items=[],
            nextep_settings={'sort_key':'pov_last_played','sort_direction':True,
                            'include_unaired':False,'sort_airing_today_to_top':False})
        self.processed = []
        self.skip = set()
        def native():
            self.processed.append([r['id'] for r in self.obj.list])
            return sorted([r for r in self.obj.list if r['id'] not in self.skip],
                          key=lambda r:r['last_played'],reverse=self.obj.nextep_settings['sort_direction'])
        self.native = native
        self.policy = None
        self.context = patch.dict(sys.modules, {'profile_age_guard':types.SimpleNamespace(active_policy=lambda:self.policy)})
        self.context.start();self.addCleanup(self.context.stop)

    def test_preview_selects_recent_entries_instead_of_database_order(self):
        result = budget.wrap_next_episode_worker(self.obj,self.native)()
        self.assertEqual([r['id'] for r in result],list(range(23,11,-1)))
        self.assertEqual(len(self.processed),1)
        self.assertEqual(len(self.processed[0]),12)
        self.assertIs(self.obj.list,self.rows)

    def test_completed_shows_backfill_to_keep_a_full_row(self):
        self.skip = set(range(15,24))
        result = budget.wrap_next_episode_worker(self.obj,self.native)()
        self.assertEqual([r['id'] for r in result],list(range(14,2,-1)))
        self.assertEqual([len(r) for r in self.processed],[12,24])
        self.assertIs(self.obj.list,self.rows)

    def test_ascending_sort_uses_native_last_played_order(self):
        self.obj.nextep_settings['sort_direction']=False
        self.assertEqual([r['id'] for r in budget.wrap_next_episode_worker(self.obj,self.native)()],list(range(12)))

    def test_other_sorts_today_child_and_full_directories_keep_native_worker(self):
        cases = [('sort_key','pov_name'),('sort_key','pov_first_aired'),
                 ('sort_airing_today_to_top',True)]
        for key,value in cases:
            before=self.obj.nextep_settings.copy()
            self.obj.nextep_settings[key]=value
            self.assertIs(budget.wrap_next_episode_worker(self.obj,self.native),self.native)
            self.obj.nextep_settings=before
        self.policy={'age':7}
        self.assertIs(budget.wrap_next_episode_worker(self.obj,self.native),self.native)
        self.policy=None
        self.obj.is_widget=False
        self.assertIs(budget.wrap_next_episode_worker(self.obj,self.native),self.native)
        self.obj.is_widget=True;self.obj.params={}
        self.assertIs(budget.wrap_next_episode_worker(self.obj,self.native),self.native)

    def test_native_failure_restores_source_list(self):
        def fail(): raise RuntimeError('worker failure')
        with self.assertRaises(RuntimeError): budget.wrap_next_episode_worker(self.obj,fail)()
        self.assertIs(self.obj.list,self.rows)

    def test_unaired_entries_do_not_displace_earlier_aired_episodes(self):
        self.obj.nextep_settings['include_unaired']=True
        class Item:
            def __init__(self, ident): self.ident=ident
            def getProperty(self, key): return 'true' if self.ident>=20 else 'false'
        def native():
            self.processed.append([r['id'] for r in self.obj.list])
            rows=[('',Item(r['id']),False) for r in self.obj.list]
            rows.sort(key=lambda r:r[1].ident,reverse=True)
            rows.sort(key=lambda r:r[1].getProperty('pov_unaired')=='true')
            return rows
        result=budget.wrap_next_episode_worker(self.obj,native)()
        self.assertEqual([r[1].ident for r in result],list(range(19,7,-1)))
        self.assertEqual([len(r) for r in self.processed],[12,24])
        self.assertIs(self.obj.list,self.rows)

    def test_hd_preview_art_keeps_explicit_original_custom_urls_and_other_art(self):
        class Item:
            def __init__(self, thumb): self.art={'thumb':thumb,'fanart':'keep-original-fanart'}
            def getArt(self, key): return self.art.get(key,'')
            def setArt(self, values): self.art.update(values)
        original='https://image.tmdb.org/t/p/original/episode.jpg'
        custom='https://custom.example/episode.jpg'
        items=[('',Item(original),False),('',Item(custom),False)]
        self.obj.meta_user_info={'image_resolution':{'still':'original','poster':'original'}}
        budget._preview_art(self.obj,items)
        self.assertEqual(items[0][1].getArt('thumb'),original)
        self.obj.meta_user_info['image_resolution']['poster']='w780'
        budget._preview_art(self.obj,items)
        self.assertEqual(items[0][1].getArt('thumb'),'https://image.tmdb.org/t/p/w1280/episode.jpg')
        self.assertEqual(items[1][1].getArt('thumb'),custom)
        self.assertEqual(items[0][1].getArt('fanart'),'keep-original-fanart')


if __name__ == '__main__': unittest.main()
