"""Wizard 0.4.81: a damaged POV cache no longer turns every search into
"No Results".

Field report (24 Oct 2026, LG webOS TV, POV 6.10.22): after the disk filled,
providerscache.db was "database disk image is malformed". POV writes each
provider's results to that cache before adding them to the list, the write
raised, results()'s bare except swallowed it, and every provider returned
nothing -- over 2,000 counted, "No Results" shown, nothing in the log.

1. pov_cache_guard: a failed cache write costs only the cache.
2. pov_cache_repair: at start-up a cache SQLite reports as damaged is deleted
   (POV rebuilds it); a locked one, and POV's user data, are left alone.
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

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'


def _load(name, path, modules):
    with mock.patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class CacheGuardTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        xbmc = types.SimpleNamespace(LOGWARNING=2, log=lambda m, l=0: self.logs.append(m))
        self.mod = _load('pov_cache_guard_t', ROOT / 'resources/libs/patches/pov_cache_guard.py',
                         {'xbmc': xbmc})

    def test_results_survive_a_failed_cache_write(self):
        class ExternalProvidersCache(object):
            def get(self, *a):
                return None

            def set(self, *a):
                raise sqlite3.DatabaseError('database disk image is malformed')

        self.mod.guard(ExternalProvidersCache)
        self.mod.guard(ExternalProvidersCache)          # idempotent

        # POV 6.10.22 get_movie_source, reduced to its order of calls
        found = []
        epc = ExternalProvidersCache()
        sources = epc.get()
        if sources is None:
            sources = [{'name': 'Inception.2010.1080p'}]
            epc.set('provider', 'movie', sources)
        found.extend(sources)
        epc.set('again')

        self.assertEqual(1, len(found))
        self.assertEqual(1, len(self.logs))             # logged once
        self.assertIn('malformed', self.logs[0])


class CacheRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, 'pov')
        os.makedirs(self.folder)
        self.state = os.path.join(self.tmp.name, 'pov_cache_ok.json')
        self.logs = []
        self.builtins = []
        xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2,
                                     executebuiltin=self.builtins.append)
        common = types.ModuleType('resources.libs.common')
        common.logging = types.SimpleNamespace(
            log=lambda m, level=0: self.logs.append(m))
        self.mod = _load('pov_cache_repair_t', ROOT / 'resources/libs/pov_cache_repair.py', {
            'xbmc': xbmc,
            'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: (
                self.folder if 'plugin.video.pov' in p else self.state)),
            'resources': types.ModuleType('resources'),
            'resources.libs': types.ModuleType('resources.libs'),
            'resources.libs.common': common,
            'resources.libs.common.logging': common.logging})

    def db(self, name, rows=400):
        path = os.path.join(self.folder, name)
        con = sqlite3.connect(path)
        con.execute('CREATE TABLE results_data (id INTEGER PRIMARY KEY, results TEXT)')
        con.executemany('INSERT INTO results_data (results) VALUES (?)',
                        [('x' * 300,) for _ in range(rows)])
        con.commit()
        con.close()
        os.utime(path, (1000000, 1000000))              # not written just now
        return path

    def corrupt(self, path):
        with open(path, 'r+b') as f:
            f.seek(4096 + 10)                           # inside page 2
            f.write(b'\xff' * 2000)

    def test_a_damaged_cache_is_removed_and_pov_rebuilds_it(self):
        bad = self.db('providerscache.db')
        self.corrupt(bad)
        good = self.db('metacache.db')
        self.assertEqual(['providerscache.db'], self.mod.run_at_startup())
        self.assertFalse(os.path.exists(bad))
        self.assertTrue(os.path.exists(good))
        self.assertEqual(['RunPlugin(plugin://plugin.video.pov/?mode=clean_databases)'],
                         self.builtins)

    def test_healthy_caches_cost_nothing(self):
        self.db('providerscache.db')
        self.assertEqual([], self.mod.run_at_startup())
        self.assertEqual([], self.builtins)

    def test_a_locked_cache_is_not_damaged(self):
        path = self.db('debridcache.db')
        holder = sqlite3.connect(path, isolation_level=None)
        holder.execute('BEGIN EXCLUSIVE')
        self.addCleanup(holder.close)
        self.mod.sqlite3 = types.SimpleNamespace(
            connect=lambda p, timeout=5: sqlite3.connect(p, timeout=0.1),
            DatabaseError=sqlite3.DatabaseError)
        self.assertFalse(self.mod.damaged(path))
        self.assertEqual([], self.mod.repair(self.folder))
        self.assertFalse(os.path.exists(self.state))    # not checked = not recorded

    def test_an_unchanged_file_is_not_read_again(self):
        path = self.db('metacache.db')
        self.assertEqual([], self.mod.repair())
        calls = []
        real = self.mod.check
        self.mod.check = lambda p: calls.append(p) or real(p)
        self.assertEqual([], self.mod.repair())
        self.assertEqual([], calls)                     # same size and time
        self.corrupt(path)                              # POV wrote to it
        os.utime(path, (1, 1))
        self.assertEqual(['metacache.db'], self.mod.repair())
        self.assertEqual(1, len(calls))

    def test_a_locked_damaged_cache_is_not_recorded_and_goes_next_start(self):
        path = self.db('providerscache.db')
        self.corrupt(path)
        holder = sqlite3.connect(path, isolation_level=None)
        holder.execute('BEGIN EXCLUSIVE')
        real_sqlite3 = self.mod.sqlite3
        self.mod.sqlite3 = types.SimpleNamespace(
            connect=lambda p, timeout=1: sqlite3.connect(p, timeout=0.1),
            DatabaseError=sqlite3.DatabaseError)
        self.assertEqual('unchecked', self.mod.check(path))
        self.assertEqual([], self.mod.repair())
        holder.close()
        self.mod.sqlite3 = real_sqlite3
        self.assertEqual(['providerscache.db'], self.mod.repair())

    def test_a_file_written_this_moment_is_not_recorded(self):
        path = self.db('debridcache.db')
        os.utime(path, None)                            # now
        self.assertEqual([], self.mod.repair())
        self.assertFalse(os.path.exists(self.state))

    def test_user_data_is_never_checked(self):
        for name in ('watched.db', 'favourites.db', 'navigator.db', 'views.db',
                     'traktcache.db', 'mdblcache.db'):
            self.corrupt(self.db(name))
        self.assertEqual([], self.mod.repair(self.folder))
        self.assertEqual(6, len(os.listdir(self.folder)))

    def test_startup_runs_it_after_the_storage_check(self):
        text = (ROOT / 'startup.py').read_text(encoding='utf-8')
        self.assertLess(text.index('storage_guard.run_at_startup()'),
                        text.index('pov_cache_repair.run_at_startup()'))
        self.assertLess(text.index('pov_cache_repair.run_at_startup()'),
                        text.index('_mu.run_update_check()'))


if __name__ == '__main__':
    unittest.main()
