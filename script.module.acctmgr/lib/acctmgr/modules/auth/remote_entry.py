# -*- coding: utf-8 -*-
"""Phone-assisted LAN text entry dialog for TV-remote setups."""
import hmac
import html
import ipaddress
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import xbmc

from acctmgr.modules import log_utils
from acctmgr.modules.auth.base_auth import BaseDeviceAuth

MAX_ATTEMPTS = 8
MAX_BODY = 4096
EXPIRES_IN = 300


def local_ip():
    """Return Kodi's LAN IPv4 address, or None if unavailable."""
    try:
        raw = (xbmc.getIPAddress() or '').strip()
        addr = ipaddress.ip_address(raw)
    except Exception:
        return None
    if addr.version != 4 or addr.is_loopback or addr.is_unspecified or addr.is_link_local:
        return None
    return str(addr)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>%(title)s</title>
<style>
 body{font-family:system-ui,sans-serif;background:#16181d;color:#f2f2f2;margin:0;padding:24px;max-width:480px}
 h1{font-size:1.25rem;margin:0 0 16px} label{display:block;margin:16px 0 6px;color:#b9bfca;font-size:.9rem}
 input{width:100%%;box-sizing:border-box;padding:14px;font-size:1.05rem;border-radius:8px;border:1px solid #3a4150;
  background:#1f232b;color:#fff} button{margin-top:22px;width:100%%;padding:14px;font-size:1.05rem;border:0;
  border-radius:8px;background:#4fc3f7;color:#000;font-weight:600}
 .msg{padding:12px;border-radius:8px;margin-bottom:8px} .err{background:#4a2326;color:#ffb4b4}
 .ok{background:#1f3d2a;color:#b7f0c8} a{color:#4fc3f7} .hint{margin-top:18px;font-size:.85rem;color:#8d95a3}
</style></head><body>
<h1>%(title)s</h1>
%(body)s
</body></html>"""


def _render(title, body):
    return (_PAGE % {'title': html.escape(title), 'body': body}).encode('utf-8')


class _Handler(BaseHTTPRequestHandler):
    timeout = 10
    server_version = 'AMLite'
    sys_version = ''

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, payload):
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(payload)

    def _route_ok(self):
        return self.path.split('?', 1)[0] == self.server.secret_path

    def do_GET(self):
        if not self._route_ok():
            return self._send(404, _render('Not found', '<div class="msg err">Not found</div>'))
        self._send(200, self.server.form_page())

    def do_POST(self):
        if not self._route_ok():
            return self._send(404, _render('Not found', '<div class="msg err">Not found</div>'))
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self._send(400, self.server.form_page('Invalid request.'))
        form = parse_qs(self.rfile.read(length).decode('utf-8', 'replace'), keep_blank_values=True)
        pin = (form.get('pin') or [''])[0].strip()
        value = (form.get('value') or [''])[0].strip()
        status, payload = self.server.submit(pin, value)
        self._send(status, payload)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, secret_path, pin, validator, title, field_label, help_url):
        ThreadingHTTPServer.__init__(self, address, _Handler)
        self.secret_path = secret_path
        self.pin = pin
        self.validator = validator
        self.title = title
        self.field_label = field_label
        self.help_url = help_url
        self.result = None
        self.locked = False
        self.attempts = 0
        self._lock = threading.Lock()

    def form_page(self, error=None):
        e = html.escape
        parts = []
        if error:
            parts.append('<div class="msg err">%s</div>' % e(error))
        parts.append(
            '<form method="post" autocomplete="off">'
            '<label>Code shown on your TV</label>'
            '<input name="pin" inputmode="numeric" pattern="[0-9]*" maxlength="8" required autofocus>'
            '<label>%s</label>'
            '<input name="value" autocapitalize="off" autocorrect="off" spellcheck="false" required>'
            '<button type="submit">Send to Kodi</button></form>' % e(self.field_label))
        if self.help_url:
            parts.append('<p class="hint">Need it? <a href="%s" target="_blank" rel="noopener noreferrer">%s</a></p>'
                         % (e(self.help_url, quote=True), e(self.help_url)))
        return _render(self.title, ''.join(parts))

    def _fail(self, message):
        self.attempts += 1
        if self.attempts >= MAX_ATTEMPTS:
            self.locked = True
            return 429, _render(self.title, '<div class="msg err">Too many attempts. '
                                            'Please restart the setup on your TV.</div>')
        return 200, self.form_page(message)

    def submit(self, pin, value):
        with self._lock:
            if self.result is not None:
                return 200, _render(self.title, '<div class="msg ok">Already received. You can close this page.</div>')
            if self.locked:
                return 429, _render(self.title, '<div class="msg err">Locked. Restart the setup on your TV.</div>')
            if not hmac.compare_digest(pin.encode('utf-8'), self.pin.encode('utf-8')):
                return self._fail('Wrong code. Check the number shown on your TV.')
            if not value:
                return 200, self.form_page('Please enter a value.')

        try:
            ok, message, extra = self.validator(value)
        except Exception as e:
            log_utils.error('Remote entry validator crashed: %s' % e)
            ok, message, extra = False, 'Could not verify that value. Try again.', None

        with self._lock:
            if self.result is not None:
                return 200, _render(self.title, '<div class="msg ok">Already received.</div>')
            if ok:
                self.result = dict(extra or {}, value=value)
                return 200, _render(self.title, '<div class="msg ok">Saved! Look at your TV - '
                                                'you can close this page.</div>')
            return self._fail(message or 'That value was rejected.')


class RemoteKeyEntry(BaseDeviceAuth):
    """Temporary local HTTP server for phone-based text entry."""
    msg_success = ''
    msg_start_failed = 'Unable to start phone entry'
    msg_expired = 'Phone entry timed out'

    def __init__(self, provider_name, validator, icon=None, field_label=None, help_url=None):
        self.provider_name = provider_name
        self.icon = icon
        self._validator = validator
        self._field_label = field_label or provider_name
        self._help_url = help_url
        self._server = None
        self._thread = None

    @staticmethod
    def available():
        """Return True if Kodi has a usable LAN IPv4 address."""
        return local_ip() is not None

    def run(self):
        return self.token_data if self.authenticate() else None

    def get_device_code(self):
        ip = local_ip()
        if not ip:
            log_utils.error('RemoteKeyEntry: no usable LAN IPv4 address')
            return None
        pin = '%04d' % secrets.randbelow(10000)
        secret_path = '/' + secrets.token_urlsafe(9)
        try:
            server = _Server((ip, 0), secret_path, pin, self._validator,
                             'Send %s to Kodi' % self._field_label, self._field_label, self._help_url)
        except OSError as e:
            log_utils.error('RemoteKeyEntry: could not bind a local port: %s' % e)
            return None

        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.25})
        self._thread.daemon = True
        self._thread.start()

        url = 'http://%s:%d%s' % (ip, server.server_address[1], secret_path)
        return {
            'device_code': secret_path,
            'user_code': pin,
            'verification_url': url,
            'expires_in': EXPIRES_IN,
            'interval': 1,
            'qr_data': url,
        }

    def poll_token(self, device_data):
        server = self._server
        if server is None:
            return
        if server.result is not None:
            self.token_data = server.result
        elif server.locked:
            self.abort_auth('Too many failed attempts')

    def save_account(self):
        return bool(self.token_data)

    def authenticate(self):
        try:
            return BaseDeviceAuth.authenticate(self)
        finally:
            self._stop_server()

    def _stop_server(self):
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is None:
            return
        try:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        except Exception as e:
            log_utils.error('RemoteKeyEntry: server shutdown failed: %s' % e)

    def _notify(self, message):
        if message:
            BaseDeviceAuth._notify(self, message)
