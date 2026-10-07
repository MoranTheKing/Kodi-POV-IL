"""Defer POV 6.10.05's shared HTTP clients until a client is actually used.

Cached directories need adapters configured at import time, but no network
client. Replay those mounts into the unmodified upstream session, including
its timeouts, retry classes, default headers and low-level pool. All other
attributes immediately delegate to that same native implementation.
"""
import hashlib
import importlib.util
import sys
import threading
import types

SESSION_SHA256 = '4f9ece685c857d6f0f596c290dd78cf04b237ca852539fb65be3e9df845bfc2c'
_install_lock = threading.Lock()


def _bounded_retry(retry):
    # Upstream total=None + unset error counters permits endless retries
    # (including TLS failures). Keep its status retry, delay and method rules,
    # but let a failed provider return to the UI. Explicit finite totals stay.
    if retry.total is None:
        return retry.new(total=2, connect=1 if retry.connect is None else retry.connect,
                         read=1 if retry.read is None else retry.read,
                         other=0 if retry.other is None else retry.other)
    return retry


class _Constructor:
    def __init__(self, owner, name, args, kwargs):
        self._owner = owner
        self._name = name
        self._args = args
        self._kwargs = kwargs
        self._value = None

    def resolve(self):
        with self._owner.lock:
            if self._value is None:
                module = self._owner.load()
                self._value = getattr(module, self._name)(
                    *self._owner.arguments(self._args), **self._owner.arguments(self._kwargs))
                if self._name == 'Retry':
                    self._value = _bounded_retry(self._value)
            return self._value

    def __getattr__(self, name):
        return getattr(self.resolve(), name)


class _Client:
    def __init__(self, owner, name):
        self._owner = owner
        self._name = name
        self._mounts = []
        self._value = None

    def resolve(self):
        with self._owner.lock:
            if self._value is None:
                value = getattr(self._owner.load(), self._name)
                for prefix, adapter in self._mounts:
                    value.mount(prefix, self._owner.arguments(adapter))
                self._mounts.clear()
                self._value = value
            return self._value

    def mount(self, prefix, adapter):
        with self._owner.lock:
            if self._value is None:
                self._mounts.append((prefix, adapter))
            else:
                self._value.mount(prefix, self._owner.arguments(adapter))

    def request(self, *args, **kwargs):
        # A caller can capture this bound method (e.g. Trakt's reauth hook)
        # without loading either HTTP library until the request is sent.
        return self.resolve().request(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.resolve(), name)

    def __setattr__(self, name, value):
        if name.startswith('_'):
            object.__setattr__(self, name, value)
        else:
            setattr(self.resolve(), name, value)


class _SessionModule(types.ModuleType):
    def __init__(self, path, source):
        super().__init__('session')
        self.__file__ = path
        self._source = source
        self.lock = threading.RLock()
        self._native = None
        self.session = _Client(self, 'session')
        self.http = _Client(self, 'http')
        self.HTTPAdapter = lambda *args, **kwargs: _Constructor(self, 'HTTPAdapter', args, kwargs)
        self.Retry = lambda *args, **kwargs: _Constructor(self, 'Retry', args, kwargs)

    def arguments(self, value):
        if isinstance(value, _Constructor):
            return value.resolve()
        if isinstance(value, dict):
            return {k: self.arguments(v) for k,v in value.items()}
        if isinstance(value, tuple):
            return tuple(self.arguments(v) for v in value)
        if isinstance(value, list):
            return [self.arguments(v) for v in value]
        return value

    def load(self):
        with self.lock:
            if self._native is None:
                # A distinct name leaves the shared proxy stable while worker
                # threads import it. Execute the original file, not a copied
                # HTTP implementation or a modified requests namespace.
                spec = importlib.util.spec_from_file_location('_povil_native_session', self.__file__)
                module = importlib.util.module_from_spec(spec)
                # Use the bytes verified at installation. A concurrent host
                # update must not switch the client contract halfway through
                # this invocation's deferred initialization.
                exec(compile(self._source, self.__file__, 'exec'), module.__dict__)
                module.retry = _bounded_retry(module.retry)
                module.http.connection_pool_kw['retries'] = module.retry
                sys.modules[spec.name] = module
                self._native = module
            return self._native

    def __getattr__(self, name):
        # Python probes package metadata during `from session import ...`.
        # Such probes must not defeat lazy loading of this plain module.
        if name.startswith('__'):
            raise AttributeError(name)
        return getattr(self.load(), name)


def install(path, version):
    """Only the verified upstream contract is deferred; other hosts pass through."""
    with _install_lock:
        if version != '6.10.05' or 'session' in sys.modules:
            return False
        try:
            with open(path, 'rb') as handle:
                source = handle.read()
                digest = hashlib.sha256(source.replace(b'\r\n', b'\n')).hexdigest()
            if digest != SESSION_SHA256:
                return False
        except OSError:
            return False
        sys.modules['session'] = _SessionModule(path, source)
        return True
