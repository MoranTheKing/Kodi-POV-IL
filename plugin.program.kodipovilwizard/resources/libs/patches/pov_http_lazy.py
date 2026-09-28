# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_http_lazy.py

import sys
import threading

class LazyRetry:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

class LazyHTTPAdapter:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

class LazyAdapters:
    Retry = LazyRetry
    HTTPAdapter = LazyHTTPAdapter

class LazySession:
    """Records HTTP configurations without loading SSL/Urllib3 contexts."""

    def __init__(self, lazy_req):
        self.lazy_req = lazy_req
        self._recorded_mounts = []
        self._headers = {}
        self._real_session = None
        self._lock = threading.Lock()

    @property
    def headers(self):
        # Allow Trakt to perform `session.headers.update(...)` onto a native dict
        if self._real_session:
            return self._real_session.headers
        return self._headers

    def mount(self, prefix, adapter):
        if self._real_session:
            self._real_session.mount(prefix, adapter)
        else:
            self._recorded_mounts.append((prefix, adapter))

    def _get_real_session(self):
        if not self._real_session:
            with self._lock:
                if not self._real_session:
                    # 1. Realize the true requests library
                    req = self.lazy_req._realize()

                    # 2. Re-create the native session
                    rs = req.Session()

                    # 3. Replay headers
                    rs.headers.update(self._headers)

                    # 4. Replay mounts with real Adapter and Retry classes
                    for prefix, adapter in self._recorded_mounts:
                        if isinstance(adapter, LazyHTTPAdapter):
                            kwargs = dict(adapter.kwargs)
                            if 'max_retries' in kwargs and isinstance(kwargs['max_retries'], LazyRetry):
                                lr = kwargs['max_retries']
                                kwargs['max_retries'] = req.adapters.Retry(*lr.args, **lr.kwargs)
                            real_adapter = req.adapters.HTTPAdapter(*adapter.args, **kwargs)
                        else:
                            real_adapter = adapter

                        rs.mount(prefix, real_adapter)

                    self._real_session = rs
        return self._real_session

    def request(self, *args, **kwargs):
        return self._get_real_session().request(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self._get_real_session().get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self._get_real_session().post(*args, **kwargs)


class LazyRequests:
    """Thread-safe sys.modules proxy to defer requests library initialization."""

    def __init__(self):
        self._real_requests = None
        self._lock = threading.Lock()

    def _realize(self):
        if not self._real_requests:
            with self._lock:
                if not self._real_requests:
                    # Drop proxy from sys.modules so standard import grabs the real deal
                    if sys.modules.get('requests') is self:
                        del sys.modules['requests']

                    import requests
                    self._real_requests = requests
        return self._real_requests

    @property
    def adapters(self):
        if self._real_requests:
            return self._real_requests.adapters
        return LazyAdapters()

    def Session(self):
        if self._real_requests:
            return self._real_requests.Session()
        return LazySession(self)

    def __getattr__(self, name):
        """Catch-all for variables like exceptions (requests.RequestException)"""
        return getattr(self._realize(), name)


def run():
    """
    Injects a temporary, thread-safe proxy into sys.modules to prevent the
    heavy requests module from eagerly loading during cold boot widget rendering.
    Safe against global state: if requests is already loaded, it skips execution.
    """
    if 'requests' not in sys.modules:
        sys.modules['requests'] = LazyRequests()