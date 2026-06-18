# Telegram provider -- thin, guarded delegator (Phase B3).
#
# engine.py imports this at module load, so it MUST stay cheap and import-safe:
# it does NOT pull in telethon here. The heavy telethon-backed implementation
# lives in telegram_impl.py and is imported LAZILY only when the Telegram
# source is actually used (and only if the user enabled it). Any failure
# (telethon missing, not logged in, network) degrades to "no results" so the
# rest of the engine keeps working.
from resources.lib.subs_engine import log

global_var = []
site_id = '[Telegram]'
sub_color = 'deepskyblue'

_impl = None
_impl_failed = False


def _load_impl():
    """Lazily import the telethon-backed implementation. Returns the module or
    None (cached) on failure."""
    global _impl, _impl_failed
    if _impl is not None:
        return _impl
    if _impl_failed:
        return None
    try:
        from resources.lib.subs_engine.sources import telegram_impl
        _impl = telegram_impl
        return _impl
    except Exception as e:
        _impl_failed = True
        try:
            log.warning('[Telegram] impl load failed: {0}'.format(e))
        except Exception:
            pass
        return None


def _has_session():
    """True only if the user has logged in to Telegram (a saved session
    string exists). Lets us skip loading telethon entirely for everyone who
    hasn't connected -- no wasted import on every search."""
    try:
        import os
        import xbmcvfs
        import xbmcaddon
        prof = xbmcvfs.translatePath(
            xbmcaddon.Addon('service.subtitles.kodipovilai')
            .getAddonInfo('profile'))
        paths = [
            os.path.join(prof, 'telegram_session',
                         'telethon_session_string.txt'),
            # Reuse an existing DarkSubs Telegram login if present.
            xbmcvfs.translatePath(
                'special://profile/addon_data/service.subtitles.All_Subs/'
                'telegram_session/telethon_session_string.txt'),
        ]
        for p in paths:
            if os.path.isfile(p):
                with open(p, 'r') as f:
                    if f.read().strip():
                        return True
    except Exception:
        pass
    return False


def get_subs(item, *args, **kwargs):
    """Search the Telegram channel. Mirrors the other providers: populate this
    module's global_var with result dicts."""
    global global_var
    global_var = []
    # Don't even load telethon if the user never connected.
    if not _has_session():
        return []
    impl = _load_impl()
    if impl is None:
        return []
    try:
        impl.global_var = []
        impl.get_subs(item)
        global_var = list(getattr(impl, 'global_var', []) or [])
    except Exception as e:
        try:
            log.warning('[Telegram] get_subs failed: {0}'.format(e))
        except Exception:
            pass
        global_var = []
    return global_var


def download(download_data, MySubFolder, *args, **kwargs):
    impl = _load_impl()
    if impl is None:
        return None
    try:
        return impl.download(download_data, MySubFolder)
    except Exception as e:
        try:
            log.warning('[Telegram] download failed: {0}'.format(e))
        except Exception:
            pass
        return None


def upload_subtitle_to_telegram(*args, **kwargs):
    impl = _load_impl()
    if impl is None:
        return None
    try:
        return impl.upload_subtitle_to_telegram(*args, **kwargs)
    except Exception:
        return None


# ---- login / logout entry points (called from the settings button) ----

def login():
    impl = _load_impl()
    if impl is None:
        import xbmcgui
        xbmcgui.Dialog().ok(
            'MoranSubs — Telegram',
            'לא ניתן לטעון את רכיב הטלגרם. ודא שהבילד מותקן במלואו.')
        return
    impl.run_async_login_to_telegram()


def logout():
    impl = _load_impl()
    if impl is None:
        return
    try:
        impl.run_async_logout_from_telegram()
    except Exception:
        pass


def diagnose(phone=None):
    """Return a human-readable status string explaining the Telegram
    connection state (and, if a phone is given, the result of sending a login
    code). Used by the "Test Telegram" button so failures are visible even
    when debug logging is off."""
    impl = _load_impl()
    if impl is None:
        return ('לא ניתן לטעון את רכיב הטלגרם (telethon). ודא שהבילד מותקן '
                'במלואו ושהמנוע המובנה דלוק.')
    try:
        return impl.run_diagnose(phone)
    except Exception as e:
        return 'diagnose FAILED: {0}: {1}'.format(type(e).__name__, str(e)[:160])
