"""Actual POV/Umbrella watched schemas: exposure seeds are not completed shows."""
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]/'addons/service.subtitles.kodipovilai/resources/lib/tonight'
spec=importlib.util.spec_from_file_location('tonight_history_test',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
pkg=importlib.util.module_from_spec(spec);sys.modules[spec.name]=pkg;spec.loader.exec_module(pkg)
from tonight_history_test import history
class HistorySchemas(unittest.TestCase):
    def fixture(self,kind):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=Path(temp.name)/'watched.db';db=sqlite3.connect(p)
        if kind=='pov':
            db.execute('CREATE TABLE watched_status (db_type TEXT,media_id TEXT,season INTEGER,episode INTEGER,last_played TEXT,title TEXT,UNIQUE(db_type,media_id,season,episode))')
            db.executemany('INSERT INTO watched_status VALUES(?,?,?,?,?,?)',[
                ('movie','900',0,0,'2026-09-01','synthetic'),('episode','12',1,1,'2026-09-03','synthetic'),
                ('episode','12',1,2,'2026-09-04','synthetic'),('movie','3',0,0,'2026-09-02','synthetic')])
        else:
            db.execute('CREATE TABLE watched(media_type TEXT,imdb_id TEXT,tmdb_id TEXT,season INTEGER,episode INTEGER,title TEXT,last_played TEXT,overlay INTEGER,UNIQUE(imdb_id,tmdb_id,season,episode))')
            db.executemany('INSERT INTO watched VALUES(?,?,?,?,?,?,?,?)',[
                ('movie','tt900','900',0,0,'synthetic','100',5),('episode','tt12','12',1,1,'synthetic','300',5),
                ('episode','tt12','12',1,2,'synthetic','400',5),('movie','tt3','3',0,0,'synthetic','200',5),
                ('episode','tt7','7',1,1,'synthetic','500',4)])
        db.commit();db.close();return p
    def test_actual_schemas_series_seeds_recency_and_readonly(self):
        for kind,read in [('pov',history.read_watched),('umbrella',history.read_umbrella_local)]:
            with self.subTest(kind=kind):
                p=self.fixture(kind);before=p.read_bytes();result=read(p)
                self.assertEqual(result['keys'],['movie:3','movie:900'])
                self.assertEqual(result['seed_keys'],['tvshow:12','movie:3','movie:900'])
                self.assertEqual(result['observed_series'],['tvshow:12'])
                self.assertEqual(result['reason'],'viewing_is_not_liking')
                self.assertEqual(result['order'],'recent_first')
                self.assertEqual(p.read_bytes(),before)
    def test_selected_pov_cache_matches_credentials_gate(self):
        self.assertEqual(history.selected_database({'watched_indicators':'2'}),'watched.db')
        self.assertEqual(history.selected_database({'watched_indicators':'2','mdblist_user':'present'}),'mdblcache.db')
        self.assertEqual(history.selected_database({'watched_indicators':'1','trakt_user':'present'}),'traktcache.db')
    def test_missing_database_remains_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'missing.db'
            self.assertEqual(history.read_watched(p)['status'],'unknown');self.assertFalse(p.exists())
    def test_older_schema_no_timestamp_does_not_claim_recency(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'older.db';db=sqlite3.connect(p)
            db.execute('CREATE TABLE watched_status(db_type TEXT,media_id TEXT)')
            db.execute("INSERT INTO watched_status VALUES('episode','12')");db.commit();db.close()
            result=history.read_watched(p)
            self.assertEqual(result['order'],'unknown');self.assertEqual(result['keys'],[])
            self.assertEqual(result['seed_keys'],['tvshow:12'])
if __name__=='__main__':unittest.main()
