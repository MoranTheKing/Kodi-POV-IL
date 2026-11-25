# -*- coding: utf-8 -*-
import requests
from requests.adapters import HTTPAdapter

from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.auth.base_auth import BaseDeviceAuth


# Variables
oc_icon = control.joinPath(control.iconsPath(), 'offcloud.png')

BASE_HOST = "https://offcloud.com"
API_BASE = f"{BASE_HOST}/api"
OAUTH_DEVICE_CODE_URL = f"{BASE_HOST}/oauth/device/code"
OAUTH_TOKEN_URL = f"{BASE_HOST}/oauth/token"
ACTIVATE_URL = "https://offcloud.com/activate"

TIMEOUT = 10.0

session = requests.Session()
session.mount("https://offcloud.com", HTTPAdapter(max_retries=1, pool_maxsize=20))


class Offcloud(BaseDeviceAuth):
	provider_name = 'Offcloud'
	icon = oc_icon

	def auth(self):
		# Already authorized check
		if control.setting('offcloud.token'):
			control.notification(message='Offcloud is already authorized!', icon=oc_icon)
			return False
		return self.authenticate()

	def get_device_code(self):
		# Request device code
		resp = session.post(OAUTH_DEVICE_CODE_URL, timeout=TIMEOUT)
		resp.raise_for_status()
		result = resp.json()

		device_code = result.get('device_code')
		user_code = result.get('user_code')
		verification_uri = result.get('verification_uri') or ACTIVATE_URL
		if not device_code or not user_code:
			raise ValueError('Offcloud device response missing device_code or user_code')

		return {
			'device_code': device_code,
			'user_code': user_code,
			'verification_url': verification_uri,
			'qr_data': result.get('verification_uri_complete') or verification_uri,
			'interval': result.get('interval', 5),
			'expires_in': result.get('expires_in', 600),
		}

	def poll_token(self, device_data):
		# Poll for access token
		data = {
			'device_code': device_data['device_code'],
			'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
		}
		try:
			resp = session.post(OAUTH_TOKEN_URL, json=data, timeout=TIMEOUT)
			if resp.ok:
				result = resp.json()
				if result.get('access_token'):
					self.token_data = result
				return

			# Pending authorization is expected while the user enters the code.
			if resp.status_code in (400, 403):
				try:
					error = resp.json().get('error', '')
				except ValueError:
					error = ''
				if error in ('authorization_pending', 'pending', ''):
					return
				if error == 'slow_down':
					self.increase_poll_interval()
					return
				if error in ('access_denied', 'expired_token', 'invalid_grant'):
					self.abort_auth('Offcloud authorization failed: %s' % error)
					return
			log_utils.error('Offcloud token polling HTTP %s' % resp.status_code)
		except requests.RequestException as e:
			log_utils.error('Offcloud token polling failed: %s' % e)

	def save_account(self):
		# Validate token
		token = (self.token_data or {}).get('access_token')
		if not token:
			return False
		try:
			resp = session.get(f'{API_BASE}/account/info', params={'key': token}, timeout=TIMEOUT)
			resp.raise_for_status()
			info = resp.json()
			username = info.get('username') or info.get('email') or str(info.get('user_id', 'Offcloud'))
		except Exception as e:
			log_utils.error('Offcloud token validation failed: %s' % e)
			return False

		# Save token & userid
		control.setSetting('offcloud.token', token)
		control.setSetting('offcloud.userid', str(username))
		return True
