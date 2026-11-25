# -*- coding: utf-8 -*-
import requests
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.auth.base_auth import BaseDeviceAuth

tb_icon = control.joinPath(control.iconsPath(), 'torbox.png')

API_BASE = "https://api.torbox.app"
DEVICE_START_URL = f"{API_BASE}/v1/api/user/auth/device/start"
DEVICE_TOKEN_URL = f"{API_BASE}/v1/api/user/auth/device/token"
USER_URL = f"{API_BASE}/v1/api/user/me"

HEADERS = {
	"User-Agent": "Kodi/21 acctmgr",
	"Accept": "application/json"
}


class Torbox(BaseDeviceAuth):
	provider_name = "TorBox"

	def __init__(self):
		self.token = control.setting('torbox.token')

	def auth(self):
		return self.authenticate()

	def get_device_code(self):
		try:
			response = requests.get(
				DEVICE_START_URL,
				params={'app': 'AccountManager'},
				headers=HEADERS,
				timeout=15
			)
			payload = response.json()
		except Exception as e:
			log_utils.error(f"TorBox device code request failed: {e}")
			return None

		if not payload.get('success'):
			log_utils.error(f"TorBox device code request error: {payload}")
			return None

		data = payload.get('data', {})
		try:
			# Torbox API specs allow verification_url or friendly_verification_url
			url = data.get('verification_url') or data.get('friendly_verification_url')
			return {
				'device_code': data['device_code'],
				'user_code': data['code'],
				'verification_url': url,
				'expires_in': int(data.get('expires_in', 600)),
				'interval': int(data.get('interval', 5)),
				'qr_data': url
			}
		except (KeyError, TypeError, ValueError) as e:
			log_utils.error(f"TorBox device code response malformed: {e} - {str(data)[:200]}")
			return None

	def poll_token(self, device_data):
		try:
			response = requests.post(
				DEVICE_TOKEN_URL,
				json={'device_code': device_data['device_code']},
				headers=HEADERS,
				timeout=15
			)
		except requests.exceptions.RequestException as e:
			log_utils.log(f"TorBox poll request error: {e}", __name__, log_utils.LOGDEBUG)
			return

		try:
			payload = response.json()
		except ValueError:
			log_utils.log(f"TorBox poll: HTTP {response.status_code} not valid JSON", __name__, log_utils.LOGDEBUG)
			return

		# Wait for successful token assignment
		if payload.get('success') is True:
			data = payload.get('data', {})
			access_token = data.get('access_token')
			if access_token:
				self.token_data = {'access_token': access_token}
				return

		# TorBox returns DEVICE_CODE_NOT_USED while waiting for the user
		# to complete device authorization. This is an expected pending state.
		error = payload.get('error')
		if error == 'DEVICE_CODE_NOT_USED':
			return

		# If the token is genuinely expired, the BaseDeviceAuth loop handles the timeout
		# automatically via expires_in. Log only genuinely unexpected responses.
		log_utils.log(f"TorBox poll unexpected: HTTP {response.status_code} - {str(payload)[:200]}", __name__, log_utils.LOGDEBUG)

	def save_account(self):
		data = self.token_data
		if not data or not data.get('access_token'):
			return False

		access_token = data['access_token']
		try:
			user_data = self._fetch_user_data(access_token)

			acct_id = user_data.get('id', '')
			email = user_data.get('email', '')
			is_subscribed = user_data.get('is_subscribed')
			plan = user_data.get('plan')
			expires = user_data.get('premium_expires_at')

			if is_subscribed is True or expires:
				auth_status = "Premium"
			elif plan == 1:
				auth_status = "Basic"
			else:
				auth_status = "Authorized"

			control.setSetting('torbox.token', access_token)
			control.setSetting('torbox.acct_id', str(acct_id))
			control.setSetting('torbox.auth_status', auth_status)
			control.setSetting('torbox.username', email)

			self.token = access_token
			return True
		except Exception as e:
			log_utils.error(f"TorBox save_account failed: {e}")
			return False

	def _fetch_user_data(self, token):
		try:
			auth_headers = HEADERS.copy()
			auth_headers['Authorization'] = f'Bearer {token}'

			response = requests.get(
				USER_URL,
				headers=auth_headers,
				timeout=15
			)
			if response.status_code == 200:
				payload = response.json()
				return payload.get('data', {})
		except Exception as e:
			log_utils.error(f"TorBox user data fetch failed: {e}")
		return {}

	def refresh_token(self):
		token = control.setting('torbox.token')
		if token:
			self.token = token
			return True
		return False

	def revoke(self):
		control.setSetting('torbox.token', '')
		control.setSetting('torbox.acct_id', '')
		control.setSetting('torbox.auth_status', '')
		control.setSetting('torbox.username', '')

	def account_info_to_dialog(self):
		if not self.token:
			return

		try:
			user_data = self._fetch_user_data(self.token)
			if not user_data:
				return

			email = user_data.get('email', 'Unknown')
			acct_id = user_data.get('id', 'Unknown')
			is_subscribed = user_data.get('is_subscribed')
			plan = user_data.get('plan')
			expires = user_data.get('premium_expires_at')

			if is_subscribed is True or expires:
				auth_status = "Premium"
			elif plan == 1:
				auth_status = "Basic"
			else:
				auth_status = "Authorized"

			items = [
				f"Email: {email}",
				f"Account ID: {acct_id}",
				f"Status: {auth_status}"
			]

			if expires:
				# Format expiry date if available
				from datetime import datetime
				try:
					if isinstance(expires, (int, float)):
						expires_str = datetime.fromtimestamp(expires).strftime("%A, %B %d, %Y")
					else:
						expires_str = str(expires)
					items.append(f"Expires: {expires_str}")
				except Exception:
					items.append(f"Expires: {expires}")

			return control.selectDialog(items, 'TorBox')
		except Exception as e:
			log_utils.error(f"TorBox account_info_to_dialog failed: {e}")
			return