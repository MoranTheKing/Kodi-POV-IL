# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_trakt_reauth.py

import threading
import xbmcgui

_AI_TRAKT_REFRESH_LOCK = 'pov_ai_trakt_refreshing'

def run(target_module):
    """
    Applies non-destructive namespace proxy patches to Trakt API module
    to gracefully recover from 401 Unauthorized errors.
    """

    # Prevent double-patching if the module is reloaded
    if hasattr(target_module, '_ai_trakt_tls'):
        return

    # Setup Thread-Local Storage for tracking 401s across concurrent threads
    target_module._ai_trakt_tls = threading.local()
    target_module._ai_trakt_tls.status = 0

    # Extract original unpatched references
    _orig_request = target_module.session.request
    _orig_call_trakt = target_module.call_trakt
    _orig_trakt_refresh = target_module.trakt_refresh
    get_setting = target_module.get_setting
    sleep = target_module.kodi_utils.sleep

    # 1. Proxy session.request to silently record HTTP status codes
    def _wrapper_request(*args, **kwargs):
        try:
            resp = _orig_request(*args, **kwargs)
            if not resp.ok:
                target_module._ai_trakt_tls.status = getattr(resp, 'status_code', 0)
            return resp
        except Exception as e:
            # Catch standard RequestsException and inspect attached response object
            target_module._ai_trakt_tls.status = getattr(getattr(e, 'response', None), 'status_code', 0)
            raise

    # 2. Thread-safe & Multi-process safe Token Refresher
    def _ai_trakt_refresh_once():
        try:
            window = xbmcgui.Window(10000)
        except Exception:
            window = None

        before = get_setting('trakt.token')

        if window is not None:
            # Poll GUI lock property to prevent simultaneous refreshes
            for _ in range(60):
                if window.getProperty(_AI_TRAKT_REFRESH_LOCK) != 'true':
                    break
                sleep(250)

            # Did someone else successfully refresh while we waited?
            if get_setting('trakt.token') != before:
                return True

            window.setProperty(_AI_TRAKT_REFRESH_LOCK, 'true')

            # Secondary verification against race conditions across processes
            if get_setting('trakt.token') != before:
                window.clearProperty(_AI_TRAKT_REFRESH_LOCK)
                return True

        try:
            _orig_trakt_refresh()
        finally:
            if window is not None:
                window.clearProperty(_AI_TRAKT_REFRESH_LOCK)

        return get_setting('trakt.token') != before

    # 3. Proxy Wrapper for `call_trakt` ensuring clean retry
    def _wrapper_call_trakt(path, params=None, data=None, with_auth=True, method=None, pagination=False, page=1):
        # POV recursively unpacks dictionary payloads. Doing so directly deletes data
        # from the parent's pointer, killing it for retries. Unpack via proxy clone.
        if isinstance(path, dict):
            p = dict(path)
            return _wrapper_call_trakt(str(p.pop('path')), **p)

        target_module._ai_trakt_tls.status = 0

        # Dispatch pristine execution
        result = _orig_call_trakt(
            path, params=params, data=data, with_auth=with_auth,
            method=method, pagination=pagination, page=page
        )

        # Allow valid return or standard error (other than 401) to propagate
        if result is not None or getattr(target_module._ai_trakt_tls, 'status', 0) != 401:
            return result

        # Check if an active refresh token even exists before attempting
        if not get_setting('trakt.refresh', ''):
            return result

        # Attempt recovery logic; if it fails, yield the original bad result
        if not _ai_trakt_refresh_once():
            return result

        # Clear state and retry the exact same original call since auth succeeded
        target_module._ai_trakt_tls.status = 0
        return _orig_call_trakt(
            path, params=params, data=data, with_auth=with_auth,
            method=method, pagination=pagination, page=page
        )

    # 4. Apply non-destructive variable shadowing overrides
    target_module.session.request = _wrapper_request
    target_module.call_trakt = _wrapper_call_trakt
    target_module.trakt_refresh = _ai_trakt_refresh_once