# -*- coding: utf-8 -*-
"""
	Account Manager

	MDBList setup wizard. Settings written by this module (never mixed):
		mdblist.token      OAuth access token (Bearer)
		mdblist.refresh    OAuth refresh token
		mdblist.expires    OAuth access-token expiry (unix timestamp)
		mdblist.apikey     plain MDBList API key ONLY
		mdblist.username   MDBList username
		mdblist.client_id  Device Code app client id (register at mdblist.com/developer)
"""
import time
import xbmc, xbmcgui, xbmcaddon
import json
import urllib.error
import urllib.parse
import urllib.request
import requests
from acctmgr.modules.auth.mdblist_select import confirm_setup
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.auth.base_auth import BaseDeviceAuth

mdb_icon = control.joinPath(control.iconsPath(), 'mdblist.png')
ADDON_ID = "script.module.acctmgr"
ADDON_NAME = "AM Lite"
API_BASE = "https://api.mdblist.com"
API_KEY_PAGE = "https://mdblist.com/preferences/"
USER_URL = f"{API_BASE}/user"
DEFAULT_CLIENT_ID = "YG07cdkRbhkmrFBUGkNhAnzfNtwi6naDvflMRob9"

DEVICE_AUTH_URL = f"{API_BASE}/oauth/device-authorization/"
TOKEN_URL = f"{API_BASE}/oauth/token/"
REVOKE_URL = f"{API_BASE}/oauth/revoke_token/"
OAUTH_SCOPE = "write"
MAX_KEY_ATTEMPTS = 3
API_KEY_FIELDS = ("apikey", "api_key", "apiKey")

class MDBListAuth(BaseDeviceAuth):
    provider_name = "MDBList"

    def __init__(self):
        self.addon = xbmcaddon.Addon(ADDON_ID)
        self.token = self._get_setting('mdblist.token')

    def _get_setting(self, key):
        try:
            return self.addon.getSetting(key)
        except Exception:
            return ""

    def _set_setting(self, key, value):
        try:
            self.addon.setSetting(key, value if value is not None else "")
            return True
        except Exception as e:
            xbmc.log(f"{ADDON_NAME}: MDBList setSetting failed for [{key}] - {e}", xbmc.LOGERROR)
            return False

    def _notify_user(self, message):
        control.notification(title=self.provider_name, message=message, icon=mdb_icon)

    def _request_json(self, url, timeout=10):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Kodi AM Lite",
                "Accept": "application/json",
            }
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            body = resp.read().decode("utf-8", "replace")

        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}

        return status, data, body

    def fetch_user(self, api_key):
        """Validate key and return MDBList username."""
        api_key = (api_key or "").strip()
        if not api_key:
            return False, "Missing API key", None

        url = f"{API_BASE}/user?apikey={urllib.parse.quote(api_key)}"

        try:
            status, data, raw = self._request_json(url)
        except urllib.error.HTTPError as e:
            xbmc.log(f"{ADDON_NAME}: MDBList key rejected - HTTP {e.code}", xbmc.LOGERROR)
            return False, ("Invalid API key" if e.code in (401, 403) else f"HTTP {e.code}"), None
        except Exception as e:
            xbmc.log(f"{ADDON_NAME}: MDBList request failed - {e}", xbmc.LOGERROR)
            return False, f"Request failed: {e}", None

        if status != 200:
            message = None
            if isinstance(data, dict):
                message = data.get("error") or data.get("message") or data.get("detail")

            if not message:
                message = f"HTTP {status}"

            xbmc.log(
                f"{ADDON_NAME}: MDBList auth failed - status={status} response={raw}",
                xbmc.LOGERROR
            )
            return False, message, None

        username = ""
        if isinstance(data, dict):
            username = (data.get("username") or "").strip()

        if not username:
            xbmc.log(
                f"{ADDON_NAME}: MDBList auth succeeded but no username returned: {raw}",
                xbmc.LOGERROR
            )
            return False, "Username not returned by MDBList", None

        return True, "OK", username

    def _validate_api_key(self, key):
        """Validate API key and return result formatted for RemoteKeyEntry."""
        ok, msg, username = self.fetch_user(key)
        return ok, msg, {'username': username}

    def _fill_username(self, username):
        if username and not self._get_setting('mdblist.username'):
            self._set_setting('mdblist.username', username)

    def _save_api_key(self, key, username):
        self._set_setting('mdblist.apikey', key)
        self._fill_username(username)
        self._notify_user('API key saved')

    def auth(self):
        """
        1. Scan installed add-ons/skins and split them into a QR (OAuth) group and an API key group
        2. Confirm with the user
        3. OAuth step  -> auth_device() (QR code)             [only if the QR group is non-empty]
        4. API key step -> auto-fetch / phone entry / keyboard [only if the API key group is non-empty]

        Returns True when at least one credential this setup needed was stored. The actual push
        to the add-ons/skins is done by mdblist_sync (default.py runs it right after this returns).
        """
        self._migrate_legacy_settings()
        oauth_targets, key_targets = self._scan_targets()
        n_oauth, n_key = len(oauth_targets), len(key_targets)

        if n_oauth == 0 and n_key == 0:
            if not control.yesnoDialog(
                    "No supported add-ons or skins were detected.\nAuthorize MDBList with a QR code anyway?",
                    ADDON_NAME, 'Cancel', 'Authorize'):
                return False
            need_oauth, need_key = True, False
        else:
            if not confirm_setup(oauth_targets, key_targets):
                return False
            need_oauth, need_key = n_oauth > 0, n_key > 0

        oauth_ok = key_ok = False

        if need_oauth:
            oauth_ok = self._ensure_oauth()
            if not oauth_ok and need_key:
                if not control.yesnoDialog(
                        "QR authorization did not complete.\nContinue with the API key setup?",
                        ADDON_NAME, 'No', 'Yes'):
                    return False

        if need_key:
            key_ok = self._ensure_api_key(oauth_ok)

        if need_oauth and not oauth_ok:
            self._notify_user('QR authorization missing - QR add-ons were not set up')
        if need_key and not key_ok:
            self._notify_user('API key missing - API key add-ons/skins were not set up')

        return (need_oauth and oauth_ok) or (need_key and key_ok)

    def _scan_targets(self):
        try:
            from acctmgr.modules.sync import mdblist_sync
            return mdblist_sync.detect_installed()
        except Exception as e:
            log_utils.error(f"MDBList target scan failed: {e}")
            return [], []

    def _ensure_oauth(self):
        if self._oauth_session_valid():
            self._notify_user('QR authorization already active')
            return True
        return bool(self.auth_device())

    def _ensure_api_key(self, oauth_ok):
        existing = (self._get_setting('mdblist.apikey') or '').strip()
        if existing:
            ok, msg, username = self.fetch_user(existing)
            if ok:
                self._fill_username(username)
                self._notify_user('API key already configured')
                return True

        if oauth_ok:
            key = self._fetch_api_key_from_profile()
            if key:
                ok, msg, username = self.fetch_user(key)
                if ok:
                    self._save_api_key(key, username)
                    return True

        return self._collect_api_key_manually()

    def _fetch_api_key_from_profile(self):
        """Attempt to extract and validate an API key from the user profile."""
        token = self._get_setting('mdblist.token')
        if not token:
            return None
        status, data = self._fetch_profile(token)
        if status != 200:
            return None
        for field in API_KEY_FIELDS:
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _collect_api_key_manually(self):
        from acctmgr.modules.auth.remote_entry import RemoteKeyEntry

        if RemoteKeyEntry.available():
            from acctmgr.modules.auth.mdblist_select import select_api_key_method

            choice = select_api_key_method()
            if choice < 0:
                return False
            if choice == 0:
                result = RemoteKeyEntry(
                    'MDBList API Key', self._validate_api_key, icon=mdb_icon,
                    field_label='MDBList API Key', help_url=API_KEY_PAGE).run()
                if result:
                    self._save_api_key(result['value'], result.get('username'))
                    return True
                if not control.yesnoDialog(
                        "Phone entry did not complete.\nType the key with the remote instead?",
                        ADDON_NAME, 'No', 'Yes'):
                    return False

        for attempt in range(MAX_KEY_ATTEMPTS):
            key = self._prompt_keyboard()
            if not key:
                return False
            ok, msg, username = self.fetch_user(key)
            if ok:
                self._save_api_key(key, username)
                return True
            last = attempt == MAX_KEY_ATTEMPTS - 1
            if last or not control.yesnoDialog(
                    f"That API key was rejected ({msg}).\nTry again?", ADDON_NAME, 'No', 'Yes'):
                self._notify_user('MDBList API key rejected')
                return False
        return False

    def _prompt_keyboard(self):
        keyboard = xbmc.Keyboard("", "MDBList API Key (tip: type with the Kodi phone remote app)")
        keyboard.doModal()
        if not keyboard.isConfirmed():
            return None
        return (keyboard.getText() or "").strip()

    def _fetch_profile(self, access_token):
        """Fetch user profile with Bearer token, returning status code and payload dict."""
        try:
            response = requests.get(
                USER_URL, headers={'Authorization': 'Bearer %s' % access_token}, timeout=15)
        except Exception as e:
            log_utils.error(f"MDBList profile request failed: {e}")
            return None, {}
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, (data if isinstance(data, dict) else {})

    def _oauth_session_valid(self):
        """Return True if stored token works or refreshes successfully."""
        token = self._get_setting('mdblist.token')
        if not token or not self._get_setting('mdblist.refresh'):
            return False
        status, _ = self._fetch_profile(token)
        if status == 200:
            return True
        return status in (401, 403) and self.refresh_token()

    def _migrate_legacy_settings(self):
        """Move verified Bearer tokens from apikey setting to token setting."""
        legacy = (self._get_setting('mdblist.apikey') or '').strip()
        if not legacy or self._get_setting('mdblist.token') or not self._get_setting('mdblist.refresh'):
            return False
        status, data = self._fetch_profile(legacy)
        if status != 200:
            return False
        self._set_setting('mdblist.token', legacy)
        self._set_setting('mdblist.apikey', '')
        self._fill_username((data.get('username') or '').strip())
        self.token = legacy
        log_utils.log("MDBList: migrated OAuth token out of 'mdblist.apikey'", __name__, log_utils.LOGDEBUG)
        return True

    def _client_id(self):
            return (self._get_setting('mdblist.client_id') or DEFAULT_CLIENT_ID).strip()

    def auth_device(self):
        """Run standalone device code authentication."""
        if not self._client_id():
            self._notify_user("MDBList client ID not configured")
            log_utils.error("MDBList: 'mdblist.client_id' setting is empty; "
                            "register a Device Code app at mdblist.com/developer")
            return False
        return self.authenticate()

    def get_device_code(self):
        try:
            response = requests.post(DEVICE_AUTH_URL, data={
                'client_id': self._client_id(),
                'scope': OAUTH_SCOPE,
            }, timeout=15)
            data = response.json()
        except Exception as e:
            log_utils.error(f"MDBList device code request failed: {e}")
            return None

        try:
            return {
                'device_code': data['device_code'],
                'user_code': data['user_code'],
                'verification_url': data['verification_uri'],
                'expires_in': int(data['expires_in']),
                'interval': int(data['interval']),
                'qr_data': data.get('verification_uri_complete'),
            }
        except (KeyError, TypeError, ValueError) as e:
            log_utils.error(f"MDBList device code response malformed: {e} - {str(data)[:200]}")
            return None

    def poll_token(self, device_data):
        try:
            response = requests.post(TOKEN_URL, data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'device_code': device_data['device_code'],
                'client_id': self._client_id(),
            }, timeout=15)
        except requests.exceptions.RequestException as e:
            log_utils.log(f"MDBList poll request error: {e}", __name__, log_utils.LOGDEBUG)
            return

        try:
            payload = response.json()
        except ValueError:
            log_utils.log(f"MDBList poll: HTTP {response.status_code} response was not valid JSON",
                          __name__, log_utils.LOGDEBUG)
            return

        if response.status_code == 200:
            if isinstance(payload, dict) and payload.get('access_token') and payload.get('refresh_token'):
                self.token_data = payload
            else:
                self.abort_auth('MDBList returned an incomplete token response')
            return

        error = payload.get('error') if isinstance(payload, dict) else None
        if error == 'authorization_pending':
            return
        if error == 'slow_down':
            self.increase_poll_interval(5)
            return
        if error == 'access_denied':
            self.abort_auth('MDBList authorization was declined')
            return
        if error == 'expired_token':
            self.abort_auth(self.msg_expired)
            return

        log_utils.log(f"MDBList poll unexpected: HTTP {response.status_code} - {str(payload)[:200]}",
                      __name__, log_utils.LOGDEBUG)

    def save_account(self):
        data = self.token_data
        if not data or not data.get('access_token') or not data.get('refresh_token'):
            return False
        try:
            expires_at = int(time.time()) + int(data.get('expires_in') or 2592000)
            username = self._fetch_username(data['access_token'])
            self._set_setting('mdblist.token', data['access_token'])
            self._set_setting('mdblist.refresh', data['refresh_token'])
            self._set_setting('mdblist.expires', str(expires_at))
            self._set_setting('mdblist.username', username)
            self.token = data['access_token']
            return True
        except Exception as e:
            log_utils.error(f"MDBList save_account failed: {e}")
            return False

    def _fetch_username(self, access_token):
        """Fetch username associated with access token, or empty string on failure."""
        status, data = self._fetch_profile(access_token)
        if status != 200:
            return ''
        return (data.get('username') or '').strip()

    def refresh_token(self):
        refresh = self._get_setting('mdblist.refresh')
        client_id = self._client_id()
        if not refresh or not client_id:
            return False

        try:
            response = requests.post(TOKEN_URL, data={
                'grant_type': 'refresh_token',
                'refresh_token': refresh,
                'client_id': client_id,
            }, timeout=15)
            payload = response.json()
        except Exception as e:
            log_utils.error(f"MDBList refresh_token request failed: {e}")
            return False

        if response.status_code != 200 or not isinstance(payload, dict) or not payload.get('access_token'):
            error = payload.get('error', '') if isinstance(payload, dict) else ''
            if error == 'invalid_grant':
                log_utils.log('MDBList refresh token invalid - user must re-authorize',
                              level=log_utils.LOGWARNING)
            else:
                log_utils.error(f"MDBList refresh failed: HTTP {response.status_code} - {payload}")
            return False

        expires_at = int(time.time()) + int(payload.get('expires_in') or 2592000)
        self._set_setting('mdblist.token', payload['access_token'])
        self._set_setting('mdblist.refresh', payload.get('refresh_token') or refresh)
        self._set_setting('mdblist.expires', str(expires_at))
        self.token = payload['access_token']
        return True

    def revoke(self):
        token = self._get_setting('mdblist.token')
        if token:
            try:
                requests.post(REVOKE_URL, data={
                    'token': token,
                    'client_id': self._client_id(),
                }, timeout=15)
            except Exception as e:
                log_utils.error(f"MDBList revoke request failed: {e}")

        self._set_setting('mdblist.apikey', '')
        self._set_setting('mdblist.token', '')
        self._set_setting('mdblist.refresh', '')
        self._set_setting('mdblist.expires', '')
        self._set_setting('mdblist.username', '')
