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


# Gemini API keys come in two formats Google issues from AI Studio:
#   * Legacy "AIza..." -- 39 ASCII chars, alphanumeric + dash + underscore.
#   * New "AQ.AbcDef..." (rolled out late 2025) -- ~50 ASCII chars and
#     INCLUDES PERIODS as part of the key body. Without `.` in the
#     allow-list below the sanitizer would strip every period and ship
#     `AQAbcDef...` to Google -- which is rejected as malformed (400).
# The filter stays tight on every OTHER non-key codepoint (curly
# quotes, NBSP, ZWSP, RTL marks etc. that iOS Safari inserts) so a
# corrupted paste still gets cleaned up; we just add `.` to the
# allow-set so new-format keys pass through intact.
_KEY_CHARSET_RE = re.compile(r'[^A-Za-z0-9_\-\.]')

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
    input[type=password] { width: 100%; box-sizing: border-box; margin-top: 8px;
                       padding: 14px; font-size: 1.1rem; direction: ltr;
                       background: #0a0f15; color: #f6f1df;
                       border: 1px solid #34495e; border-radius: 8px; }
    button { width: 100%; margin-top: 20px; padding: 14px; font-size: 1.1rem;
             font-weight: bold; color: #101820; background: #ffd166;
             border: none; border-radius: 8px; cursor: pointer; }
    button:disabled { opacity: .5; cursor: default; }
    button:active { background: #e0b54a; }
    #fp { direction: ltr; text-align: center; margin-top: 10px; color: #f6f1df; }
    #msg { margin-top: 14px; padding: 12px; border-radius: 8px; font-size: 0.95rem;
           line-height: 1.5; display: none; }
    .ok { background: #16351f; color: #a7e0b0; display: block !important; }
    .err { background: #351a1a; color: #e6a6a6; display: block !important; }
    .info { background: #14202c; color: #b7c4cf; display: block !important; }
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
      <code>aistudio.google.com/apikey</code>. נוודא מול Google
      שהמפתח תקין, ורק אז נשלח אותו ל-Kodi.
    </p>
    <form method="POST" action="/submit" id="f">
      <label for="key">Gemini API Key</label>
      <!--
        iOS/WebKit note: type=password suppresses the smart-punctuation /
        autocorrect that silently corrupt a pasted key on iOS (every iOS
        browser is WebKit). We also read the RAW clipboard on paste (bypassing
        field-level mangling) and validate the key against Google FROM THE PHONE
        before submitting -- so a corrupted / bad key is caught here with a clear
        message instead of a confusing 401 back in Kodi. The server still
        sanitizes what it receives.
      -->
      <input type="password" id="key" name="key"
             autocomplete="off" autocapitalize="off"
             autocorrect="off" spellcheck="false"
             inputmode="verbatim"
             placeholder="AIza... או AQ.Ab8..." required>
      <div id="fp"></div>
      <button type="submit" id="go">בדוק ושלח ל-Kodi</button>
    </form>
    <div id="msg"></div>
    <p class="small">
      טיפ: בטלפון לחץ "Copy" ב-AI Studio, אז כאן בשדה למעלה
      לחץ פעם ארוכה והדבק.
    </p>
  </div>
<script>
"use strict";
// sanitize() is byte-parity with the server-side _sanitize_key (proven).
var DASH = /[‐‑‒–—―⁃−﹘﹣－]/g;
function sanitize(raw) {
  if (!raw) return '';
  return raw.normalize('NFKC').replace(DASH, '-').replace(/[^A-Za-z0-9_.-]/g, '');
}
function fingerprint(k) {
  var h = k.length >= 8 ? k.slice(0, 8) : k;
  var t = k.length >= 16 ? k.slice(-8) : '';
  return h + (t ? '…' + t : '') + '   (' + k.length + ' chars)';
}
var elKey = document.getElementById('key');
var elFp = document.getElementById('fp');
var elMsg = document.getElementById('msg');
var form = document.getElementById('f');
var btn = document.getElementById('go');
function msg(t, c) { elMsg.textContent = t; elMsg.className = c; }
// Read the RAW clipboard on paste, before iOS/WebKit can mangle it in the field.
elKey.addEventListener('paste', function (e) {
  try {
    var raw = (e.clipboardData || window.clipboardData).getData('text/plain');
    if (raw) { e.preventDefault(); elKey.value = sanitize(raw); elFp.textContent = fingerprint(elKey.value); }
  } catch (err) { /* fall back to the field value */ }
});
elKey.addEventListener('input', function () { elFp.textContent = elKey.value ? fingerprint(sanitize(elKey.value)) : ''; });
// Validate the key against Google FROM THE PHONE (x-goog-api-key header so AQ.
// keys work). Classify by STATUS, not r.ok: 400/401/403 = truly bad key (false);
// 429 / 5xx / network / timeout = ambiguous (null) -> submit anyway and let Kodi
// decide. (Mirrors gemini.py's InvalidKey-vs-RateLimited/Overload distinction, so
// a valid key hitting a transient rate limit is never mislabeled "bad key".)
function validateKey(key) {
  var ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
  var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 9000) : null;
  var opts = { method: 'GET', headers: { 'x-goog-api-key': key }, cache: 'no-store' };
  if (ctrl) opts.signal = ctrl.signal;
  return fetch('https://generativelanguage.googleapis.com/v1beta/models', opts)
    .then(function (r) {
      if (timer) clearTimeout(timer);
      if (r.ok) return true;
      if (r.status === 400 || r.status === 401 || r.status === 403) return false;
      return null;
    })
    .catch(function () { if (timer) clearTimeout(timer); return null; });
}
form.addEventListener('submit', function (e) {
  e.preventDefault();
  var key = sanitize(elKey.value || '');
  elKey.value = key;
  elFp.textContent = key ? fingerprint(key) : '';
  if (!key) { msg('הזן API key.', 'err'); return; }
  if (typeof fetch !== 'function') { form.submit(); return; }   // ancient browser: let Kodi validate
  btn.disabled = true;
  elKey.readOnly = true;                                         // lock the field during the async check
  msg('בודק את המפתח מול Google…', 'info');
  validateKey(key).then(function (ok) {
    if (ok === false) {
      msg('Google דחה את המפתח הזה. העתק אותו שוב במלואו מ-AI Studio ונסה שוב ' +
          '(ודא שאין רווח או תו חסר). אם הוא נכון אבל עדיין נדחה — צור מפתח חדש.', 'err');
      btn.disabled = false; elKey.readOnly = false; return;
    }
    if (ok === null) { msg('לא הצלחנו לאמת מול Google (בעיית רשת?) — שולח בכל זאת, Kodi יבדוק.', 'info'); }
    else { msg('המפתח תקין ✓  שולח ל-Kodi…', 'info'); }
    elKey.value = key;                                           // re-assert the exact validated value
    form.submit();   // readOnly fields ARE submitted; native POST, no submit-event re-fire
  });
});
</script>
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
            # the key they actually copied. Show first 8 + last 8
            # chars: a 39-char Gemini key has its middle 23 hidden,
            # which is plenty for shoulder-surf safety while giving
            # the user enough material to confirm no mid-string
            # corruption survived our sanitiser.
            head = (key[:8] if len(key) >= 8 else key) or '?'
            tail = (key[-8:] if len(key) >= 16 else '') or '...'
            fingerprint = '{0}…{1}   ({2} chars)'.format(
                head, tail, len(key))
            self._send(200, _HTML_DONE_OK.format(
                fingerprint=fingerprint, first4=head, last4=tail))

        # Silence stderr access-log spam.
        def log_message(self, fmt, *args):
            pass

    return Handler


class _ThreadingServer(socketserver.ThreadingMixIn,
                       http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _is_private_lan_ip(ip):
    """True for the RFC 1918 ranges + 100.64/10 (CGNAT-ish, occasionally
    seen on home routers). Excludes 127/8 (loopback), 169.254/16
    (link-local that means "DHCP failed"), VPN tunnel typical ranges
    are NOT excluded because we want them surfaced -- the user can
    pick which one matches their phone."""
    if not ip or ip.startswith('127.') or ip.startswith('169.254.'):
        return False
    if ip.startswith('10.') or ip.startswith('192.168.'):
        return True
    if ip.startswith('172.'):
        try:
            second = int(ip.split('.')[1])
            return 16 <= second <= 31
        except (ValueError, IndexError):
            return False
    if ip.startswith('100.'):
        try:
            second = int(ip.split('.')[1])
            return 64 <= second <= 127
        except (ValueError, IndexError):
            return False
    return False


def _probe_outbound_ip(target):
    """Open a UDP socket "connected" to `target` (no packets sent)
    and read the local address the OS picked. Returns '' on failure."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.5)
        s.connect((target, 1))
        return s.getsockname()[0]
    except Exception:
        return ''
    finally:
        s.close()


def _ips_from_subprocess():
    """Enumerate IPv4 addresses on every interface using the `ip`
    or `ifconfig` CLI. Reliable on Android (which always ships
    `ip` via toybox), Linux desktops, and most BSDs. Returns an
    empty list if neither command is available. This is the
    cleanest way to catch IPs on interfaces that AREN'T the
    default route -- a WiFi + Ethernet multi-NIC Android TV
    where the user's phone might only reach one of them."""
    import subprocess
    out = ''
    for cmd in (['ip', '-4', '-o', 'addr'],
                ['ifconfig'], ['ifconfig', '-a']):
        try:
            out = subprocess.check_output(
                cmd, stderr=subprocess.DEVNULL,
                timeout=2).decode('utf-8', errors='replace')
            if out:
                break
        except Exception:
            continue
    if not out:
        return []
    # IPv4 dotted-quad regex; tolerates `ip addr` ("inet 192.168.1.5/24")
    # and ifconfig ("inet 192.168.1.5 netmask ...").
    import re as _re
    found = _re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', out)
    # Dedupe preserving order.
    seen, ips = set(), []
    for ip in found:
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips


def get_lan_ips():
    """Return ALL plausible LAN IPv4 addresses for this machine, in
    priority order. The dialog shows every entry so a user with
    multiple interfaces (WiFi + Ethernet on an Android TV, VPN
    + WiFi on a laptop, etc.) can pick the one their phone is on
    -- the single-IP heuristic in the older version would silently
    pick the wrong interface for VPN/multi-NIC setups, leaving
    the phone unable to reach the server."""
    candidates = []

    # 1. The "connect to 8.8.8.8" trick -- gives us the IP of the
    #    interface used for the default route. PRIORITISED first
    #    because in single-NIC cases this is always correct.
    ip = _probe_outbound_ip('8.8.8.8')
    if ip and ip not in candidates:
        candidates.append(ip)

    # 2. Subprocess-based interface enumeration -- catches IPs on
    #    non-default-route interfaces (the case behind every
    #    "phone says address not found" report when the user has
    #    WiFi + Ethernet both up). `ip addr` on Android, `ifconfig`
    #    on POSIX.
    for ip in _ips_from_subprocess():
        if ip and ip not in candidates:
            candidates.append(ip)

    # 3. Probe each private-LAN range -- in some routing-table
    #    configurations a probe to a specific range binds to the
    #    matching interface.
    for probe_target in ('10.0.0.1', '192.168.1.1', '172.16.0.1',
                         '100.64.0.1'):
        ip = _probe_outbound_ip(probe_target)
        if ip and ip not in candidates:
            candidates.append(ip)

    # 4. Hostname-based fallback (sometimes lists more interfaces).
    try:
        _, _, hostname_ips = socket.gethostbyname_ex(socket.gethostname())
        for ip in hostname_ips:
            if ip and ip not in candidates:
                candidates.append(ip)
    except Exception:
        pass

    # Keep only private-LAN-looking IPs -- VPN/Internet IPs would
    # never be reachable from the phone anyway, and the user
    # gets confused if we show them.
    return [ip for ip in candidates if _is_private_lan_ip(ip)]


def get_lan_ip():
    """Back-compat shim for callers that want just one IP -- returns
    the first (= default-route) LAN candidate or None."""
    ips = get_lan_ips()
    return ips[0] if ips else None


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
      ps.lan_ip         -- detected primary LAN IP or None
      ps.lan_ips        -- list of ALL plausible LAN IPv4 addresses
                           (one per interface). The dialog should
                           show every entry because a user on
                           Android-TV-with-Ethernet-AND-WiFi might
                           need a different one than the
                           default-route IP we'd otherwise pick.
      ps.url_lan        -- 'http://<lan_ip>:<port>' or None
                           (primary URL -- first entry of url_lans)
      ps.url_lans       -- list of 'http://<ip>:<port>' for every IP
      ps.url_local      -- 'http://localhost:<port>'
      ps.received_key() -- returns the submitted key or '' if none yet
      ps.shutdown()     -- stops the server thread (idempotent)
    """

    def __init__(self):
        self._state = {'received_key': None}
        self.port = find_free_port()
        self.lan_ips = get_lan_ips()
        self.lan_ip = self.lan_ips[0] if self.lan_ips else None
        handler = _make_handler(self._state)
        self._server = _ThreadingServer(('', self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.url_lans = ['http://{0}:{1}'.format(ip, self.port)
                         for ip in self.lan_ips]
        self.url_lan = self.url_lans[0] if self.url_lans else None
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
