"""Provider routes must fit the native client and bypass stale company results."""
import runpy
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT=Path(__file__).resolve().parents[1]
CONFIG=runpy.run_path(str(ROOT/'plugin.program.kodipovilwizard/resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
RULE=next(row for row in CONFIG if row['id']=='pov_movie_networks_providers_fix')


class MovieProviderRequestTests(unittest.TestCase):
    def build(self, provider, page=1, legacy=False, base='https://api.themoviedb.org'):
        captured={}
        def get_tmdb(url):
            full=url if legacy else base+url
            captured['request']=full
            return {'results':[{'id':page*100+int(provider)}],'page':page,'total_pages':3}
        def cache(function,key,url,expiration):
            captured.update(key=key,url=url,expiration=expiration)
            return function(url)
        namespace={'base_url':base,'EXPIRES_2_DAYS':48,'cache_object':cache,'get_tmdb':get_tmdb}
        if legacy:namespace['requests']=object()
        # Embed the actual published hook in the host function's anchored body.
        source=('def tmdb_movies_networks(network_id, page_no):\n'
                "\tstring = 'tmdb_movies_networks_%s_%s' % (network_id, page_no)\n"
                "\turl = '/3/discover/movie?language=en-US&region=US&page=%s' % page_no\n"
                +RULE['anchor']+'\n'+RULE['hook']+
                '\treturn cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)\n')
        exec(compile(source,'provider_host.py','exec'),namespace)
        result=namespace['tmdb_movies_networks'](provider,page)
        return result,captured

    def test_native_requests_have_one_host_one_api_version_and_provider_filters(self):
        for provider in ('8','337','350'):
            result,call=self.build(provider)
            url=urlsplit(call['request']);query=parse_qs(url.query)
            self.assertEqual(url.scheme,'https');self.assertEqual(url.netloc,'api.themoviedb.org')
            self.assertEqual(url.path,'/3/discover/movie')
            self.assertEqual(query['with_watch_providers'],[provider])
            self.assertEqual(query['watch_region'],['US'])
            self.assertEqual(query['with_watch_monetization_types'],['flatrate'])
            self.assertNotIn('with_companies',query)
            self.assertTrue(result['results'])

    def test_legacy_full_url_contract_does_not_duplicate_api_version(self):
        for base in ('https://api.themoviedb.org','https://api.themoviedb.org/3'):
            result,call=self.build('337',legacy=True,base=base)
            self.assertEqual(urlsplit(call['request']).path,'/3/discover/movie')
            self.assertEqual(urlsplit(call['request']).netloc,'api.themoviedb.org')
            self.assertTrue(result['results'])

    def test_page_and_provider_have_distinct_caches_and_native_pagination(self):
        keys=[]
        for provider,page in (('8',1),('8',2),('337',1)):
            result,call=self.build(provider,page)
            self.assertEqual(parse_qs(urlsplit(call['request']).query)['page'],[str(page)])
            self.assertEqual(result['page'],page);self.assertEqual(result['total_pages'],3)
            self.assertEqual(call['expiration'],48)
            self.assertNotEqual(call['key'],'tmdb_movies_networks_%s_%s'%(provider,page))
            keys.append(call['key'])
        self.assertEqual(len(set(keys)),3)


if __name__=='__main__':unittest.main()
