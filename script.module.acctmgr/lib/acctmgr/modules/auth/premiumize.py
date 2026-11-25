# -*- coding: utf-8 -*-
import time
import requests
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.auth.base_auth import BaseDeviceAuth

pm_icon = control.joinPath(control.iconsPath(), 'premiumize.png')
DEFAULT_CLIENT_ID = '671951559'
TOKEN_URL = 'https://www.premiumize.me/token'
ACCOUNT_INFO_URL = 'https://www.premiumize.me/api/account/info'

class Premiumize(BaseDeviceAuth):
	provider_name = "Premiumize"

	def __init__(self):
		self.token = control.setting('premiumize.token')

	def auth(self):
		return self.authenticate()

	def _client_id(self):
		return (control.setting('premiumize.client_id') or DEFAULT_CLIENT_ID).strip()

	def get_device_code(self):
		try:
			response = requests.post(TOKEN_URL, data={
				'response_type': 'device_code',
				'client_id': self._client_id()
			}, timeout=15)
			payload = response.json()
		except Exception as e:
			log_utils.error(f"Premiumize device code request failed: {e}")
			return None

		try:
			return {
				'device_code': payload['device_code'],
				'user_code': payload['user_code'],
				'verification_url': payload['verification_uri'],
				'expires_in': int(payload['expires_in']),
				'interval': int(payload.get('interval', 5)),
				'qr_data': f"{payload['verification_uri']}?user_code={payload['user_code']}"
			}
		except (KeyError, TypeError, ValueError) as e:
			log_utils.error(f"Premiumize device code response malformed: {e} - {str(payload)[:200]}")
			return None

	def poll_token(self, device_data):
		try:
			response = requests.post(TOKEN_URL, data={
				'grant_type': 'device_code',
				'code': device_data['device_code'],
				'client_id': self._client_id()
			}, timeout=15)
		except requests.exceptions.RequestException as e:
			log_utils.log(f"Premiumize poll request error: {e}", __name__, log_utils.LOGDEBUG)
			return

		try:
			payload = response.json()
		except ValueError:
			log_utils.log(f"Premiumize poll: HTTP {response.status_code} not valid JSON", __name__, log_utils.LOGDEBUG)
			return

		if response.status_code == 200 and payload.get('access_token'):
			self.token_data = payload
			return

		error = payload.get('error')

		if error == 'authorization_pending':
			return
		if error == 'slow_down':
			self.increase_poll_interval(5)
			return
		if error == 'access_denied':
			self.abort_auth('Premiumize authorization was declined')
			return
		if error == 'invalid_grant':
			self.abort_auth(self.msg_expired)
			return

		log_utils.log(f"Premiumize poll unexpected response: HTTP {response.status_code} - {str(payload)[:200]}", __name__, log_utils.LOGDEBUG)

	def save_account(self):
		data = self.token_data
		if not data or not data.get('access_token'):
			return False

		access_token = data['access_token']
		try:
			username = self._fetch_username(access_token)
			control.setSetting('premiumize.token', access_token)
			control.setSetting('premiumize.username', username)
			self.token = access_token
			return True
		except Exception as e:
			log_utils.error(f"Premiumize save_account failed: {e}")
			return False

	def _fetch_username(self, access_token):
		try:
			response = requests.get(
				ACCOUNT_INFO_URL,
				headers={'Authorization': f'Bearer {access_token}'},
				timeout=15
			)
			if response.status_code != 200:
				return 'Premiumize User'

			payload = response.json()
			if payload.get('status') == 'success':
				return str(payload.get('customer_id', 'Premiumize User')).strip()
			return 'Premiumize User'
		except Exception as e:
			log_utils.error(f"Premiumize username fetch failed: {e}")
			return 'Premiumize User'

	def refresh_token(self):
		# The Premiumize device flow uses a static token without rotation.
		# Returning True safely passes generic refresh checks.
		token = control.setting('premiumize.token')
		if token:
			self.token = token
			return True
		return False

	def revoke(self):
		control.setSetting('premiumize.token', '')
		control.setSetting('premiumize.username', '')

	def account_info_to_dialog(self):
		from datetime import datetime
		import math

		if not self.token:
			return

		try:
			response = requests.get(
				ACCOUNT_INFO_URL,
				headers={'Authorization': f'Bearer {self.token}'},
				timeout=15
			)
			if response.status_code != 200:
				return

			accountInfo = response.json()
			if accountInfo.get('status') != 'success':
				return

			expires = datetime.fromtimestamp(accountInfo['premium_until'])
			days_remaining = (expires - datetime.today()).days
			expires_str = expires.strftime("%A, %B %d, %Y")
			points_used = int(math.floor(float(accountInfo['space_used']) / 1073741824.0))
			space_used = float(int(accountInfo['space_used'])) / 1073741824
			percentage_used = str(round(float(accountInfo['limit_used']) * 100.0, 1))

			items = [
				control.lang(40040) % accountInfo.get('customer_id', 'Unknown'),
				control.lang(40041) % expires_str,
				control.lang(40042) % days_remaining,
				control.lang(40043) % points_used,
				control.lang(40044) % space_used,
				control.lang(40045) % percentage_used,
			]

			return control.selectDialog(items, 'Premiumize')
		except Exception as e:
			log_utils.error(f"Premiumize account_info_to_dialog failed: {e}")
			return
