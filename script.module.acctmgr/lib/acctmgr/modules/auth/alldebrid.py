# -*- coding: utf-8 -*-
import requests
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.auth.base_auth import BaseDeviceAuth

ad_icon = control.joinPath(control.iconsPath(), 'alldebrid.png')
AGENT = 'AccountManager'

class AllDebrid(BaseDeviceAuth):
	provider_name = "All-Debrid"

	def __init__(self):
		self.token = control.setting('alldebrid.token')

	def auth(self):
		return self.authenticate()

	def get_device_code(self):
		try:
			response = requests.get(
				'https://api.alldebrid.com/v4.1/pin/get',
				params={'agent': AGENT},
				timeout=15
			)
			payload = response.json()
		except Exception as e:
			log_utils.error(f"AllDebrid device code request failed: {e}")
			return None

		if payload.get('status') != 'success':
			log_utils.error(f"AllDebrid device code request error: {payload}")
			return None

		data = payload.get('data', {})
		try:
			return {
				'device_code': data['check'],
				'user_code': data['pin'],
				'verification_url': data.get('base_url', 'https://alldebrid.com/pin/'),
				'expires_in': int(data.get('expires_in', 600)),
				'interval': 5,
				'qr_data': data.get('user_url')
			}
		except (KeyError, TypeError, ValueError) as e:
			log_utils.error(f"AllDebrid device code response malformed: {e} - {str(data)[:200]}")
			return None

	def poll_token(self, device_data):
		try:
			response = requests.post(
				'https://api.alldebrid.com/v4/pin/check',
				params={'agent': AGENT},
				data={
					'check': device_data['device_code'],
					'pin': device_data['user_code']
				},
				timeout=15
			)
		except requests.exceptions.RequestException as e:
			log_utils.log(f"AllDebrid poll request error: {e}", __name__, log_utils.LOGDEBUG)
			return

		try:
			payload = response.json()
		except ValueError:
			log_utils.log(f"AllDebrid poll: HTTP {response.status_code} not valid JSON", __name__, log_utils.LOGDEBUG)
			return

		status = payload.get('status')

		if status == 'success':
			data = payload.get('data', {})
			if data.get('activated') is True:
				apikey = data.get('apikey')
				if apikey:
					self.token_data = {'apikey': apikey}
				else:
					self.abort_auth('AllDebrid returned activated but missing apikey')
			# If activated is false, just return. The RepeatTimer will poll again next tick.
			return

		if status == 'error':
			error = payload.get('error', {})
			error_code = error.get('code')
			if error_code in ('PIN_EXPIRED', 'PIN_INVALID'):
				self.abort_auth(f"AllDebrid PIN error: {error_code}")
				return

			log_utils.log(f"AllDebrid poll unexpected error: {error_code} - {error.get('message')}", __name__, log_utils.LOGDEBUG)
			return

		log_utils.log(f"AllDebrid poll unexpected response: {str(payload)[:200]}", __name__, log_utils.LOGDEBUG)

	def save_account(self):
		data = self.token_data
		if not data or not data.get('apikey'):
			return False

		apikey = data['apikey']
		try:
			username = self._fetch_username(apikey)
			control.setSetting('alldebrid.token', apikey)
			control.setSetting('alldebrid.apikey', apikey) # Retained for backward compatibility
			control.setSetting('alldebrid.username', username)
			self.token = apikey
			return True
		except Exception as e:
			log_utils.error(f"AllDebrid save_account failed: {e}")
			return False

	def _fetch_username(self, apikey):
		try:
			response = requests.get(
				'https://api.alldebrid.com/v4/user',
				params={'agent': AGENT},
				headers={'Authorization': f'Bearer {apikey}'},
				timeout=15
			)
			if response.status_code != 200:
				return ''

			payload = response.json()
			if payload.get('status') == 'success':
				user_data = payload.get('data', {}).get('user', {})
				return (user_data.get('username') or '').strip()
			return ''
		except Exception as e:
			log_utils.error(f"AllDebrid username fetch failed: {e}")
			return ''

	def refresh_token(self):
		# AllDebrid uses a static API key, no refresh rotation needed.
		# This safely returns True so generic refresh triggers don't fail.
		token = control.setting('alldebrid.token')
		if token:
			self.token = token
			return True
		return False

	def revoke(self):
		# No remote revoke endpoint exists in the AD API docs. Standard local cleanup.
		control.setSetting('alldebrid.token', '')
		control.setSetting('alldebrid.apikey', '')
		control.setSetting('alldebrid.username', '')

	def account_info_to_dialog(self):
		from datetime import datetime
		if not self.token:
			return

		try:
			response = requests.get(
				'https://api.alldebrid.com/v4/user',
				params={'agent': AGENT},
				headers={'Authorization': f'Bearer {self.token}'},
				timeout=15
			)
			if response.status_code != 200:
				return

			payload = response.json()
			if payload.get('status') != 'success':
				return

			user = payload.get('data', {}).get('user', {})
			if not user:
				return

			username = user.get("username", "")
			email = user.get("email", "")
			status = "Premium" if user.get("isPremium") else "Not Active"
			expires = datetime.fromtimestamp(user.get("premiumUntil", 0))
			days_remaining = (expires - datetime.today()).days

			items = [
				control.lang(40036) % username,
				control.lang(40035) % email,
				control.lang(40037) % status,
				control.lang(40041) % expires,
				control.lang(40042) % days_remaining,
			]
			return control.selectDialog(items, "AllDebrid")
		except Exception as e:
			log_utils.error(f"AllDebrid account_info_to_dialog failed: {e}")
			return