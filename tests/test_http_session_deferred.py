"""Native HTTP contract, cold imports, concurrency and unknown-host fallback."""
import concurrent.futures
import contextlib
import http.server
import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'plugin.program.kodipovilwizard/resources/libs/patches/pov_http_session.py'
FIXTURE = ROOT/'tests/fixtures/http_session/session.py'
spec = importlib.util.spec_from_file_location('deferred_http_test', SOURCE)
lazy = importlib.util.module_from_spec(spec); spec.loader.exec_module(lazy)


class SharedHttpTests(unittest.TestCase):
    def setUp(self):
        self.saved = {key:sys.modules.get(key) for key in ('session','_povil_native_session')}
        for key in self.saved: sys.modules.pop(key, None)
        self.addCleanup(self.restore)

    def restore(self):
        module = sys.modules.pop('session', None)
        if isinstance(module, lazy._SessionModule) and module._native:
            module._native.session.close()
            module._native.http.clear()
        for key,value in self.saved.items():
            sys.modules.pop(key, None)
            if value is not None:sys.modules[key] = value

    def install(self):
        self.assertTrue(lazy.install(str(FIXTURE),'6.10.05'))
        return sys.modules['session']

    def server(self):
        lock = threading.Lock(); counts = {}; seen = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                with lock:
                    counts[self.path] = counts.get(self.path,0)+1
                    retry = self.path=='/retry' and counts[self.path]==1
                    seen.append((self.path,self.headers.get('Authorization')))
                data = json.dumps({'path':self.path,'auth':self.headers.get('Authorization')}).encode()
                self.send_response(503 if retry else 200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length','0')))
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:%s'%server.server_port,counts,seen

    def test_cold_configuration_does_not_import_network_libraries(self):
        code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('lazy',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.install(sys.argv[2],'6.10.05')
from session import session,HTTPAdapter,Retry
session.mount('https://example.test',HTTPAdapter(pool_maxsize=100,max_retries=Retry(total=None,status=1,status_forcelist=(429,502,503,504),backoff_factor=1)))
assert 'requests' not in sys.modules and 'urllib3' not in sys.modules
assert not m.install(sys.argv[2],'6.10.05')
"""
        subprocess.run([sys.executable,'-c',code,str(SOURCE),str(FIXTURE)],check=True,capture_output=True)

    def test_connected_trakt_wrapper_keeps_shared_client_deferred(self):
        code = """import importlib.util,sys,types
spec=importlib.util.spec_from_file_location('lazy',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.install(sys.argv[2],'6.10.05')
from session import session,HTTPAdapter,Retry
session.mount('https://api.trakt.tv/',HTTPAdapter(max_retries=Retry(total=None,status=1)))
original_request=session.request
sys.modules['xbmcgui']=types.SimpleNamespace()
spec=importlib.util.spec_from_file_location('reauth',sys.argv[3]);reauth=importlib.util.module_from_spec(spec);spec.loader.exec_module(reauth)
target=types.SimpleNamespace(session=session,call_trakt=lambda *a,**k:[],
    get_setting=lambda key,default='':'connected',kodi_utils=types.SimpleNamespace(sleep=lambda _:None))
reauth.run(target)
assert 'requests' not in sys.modules and 'urllib3' not in sys.modules
assert session.request==original_request
assert target.session is not session
assert target.call_trakt('shows/trending')==[]
assert sys.modules['session']._native is None
"""
        subprocess.run([sys.executable,'-c',code,str(SOURCE),str(FIXTURE),
                        str(SOURCE.with_name('pov_trakt_reauth.py'))],check=True,capture_output=True)

    def test_unknown_versions_content_and_existing_modules_are_preserved(self):
        self.assertFalse(lazy.install(str(FIXTURE),'6.10.06'))
        self.assertNotIn('session',sys.modules)
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'session.py';path.write_text('unrecognized source')
            self.assertFalse(lazy.install(str(path),'6.10.05'))
            self.assertNotIn('session',sys.modules)
        existing=object();sys.modules['session']=existing
        self.assertFalse(lazy.install(str(FIXTURE),'6.10.05'))
        self.assertIs(sys.modules['session'],existing)

    def test_replay_uses_native_retries_timeouts_headers_and_adapter_order(self):
        url,counts,seen=self.server();module=self.install()
        retry=module.Retry(total=None,status=1,status_forcelist=(503,),backoff_factor=0)
        first=module.HTTPAdapter(pool_maxsize=2)
        second=module.HTTPAdapter(pool_maxsize=7,max_retries=retry)
        module.session.mount(url,first);module.session.mount(url,second)
        self.assertIsNone(module._native)
        response=module.session.request('get',url+'/retry',headers={'Authorization':'Bearer TEST'},timeout=2)
        self.assertEqual(response.json(),{'path':'/retry','auth':'Bearer TEST'})
        self.assertEqual(counts['/retry'],2)
        self.assertEqual(module.session.timeout,(3.05,6.05))
        self.assertIn('User-Agent',module.session.headers)
        adapter=module.session.get_adapter(url)
        self.assertEqual(adapter._pool_maxsize,7)
        self.assertIsInstance(adapter,module._native.HTTPAdapter)
        self.assertIsInstance(adapter.max_retries,module._native.Retry)
        self.assertEqual(adapter.max_retries.status_forcelist,(503,))
        self.assertEqual(adapter.max_retries.total,2)
        self.assertEqual(adapter.max_retries.connect,1)
        self.assertEqual(adapter.max_retries.read,1)
        self.assertEqual(adapter.max_retries.other,0)
        module.session.mount(url,module.HTTPAdapter(pool_maxsize=3))
        self.assertEqual(module.session.get_adapter(url)._pool_maxsize,3)
        with module.session.request('post',url+'/post',json={'page':2},stream=True,timeout=2) as response:
            self.assertEqual(response.json(),{'page':2})

    def test_header_and_timeout_mutations_and_low_level_pool_delegate(self):
        url,counts,seen=self.server();module=self.install()
        module.session.headers.update({'Authorization':'Bearer LOCAL'})
        module.session.timeout=(.2,.4)
        self.assertEqual(module.session.request('get',url+'/session').json()['auth'],'Bearer LOCAL')
        self.assertEqual(module._native.session.timeout,(.2,.4))
        module.http.headers.update({'X-Fixture':'pool'})
        self.assertEqual(module.http.request('get',url+'/pool').status,200)
        self.assertIs(module.http.resolve(),module._native.http)
        self.assertIs(module.TimeoutSession,module._native.TimeoutSession)

    def test_concurrent_first_requests_share_one_native_session(self):
        url,counts,seen=self.server();module=self.install()
        module.session.mount(url,module.HTTPAdapter(pool_maxsize=8))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows=list(pool.map(lambda i:module.session.request('get',url+'/?page=%s'%i,timeout=4).json(),range(16)))
        self.assertEqual([r['path'] for r in rows],['/?page=%s'%i for i in range(16)])
        self.assertIs(module.session.resolve(),module._native.session)
        self.assertEqual(sum(counts.values()),16)
        self.assertEqual(module.session.get_adapter(url)._pool_maxsize,8)

    def test_native_connection_errors_remain_catchable(self):
        module=self.install()
        with contextlib.closing(socket.socket()) as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        caught=False
        try:module.session.request('get','http://127.0.0.1:%s/'%port,timeout=.1)
        except module.session.CUSTOM_ERRORS:caught=True
        self.assertTrue(caught)

    def test_request_capture_stays_deferred_and_native_retries_are_bounded(self):
        module=self.install()
        request=module.session.request
        self.assertIsNone(module._native)
        module.session.mount('https://example.test',module.HTTPAdapter(max_retries=module.Retry(
            total=None,status=1,status_forcelist=(429,503),backoff_factor=1)))
        native=module.session.resolve()
        for retry in (native.get_adapter('https://example.test').max_retries,
                      module.http.resolve().connection_pool_kw['retries']):
            self.assertEqual((retry.total,retry.connect,retry.read,retry.other),(2,1,1,0))
            self.assertEqual(retry.status,1)
            self.assertIn(503,retry.status_forcelist)
        finite=module.Retry(total=4,connect=2,read=0).resolve()
        self.assertEqual((finite.total,finite.connect,finite.read),(4,2,0))

    def test_tls_failure_is_not_retried_without_end(self):
        module=self.install()
        retry=module.Retry(total=None,status=1,backoff_factor=1).resolve()
        urllib3=module._native.urllib3
        with self.assertRaises(urllib3.exceptions.MaxRetryError):
            retry.increment(method='GET',error=urllib3.exceptions.SSLError('fixture TLS failure'))

    def test_dns_failure_returns_after_one_connection_retry(self):
        module=self.install()
        retry=module.Retry(total=None,status=1,backoff_factor=1).resolve()
        urllib3=module._native.urllib3
        error=urllib3.exceptions.NameResolutionError('example.test',None,socket.gaierror('fixture DNS failure'))
        retry=retry.increment(method='GET',error=error)
        self.assertEqual((retry.total,retry.connect),(1,0))
        with self.assertRaises(urllib3.exceptions.MaxRetryError):
            retry.increment(method='GET',error=error)

    def test_verified_source_snapshot_survives_a_concurrent_host_update(self):
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'session.py';path.write_bytes(FIXTURE.read_bytes().replace(b'\n',b'\r\n'))
            self.assertTrue(lazy.install(str(path),'6.10.05'))
            module=sys.modules['session']
            path.write_text('raise RuntimeError("new host during invocation")')
            self.assertEqual(module.session.timeout,(3.05,6.05))


if __name__=='__main__':unittest.main()
