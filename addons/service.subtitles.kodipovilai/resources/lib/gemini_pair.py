# Local HTTP pair server for the Gemini API key.
#
# When the user picks "Pair from another device" in Connect
# Services, this module:
#   1. Picks a free port on the local machine.
#   2. Starts a tiny http.server on 0.0.0.0:<port> bound to all
#      interfaces (so it's reachable from LAN AND localhost).
#   3. Returns the URL(s) + a shared dict the caller can poll for
#      the submitted key.
#   4. Serves GET / -- a minimal RTL Hebrew HTML form that takes
#      an API key. Serves POST /submit -- stashes the key into
#      the shared dict and returns a "thanks" page.
#   5. Caller calls shutdown() when done (key received or timed
#      out) to free the port.
#
# Why localhost matters: a user running Kodi on their PHONE with
# cellular data has no LAN at all. Showing them a 192.168 URL is
# useless. But they CAN open http://localhost:<port> in the
# phone's browser -- the HTTP server runs on the same device and
# is reachable via the loopback interface regardless of network
# state. So we always show BOTH the LAN URL and the localhost
# URL; the user picks whichever applies.
#
# No third-party deps -- only Python stdlib (http.server, socket,
# threading). Validated against py3.8+ which is what Kodi 21
# ships.

import http.server
import re
import socket
import socketserver
import threading
import unicodedata
import urllib.parse


# Gemini API keys are ASCII alphanumeric + dash + underscore, ~39 chars.
# We keep this filter intentionally tight: anything outside it is
# either iOS autocorrect garbage (curly quotes, NBSP, ZWSP) or
# user typo from manual entry. Stripping it gives the API key it
# actually expected, not the version iOS Safari rewrote.
_KEY_CHARSET_RE = re.compile(r'[^A-Za-z0-9_\-]')

# iOS Smart Punctuation replaces ASCII hyphen-minus (U+002D) with
# typographically "pretty" dash variants -- em-dash for `--`, sometimes
# en-dash for stand-alone `-`. Those are SEPARATE Unicode codepoints
# from U+002D and NFKC normalisation does NOT collapse them back.
# Without explicit handling, the allow-list above would STRIP them
# entirely and an iPhone-pasted key like `AIza...XYZ-ABC` would
# arrive at our server as `AIza...XYZABC` -- Google rejects it as
# malformed. Mapping every dash-shaped Unicode codepoint back to
# ASCII `-` BEFORE the allow-list preserves the key.
_DASH_LIKE = (
    '‐'  # hyphen
    '‑'  # non-breaking hyphen
    '‒'  # figure dash
    '–'  # en dash         <- iOS often picks this
    '—'  # em dash         <- iOS for "--"
    '―'  # horizontal bar
    '⁃'  # hyphen bullet
    '−'  # minus sign
    '﹘'  # small em dash
    '﹣'  # small hyphen-minus
    '－'  # full-width hyphen-minus
)
_DASH_TO_ASCII = str.maketrans({c: '-' for c in _DASH_LIKE})


def _sanitize_key(raw):
    """Strip every byte iOS Safari might have inserted into a pasted
    API key. Order matters: NFKC normalises full-width / smart-quoted
    variants to their ASCII equivalents BEFORE we filter, so e.g. a
    smart-quoted "AIza..." becomes plain quotes (then stripped) and
    a full-width A maps to ASCII A. THEN we coerce every dash-shaped
    codepoint back to ASCII `-` (iOS Smart Punctuation substitution
    that NFKC misses). Finally the allow-list keeps only the charset
    Gemini keys actually use."""
    if not raw:
        return ''
    # Normalize unicode confusables to their ASCII canonical form.
    normalised = unicodedata.normalize('NFKC', raw)
    # Convert iOS smart-dashes (em-dash, en-dash, etc.) back to '-'.
    # Without this, the allow-list would drop them and shorten the
    # key, which Google rejects.
    normalised = normalised.translate(_DASH_TO_ASCII)
    # Remove ASCII whitespace plus NBSP, ZWSP, BOM, RTL/LTR marks etc.
    # _KEY_CHARSET_RE catches all of these by allow-listing only the
    # chars Gemini keys actually use.
    cleaned = _KEY_CHARSET_RE.sub('', normalised)
    return cleaned


# Form served on GET /. Plain UTF-8 HTML with inline CSS, RTL.
# Submitted to POST /submit as application/x-www-form-urlencoded.
_HTML_FORM = '''<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kodi POV IL - Gemini API Key</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
           margin: 0; padding: 24px; background: #101820; color: #f6f1df; }
    .card { max-width: 540px; margin: 32px auto; padding: 28px;
            background: #172635; border: 1px solid #34495e;
            border-radius: 16px; }
    h1 { margin: 0 0 8px 0; color: #ffd166; font-size: 1.4rem; }
    p { line-height: 1.6; color: #b7c4cf; font-size: 0.95rem; }
    label { display: block; margin-top: 16px; font-weight: bold; }
    input[type=text] { width: 100%; box-sizing: border-box; margin-top: 8px;
                       padding: 14px; font-size: 1.1rem; direction: ltr;
                       background: #0a0f15; color: #f6f1df;
                       border: 1px solid #34495e; border-radius: 8px; }
    button { width: 100%; margin-top: 20px; padding: 14px; font-size: 1.1rem;
             font-weight: bold; color: #101820; background: #ffd166;
             border: none; border-radius: 8px; cursor: pointer; }
    button:active { background: #e0b54a; }
    .small { font-size: 0.85rem; color: #b7c4cf; margin-top: 12px; }
    code { background: #0a0f15; padding: 2px 6px; border-radius: 4px;
           font-size: 0.9rem; direction: ltr; }
  </style>
</head>
<body>
  <div class="card">
    <h1>חיבור Gemini AI</h1>
    <p>
      הדבק כאן את ה-Gemini API key שיצרת ב-
      <code>aistudio.google.com/apikey</code> ולחץ "שלח".
      Kodi יבדוק את המפתח ויאמת מולך אם החיבור הצליח.
    </p>
    <form method="POST" action="/submit">
      <label for="key">Gemini API Key</label>
      <!--
        iOS Safari note: in addition to the W3C attributes
        (autocomplete, autocapitalize, spellcheck), iOS-only
        autocorrect MUST be explicitly disabled. Without it,
        Safari quietly modifies the pasted key (smart quotes,
        non-breaking spaces, mid-word capitalization) and the
        server receives a corrupted string that Google's API
        rejects with a 400. inputmode=verbatim also helps disable
        keyboard suggestions on iOS / Android.
      -->
      <input type="text" id="key" name="key"
             autocomplete="off" autocapitalize="off"
             autocorrect="off" spellcheck="false"
             inputmode="verbatim"
             placeholder="AIza..." required>
      <button type="submit">שלח ל-Kodi</button>
    </form>
    <p class="small">
      טיפ: בטלפון לחץ "Copy" ב-AI Studio, אז כאן בשדה למעלה
      לחץ פעם ארוכה והדבק.
    </p>
  </div>
</body>
</html>
'''

# Echoes a fingerprint of the received key so the user can verify
# nothing got corrupted in transit (iOS autocorrect, etc.). Format
# is FIRST-FOUR…LAST-FOUR + length, e.g. "AIza…9xY7 (39 chars)".
# We deliberately do NOT show the full key (the page might be
# screenshotted/photographed by support or shoulder-surfed).
_HTML_DONE_OK = '''<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>נשלח</title>
<style>body{{font-family:Arial,sans-serif;background:#101820;color:#f6f1df;
text-align:center;padding:60px 20px}}h1{{color:#7fbf7f;font-size:2rem}}
p{{color:#b7c4cf}}code{{background:#0a0f15;padding:6px 12px;border-radius:6px;
display:inline-block;margin:8px;direction:ltr;font-size:1.1rem}}</style></head>
<body><h1>✓ ה-key נשלח ל-Kodi</h1>
<p>השרת קיבל:</p>
<p><code>{fingerprint}</code></p>
<p>ודא ש-{first4} ו-{last4} תואמים את ה-key המקורי שהעתקת.
אם לא — לחץ <a href="/" style="color:#ffd166">חזור</a> והדבק שוב.</p>
<p>אפשר לסגור את הדף ולחזור ל-Kodi.</p></body></html>
'''

_HTML_DONE_EMPTY = '''<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>שגיאה</title>
<style>body{font-family:Arial,sans-serif;background:#101820;color:#f6f1df;
text-align:center;padding:60px 20px}h1{color:#bf7f7f;font-size:2rem}
p{color:#b7c4cf}a{color:#ffd166}</style></head>
<body><h1>שדה ריק</h1>
<p>לא הוזן key. <a href="/">חזור לטופס</a>.</p></body></html>
'''


def _make_handler(state):
    """Build a request-handler class that closes over `state`
    (a dict the caller polls for the submitted key)."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, code, body, ctype='text/html; charset=utf-8'):
            data = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = (self.path or '/').split('?', 1)[0]
            if path == '/' or path == '/index.html':
                self._send(200, _HTML_FORM)
                return
            self._send(404, '<h1>404</h1>')

        def do_POST(self):
            if self.path != '/submit':
                self._send(404, '<h1>404</h1>')
                return
            length = int(self.headers.get('Content-Length') or 0)
            try:
                raw = self.rfile.read(length).decode('utf-8',
                                                     errors='replace')
            except Exception:
                self._send(400, '<h1>400</h1>')
                return
            fields = urllib.parse.parse_qs(raw)
            submitted = (fields.get('key', [''])[0] or '').strip()
            # Aggressive sanitisation: iOS Safari can sneak smart
            # quotes / non-breaking spaces / zero-width chars into a
            # pasted API key even with autocorrect=off. The Gemini
            # API rejects those with 400 and the user sees no clue
            # why. _sanitize_key normalises NFKC then keeps only the
            # ASCII charset Google's keys actually use.
            key = _sanitize_key(submitted)
            if not key:
                self._send(200, _HTML_DONE_EMPTY)
                return
            # Stash for the caller's polling loop. We deliberately
            # don't validate here -- the caller does that with the
            # full Gemini test_key flow so the user sees the
            # error in the Kodi UI, not in the browser.
            state['received_key'] = key
            # Build a fingerprint the user can sanity-check against
            # the key they actually copied. If iOS managed to corrupt
            # something despite our sanitiser, the first-4/last-4
            # comparison surfaces it immediately.
            first4 = (key[:4] if len(key) >= 4 else key) or '?'
            last4 = (key[-4:] if len(key) >= 8 else '') or '...'
            fingerprint = '{0}…{1}   ({2} chars)'.format(
                first4, last4, len(key))
            self._send(200, _HTML_DONE_OK.format(
                fingerprint=fingerprint, first4=first4, last4=last4))

        # Silence stderr access-log spam.
        def log_message(self, fmt, *args):
            pass

    return Handler


class _ThreadingServer(socketserver.ThreadingMixIn,
                       http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def get_lan_ip():
    """Best-effort detection of this machine's LAN IP. Tries the
    "connect to a public address" trick (no packets actually sent
    on UDP) and falls back to hostname resolution.

    Returns the IP as a string, or None if we couldn't figure out
    a non-loopback one."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        try:
            s.connect(('8.8.8.8', 1))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    try:
        host = socket.gethostname()
        ip = socket.gethostbyname(host)
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass
    return None


def find_free_port(preferred=(8765, 8766, 8767, 8768, 8769)):
    """Try a small set of preferred ports first (so the firewall
    prompt is consistent across runs). Fall back to an
    OS-allocated port if all are taken."""
    for port in preferred:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('', port))
            s.close()
            return port
        except OSError:
            continue
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class PairServer:
    """Tiny wrapper so the caller can `with PairServer() as ps:`
    style use it. After construction:
      ps.port           -- the bound port number
      ps.lan_ip         -- detected LAN IP or None
      ps.url_lan        -- 'http://<lan_ip>:<port>' or None
      ps.url_local      -- 'http://localhost:<port>'
      ps.received_key() -- returns the submitted key or '' if none yet
      ps.shutdown()     -- stops the server thread (idempotent)
    """

    def __init__(self):
        self._state = {'received_key': None}
        self.port = find_free_port()
        self.lan_ip = get_lan_ip()
        handler = _make_handler(self._state)
        self._server = _ThreadingServer(('', self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.url_lan = ('http://{0}:{1}'.format(self.lan_ip, self.port)
                        if self.lan_ip else None)
        self.url_local = 'http://localhost:{0}'.format(self.port)
        self._closed = False

    def received_key(self):
        return self._state.get('received_key') or ''

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown()
