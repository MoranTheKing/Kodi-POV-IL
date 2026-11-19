"""The viewer's own Google Drive as the sync's store: one file the build made there (FILE_NAME), reached with
drive.file -- "see, edit, create and delete only the specific Google Drive files you use with this app": the build
sees nothing else in the viewer's Drive, and nothing passes through the build's own servers. (Drive's hidden folder
for apps, drive.appdata, is not offered to TVs: Google's device flow answers "Invalid device flow scope" -- seen
with the build's own client, 20 Nov 2026. drive.file is.) A file made by the build is the build's on every device
of the viewer: drive.file is granted to the app, not to one device.

Connecting a device is Google's flow for TVs: the device shows an address and a short code, the viewer types the
code on a phone or a computer and approves; the device keeps the refresh token in its own settings file.

What each call costs in Drive's quota units (May 2026 table): a look at the file 5, an upload 50, a download 200,
a search 100 (only while the file's id is unknown). A round of the engine is one look; a download only when the
file changed since this device last read it; an upload only when this device has something new.
"""
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEVICE_URL = 'https://oauth2.googleapis.com/device/code'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
FILES = 'https://www.googleapis.com/drive/v3/files'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
SCOPE = 'https://www.googleapis.com/auth/drive.file'
NAME = 'Kodi POV IL - sync between devices (do not delete).gz'
TIMEOUT = 20


class DriveError(Exception):
    """A call that did not succeed; status is the HTTP status (0: no answer)."""

    def __init__(self, status, reason=''):
        Exception.__init__(self, '%s %s' % (status, reason))
        self.status, self.reason = status, reason


class Disconnected(DriveError):
    """The viewer took the build's access away (or it lapsed): the device must be connected again."""


def _open(request, opener=None):
    opener = opener or urllib.request.build_opener()
    try:
        with opener.open(request, timeout=TIMEOUT) as answer:
            return answer.status, answer.read(), dict(answer.headers)
    except urllib.error.HTTPError as answer:
        return answer.code, answer.read(), dict(answer.headers or {})
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DriveError(0, type(exc).__name__)


def _form(url, fields, opener=None):
    data = urllib.parse.urlencode(fields).encode()
    status, body, _headers = _open(urllib.request.Request(url, data=data, method='POST'), opener)
    try:
        return status, json.loads(body.decode('utf-8') or '{}')
    except ValueError:
        return status, {}


# ------------------------------------------------------------------ connecting a device
def start_device_flow(client_id, opener=None):
    """{'device_code', 'user_code', 'verification_url', 'expires_in', 'interval'} -- what the screen shows."""
    status, data = _form(DEVICE_URL, {'client_id': client_id, 'scope': SCOPE}, opener)
    if status != 200 or 'device_code' not in data:
        raise DriveError(status, data.get('error', 'no device code'))
    data.setdefault('interval', 5)
    data.setdefault('verification_url', data.get('verification_uri', 'https://www.google.com/device'))
    return data


def poll_device_flow(client_id, client_secret, flow, wait=time.sleep, cancelled=lambda: False, clock=time.time, opener=None):
    """Asks every few seconds until the viewer approved: the tokens ({'refresh_token', 'access_token', 'expires_at'}),
    or None when the viewer cancelled, refused, or the code ran out."""
    interval = int(flow.get('interval') or 5)
    ends = clock() + int(flow.get('expires_in') or 1800)
    while clock() < ends:
        if cancelled():
            return None
        wait(interval)
        if cancelled():
            return None
        status, data = _form(TOKEN_URL, {'client_id': client_id, 'client_secret': client_secret, 'device_code': flow['device_code'],
                                         'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'}, opener)
        if status == 200 and data.get('refresh_token'):
            return {'refresh_token': data['refresh_token'], 'access_token': data.get('access_token', ''),
                    'expires_at': clock() + int(data.get('expires_in') or 3600) - 60}
        error = data.get('error')
        if error == 'authorization_pending':
            continue
        if error == 'slow_down':
            interval += 5
            continue
        return None             # access_denied, expired_token, or something unexpected
    return None


def revoke(token, opener=None):
    try:
        _form(REVOKE_URL, {'token': token}, opener)
    except DriveError:
        pass


# ------------------------------------------------------------------ the file
class Drive(object):
    """The sync file in one viewer's Drive. tokens: the dict poll_device_flow gave (kept up to date here; save() is
    called whenever it changes, so the device keeps the fresh access token)."""

    def __init__(self, client_id, client_secret, tokens, save=lambda tokens: None, clock=time.time, opener=None):
        self.client_id, self.client_secret = client_id, client_secret
        self.tokens, self.save, self.clock, self.opener = tokens, save, clock, opener
        self.calls = []             # (method, quota units) of this round, for the log

    def _token(self):
        if self.tokens.get('access_token') and self.clock() < self.tokens.get('expires_at', 0):
            return self.tokens['access_token']
        status, data = _form(TOKEN_URL, {'client_id': self.client_id, 'client_secret': self.client_secret,
                                         'refresh_token': self.tokens['refresh_token'], 'grant_type': 'refresh_token'}, self.opener)
        if status in (400, 401) and data.get('error') in ('invalid_grant', 'unauthorized_client'):
            raise Disconnected(status, data.get('error'))
        if status != 200 or not data.get('access_token'):
            raise DriveError(status, data.get('error', 'no access token'))
        self.tokens = dict(self.tokens, access_token=data['access_token'], expires_at=self.clock() + int(data.get('expires_in') or 3600) - 60)
        self.save(self.tokens)
        return self.tokens['access_token']

    def _call(self, method, url, units, body=None, headers=None):
        request = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
        request.add_header('Authorization', 'Bearer ' + self._token())
        status, data, _headers = _open(request, self.opener)
        self.calls.append((method, units))
        if status == 401:
            # (an access token that lapsed early: once more with a fresh one)
            self.tokens = dict(self.tokens, access_token='', expires_at=0)
            request.add_header('Authorization', 'Bearer ' + self._token())
            status, data, _headers = _open(request, self.opener)
            self.calls.append((method, units))
        if status == 403 and b'insufficientPermissions' in data:
            raise Disconnected(status, 'insufficient permissions')
        if not 200 <= status < 300:
            raise DriveError(status, data[:120].decode('utf-8', 'replace'))
        return data

    def find(self):
        """The file's {'id', 'md5Checksum'} -- the latest of the build's own if there are several -- or None (100 units).
        (drive.file: only files the build made are ever listed.)"""
        query = urllib.parse.urlencode({'q': "name = '%s' and trashed = false" % NAME, 'orderBy': 'modifiedTime desc',
                                        'fields': 'files(id,md5Checksum,modifiedTime)', 'pageSize': 10})
        data = json.loads(self._call('GET', FILES + '?' + query, 100).decode('utf-8'))
        files = data.get('files') or []
        return files[0] if files else None

    def look(self, file_id):
        """{'id', 'md5Checksum'} of the file (5 units); None when it is gone."""
        try:
            data = self._call('GET', '%s/%s?%s' % (FILES, file_id, urllib.parse.urlencode({'fields': 'id,md5Checksum,trashed'})), 5)
        except DriveError as exc:
            if exc.status == 404:
                return None
            raise
        data = json.loads(data.decode('utf-8'))
        return None if data.get('trashed') else data

    def download(self, file_id):
        """The file's text (200 units)."""
        raw = self._call('GET', '%s/%s?alt=media' % (FILES, file_id), 200)
        return gzip.decompress(raw).decode('utf-8')

    def upload(self, text, file_id=None):
        """Writes the file (50 units): a new one in the viewer's Drive when there is no file_id. Its {'id', 'md5Checksum'}."""
        body = gzip.compress(text.encode('utf-8'))
        fields = urllib.parse.urlencode({'fields': 'id,md5Checksum'})
        if file_id:
            data = self._call('PATCH', '%s/%s?uploadType=media&%s' % (UPLOAD, file_id, fields), 50, body,
                              {'Content-Type': 'application/gzip'})
        else:
            boundary = 'povil-sync-boundary'
            meta = json.dumps({'name': NAME, 'mimeType': 'application/gzip',
                               'description': 'Kodi POV IL: favourites, watched marks and continue watching of POV and Umbrella, '
                                              'kept the same on every Kodi device of this account. Deleting it stops nothing: '
                                              'the next sync writes it again.'})
            multipart = ('--%s\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n%s\r\n--%s\r\nContent-Type: application/gzip\r\n\r\n'
                         % (boundary, meta, boundary)).encode() + body + ('\r\n--%s--' % boundary).encode()
            data = self._call('POST', '%s?uploadType=multipart&%s' % (UPLOAD, fields), 50, multipart,
                              {'Content-Type': 'multipart/related; boundary=%s' % boundary})
        return json.loads(data.decode('utf-8'))

    def delete(self, file_id):
        self._call('DELETE', '%s/%s' % (FILES, file_id), 50)
