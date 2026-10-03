"""Exercise native provider filters and page slices through the build merge."""
import runpy
import sys
import types
import unittest
from operator import itemgetter
from unittest.mock import patch
from test_personal_list_order import ROOT, FIX, WIZ, logic, load

merge = load('qa_merged_personal', WIZ / 'pov_my_lists.py')


def native(media, release_sort=False, paginate=True, sentinel=True):
    entry = next(e for e in runpy.run_path(str(WIZ / 'patches_config.py'))['PATCH_CONFIG']
                 if e['id'] == 'pov_merged_personal_pagination')
    source = (FIX / 'paginate.py').read_text('utf8')
    if sentinel:
        source = source.replace(entry['anchor'], entry['hook'] + entry['anchor'])
    ns = {'chunks': lambda data, limit: [data[i:i+limit] for i in range(0, len(data), limit)]}
    exec(source, ns)
    settings = types.SimpleNamespace(lists_sort_order=lambda *a: 2 if release_sort else 1,
        paginate=lambda: paginate, page_limit=lambda: 2, show_unaired_watchlist=lambda: True)
    calls = []
    collection = [{'collected_at': '2026-01-01T00:00:00Z', 'premiered': '2020',
                   'title': 'old', 'media_ids': {'tmdb': 1}, 'id': 1, 'year': 2020},
                  {'collected_at': '2026-01-02T00:00:00Z', 'premiered': '2020',
                   'title': 'duplicate', 'media_ids': {'tmdb': 2}, 'id': 2, 'year': 2020}]
    watchlist = [{'collected_at': '2026-10-03T00:00:00Z', 'watchlist_at': '2026-10-03T00:00:00Z',
                  'premiered': '2020', 'release_date': '2020', 'title': 'new', 'media_ids': {'tmdb': 9}, 'id': 9},
                 {'collected_at': '2026-10-02T00:00:00Z', 'watchlist_at': '2026-10-02T00:00:00Z',
                  'premiered': '2020', 'release_date': '2020', 'title': 'readded', 'media_ids': {'tmdb': 2}, 'id': 2}]
    def fetch(kind, _media):
        calls.append(kind)
        return [dict(i) for i in (collection if kind == 'collection' else watchlist if kind == 'watchlist' else [])]
    ns.update(settings=settings, itemgetter=itemgetter, trakt_fetch_collection_watchlist=fetch,
              mdbl_collection_watchlist_items=fetch)
    exec((FIX / ('merged_trakt.py' if media == 'trakt' else 'merged_mdblist.py')).read_text('utf8'), ns)
    funcs = [(ns[name], name) for name in (('trakt_collection', 'trakt_watchlist', 'trakt_favorites')
             if media == 'trakt' else ('mdblist_collection', 'mdblist_watchlist'))]
    return settings, ns, funcs, calls


class MergedPersonalOrderTests(unittest.TestCase):
    def invoke(self, provider, page=1, **kwargs):
        settings, ns, funcs, calls = native(provider, **kwargs)
        with patch.dict(sys.modules, {'modules': types.SimpleNamespace(settings=settings,
                utils=types.SimpleNamespace(paginate_list=ns['paginate_list'])),
                'pov_mdblist_patch_logic': logic}):
            result = (merge._merge_trakt if provider == 'trakt' else merge._merge_tmdb_or_mdblist)(funcs, 'shows', page)
        return result, calls

    def test_watchlist_new_series_precedes_collection_and_duplicate_readdition(self):
        for provider in ('trakt', 'mdblist'):
            (items, pages), calls = self.invoke(provider)
            ids = [i['tmdb'] for i in items] if provider == 'trakt' else items
            self.assertEqual(ids, [9, 2])
            self.assertEqual(pages, 2)
            self.assertEqual(len(calls), 3 if provider == 'trakt' else 2)

    def test_combined_pagination_has_no_duplicate_or_missing_items(self):
        for provider in ('trakt', 'mdblist'):
            (items, pages), _ = self.invoke(provider, page=2)
            self.assertEqual([i['tmdb'] for i in items] if provider == 'trakt' else items, [1])
            self.assertEqual(pages, 2)
            self.assertEqual(self.invoke(provider, page=3)[0], ([], 2))

    def test_no_pagination_still_sorts_all_sources_and_deduplicates(self):
        for provider in ('trakt', 'mdblist'):
            (items, pages), _ = self.invoke(provider, paginate=False)
            self.assertEqual([i['tmdb'] for i in items] if provider == 'trakt' else items, [9, 2, 1])
            self.assertEqual(pages, 1)

    def test_explicit_release_sort_and_staggered_unpatched_host_use_native_path(self):
        for provider in ('trakt', 'mdblist'):
            for kwargs in ({'release_sort': True}, {'sentinel': False}):
                (items, _), _ = self.invoke(provider, **kwargs)
                expected = [1, 2, 9] if kwargs.get('release_sort') else [2, 1, 9]
                self.assertEqual([i['tmdb'] for i in items] if provider == 'trakt' else items, expected)

    def test_native_regular_pages_and_empty_lists_are_unchanged(self):
        _, ns, _, _ = native('trakt')
        self.assertEqual(ns['paginate_list']([1, 2, 3], 2, 2), ([3], 2))
        self.assertEqual(ns['paginate_list']([], 3, 2), ([], 3))


if __name__ == '__main__':
    unittest.main()
