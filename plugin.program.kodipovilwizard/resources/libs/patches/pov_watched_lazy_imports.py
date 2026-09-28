# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_watched_lazy_imports.py

import sys
import xbmc

DUMMY_MODULES = [
    'caches.mdbl_cache',
    'caches.trakt_cache',
    'indexers.local_api',
    'indexers.mdblist_api',
    'indexers.trakt_api'
]

class DummyModule:
    """Intercepts attribute requests to satisfy 'from X import Y' syntax smoothly."""
    def __getattr__(self, name):
        return self

    def __call__(self, *args, **kwargs):
        return None

def mock_modules():
    """
    Injects dummies into sys.modules BEFORE the upstream parser reaches the imports.
    This safely prevents disk reading and heavy CPU parsing on 32-bit platforms.
    """
    try:
        for mod in DUMMY_MODULES:
            if mod not in sys.modules:
                sys.modules[mod] = DummyModule()
    except Exception as e:
        xbmc.log(f"[WIZARD-PATCH] Error mocking lazy imports: {e}", xbmc.LOGWARNING)

class LazyProxy:
    """
    A callable proxy that performs the real import (only when actually invoked)
    and forwards the call transparently to the native API endpoint.
    """
    def __init__(self, module_name, func_name):
        self.module_name = module_name
        self.func_name = func_name

    def __call__(self, *args, **kwargs):
        try:
            real_mod = __import__(self.module_name, fromlist=[self.func_name])
            real_func = getattr(real_mod, self.func_name)
            return real_func(*args, **kwargs)
        except Exception as e:
            xbmc.log(f"[WIZARD-PATCH] Error executing LazyProxy for {self.func_name}: {e}", xbmc.LOGERROR)
            return None

def apply_proxies(global_vars):
    """
    Shadows the intercepted variables in watched_cache.py's global dictionary
    with the callable proxies, then deletes the dummies from sys.modules so standard
    imports in other parts of the addon aren't crippled.
    """
    try:
        proxies = {
            'clear_mdbl_collection_watchlist_data': 'caches.mdbl_cache',
            'clear_trakt_collection_watchlist_data': 'caches.trakt_cache',
            'local_get_hidden_items': 'indexers.local_api',
            'mdbl_watched_unwatched': 'indexers.mdblist_api',
            'mdbl_progress': 'indexers.mdblist_api',
            'mdbl_get_hidden_items': 'indexers.mdblist_api',
            'trakt_watched_unwatched': 'indexers.trakt_api',
            'trakt_progress': 'indexers.trakt_api',
            'trakt_get_hidden_items': 'indexers.trakt_api',
            'trakt_official_status': 'indexers.trakt_api'
        }

        # Shadow the global variables natively grabbed by the upstream imports
        for func_name, mod_name in proxies.items():
            global_vars[func_name] = LazyProxy(mod_name, func_name)

        # Un-mock immediately. This confines the fake environment strictly to watched_cache.py.
        for mod in DUMMY_MODULES:
            if mod in sys.modules and isinstance(sys.modules[mod], DummyModule):
                del sys.modules[mod]

    except Exception as e:
        xbmc.log(f"[WIZARD-PATCH] Error applying lazy import proxies: {e}", xbmc.LOGWARNING)