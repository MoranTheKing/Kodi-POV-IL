# Anonymous, best-effort usage telemetry for AI translations -> the POV pool
# Worker (POST /ev). Owner-only dashboard lives at the Worker's /stats.
#
# Privacy: the ONLY identifier sent is a random per-install id (a uuid stored in
# a hidden setting). No account, no IP (beyond what any HTTPS request exposes to
# Cloudflare), no file paths. The payload is: anonymous id, add-on version,
# media type + title + season/episode/year, source language, the translation
# METHOD (ai_ar / ai_fallback / ai_plain), success, and a few diagnostics.
#
# Fully guarded and fire-and-forget on a daemon thread -- it NEVER blocks the
# translation and NEVER raises into the caller. If the Worker has no /ev yet
# (not deployed) the POST just 404s and is ignored.
import json
import threading

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

ADDON_ID = 'service.subtitles.kodipovilai'


def _addon_version():
    try:
        return xbmcaddon.Addon(ADDON_ID).getAddonInfo('version') or ''
    except Exception:
        return ''


def _anon_id():
    """A stable, anonymous per-install id. Created once and stored in a hidden
    setting. Read/written on the CALLING thread (Kodi setting writes off-thread
    are unreliable)."""
    try:
        from resources.lib import kodi_utils
        v = (kodi_utils.get_setting('_telemetry_id', '') or '').strip()
        if not v:
            import uuid
            v = uuid.uuid4().hex
            kodi_utils.set_setting('_telemetry_id', v)
        return v
    except Exception:
        return ''


def report(event):
    """Send one usage event. Best-effort, non-blocking, never raises."""
    try:
        event = dict(event or {})
        event['anon'] = _anon_id()
        event['v'] = _addon_version()
    except Exception:
        return

    def _send():
        try:
            import urllib.request
            from resources.lib import pool
            data = json.dumps(event).encode('utf-8')
            req = urllib.request.Request(
                pool.POOL_URL + '/ev', data=data,
                headers={'content-type': 'application/json',
                         'x-api-key': pool.POOL_API_KEY,
                         'user-agent': 'Mozilla/5.0'})
            urllib.request.urlopen(req, timeout=8).read()
        except Exception:
            pass  # telemetry must never matter to the user

    try:
        threading.Thread(target=_send, daemon=True).start()
    except Exception:
        pass
