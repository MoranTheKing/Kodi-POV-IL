# -*- coding: utf-8 -*-
import json
import requests
import xbmc
import xbmcaddon
import xbmcgui
from requests.adapters import HTTPAdapter
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.auth.base_auth import BaseDeviceAuth

# Variables
FormatDateTime = "%Y-%m-%dT%H:%M:%S.%fZ"
rest_base_url = 'https://api.real-debrid.com/rest/1.0/'
oauth_base_url = 'https://api.real-debrid.com/oauth/v2/'
device_code_url = 'device/code?%s'
credentials_url = 'device/credentials?%s'
rd_icon = control.joinPath(control.iconsPath(), 'realdebrid.png')
DEFAULT_CLIENT_ID = 'X245A4XAIBGVM'  # Real-Debrid open-source client id

class RealDebrid(BaseDeviceAuth):
	name = "Real-Debrid"
	provider_name = name

	def __init__(self):
		self.token = control.setting('realdebrid.token')
		self.client_ID = control.setting('realdebrid.client_id')
		if self.client_ID == '':
			self.client_ID = DEFAULT_CLIENT_ID
		self.secret = control.setting('realdebrid.secret')
		self.device_code = ''

	def _get(self, url, fail_check=False, token_ck=False):
		try:
			original_url = url
			url = rest_base_url + url
			if self.token == '':
				log_utils.log('No Real Debrid Token Found', __name__, log_utils.LOGDEBUG)
				return None
			if '?' not in url:
				url += "?auth_token=%s" % self.token
			else:
				url += "&auth_token=%s" % self.token
			response = requests.get(url, timeout=15).json()
			if 'bad_token' in str(response) or 'Bad Request' in str(response):
				if not fail_check:
					if self.refresh_token() and token_ck:
						return
					response = self._get(original_url, fail_check=True)
			return response
		except Exception as e:
			log_utils.error(f"RealDebrid GET failed: {e}")
		return None

	def _post(self, url, data):
		original_url = url
		url = rest_base_url + url
		if self.token == '':
			log_utils.log('No Real Debrid Token Found', __name__, log_utils.LOGDEBUG)
			return None
		if '?' not in url:
			url += "?auth_token=%s" % self.token
		else:
			url += "&auth_token=%s" % self.token
		response = requests.post(url, data=data, timeout=15).text
		if 'bad_token' in response or 'Bad Request' in response:
			self.refresh_token()
			response = self._post(original_url, data)
		elif 'error' in response:
			response = json.loads(response)
			control.notification(title='default', message=response.get('error'), icon=rd_icon)
			return None
		try:
			return json.loads(response)
		except Exception as e:
			log_utils.error(f"RealDebrid POST failed to parse response: {e}")
			return response

	def get_device_code(self):
		self.secret = ''
		self.client_ID = DEFAULT_CLIENT_ID
		self.device_code = ''
		try:
			url = 'client_id=%s&new_credentials=yes' % self.client_ID
			url = oauth_base_url + device_code_url % url
			response = requests.get(url, timeout=15).json()
			return {
				'device_code': response['device_code'],
				'user_code': response['user_code'],
				'verification_url': response.get('verification_url') or 'https://real-debrid.com/device',
				'expires_in': int(response['expires_in']),
				'interval': int(response['interval']),
				'qr_data': response.get('direct_verification_url'),
			}
		except Exception as e:
			log_utils.error(f"RealDebrid device code request failed: {e}")
			return None

	def poll_token(self, device_data):
		# Runs in the RepeatTimer thread
		try:
			url = 'client_id=%s&code=%s' % (self.client_ID, device_data['device_code'])
			url = oauth_base_url + credentials_url % url
			response = requests.get(url, timeout=15).json()
		except (requests.exceptions.RequestException, ValueError) as e:
			log_utils.log(f"RealDebrid credentials poll failed: {e}", __name__, log_utils.LOGDEBUG)
			return

		if not isinstance(response, dict) or 'error' in response:
			return  # authorization_pending

		client_id = response.get('client_id')
		secret = response.get('client_secret')
		if not client_id or not secret:
			return

		try:
			token_response = self._post_token(client_id, secret, device_data['device_code'])
			payload = token_response.json()
		except (requests.exceptions.RequestException, ValueError) as e:
			log_utils.log(f"RealDebrid token exchange failed: {e}", __name__, log_utils.LOGDEBUG)
			return

		if (not isinstance(payload, dict) or 'error' in payload
				or not payload.get('access_token') or not payload.get('refresh_token')):
			log_utils.log(f"RealDebrid token exchange rejected: {str(payload)[:200]}", __name__, log_utils.LOGDEBUG)
			return  # retried on the next tick

		self.token_data = {
			'client_id': client_id,
			'client_secret': secret,
			'device_code': device_data['device_code'],
			'access_token': payload['access_token'],
			'refresh_token': payload['refresh_token'],
		}

	def save_account(self):
		data = self.token_data
		if not data:
			return False
		try:
			self.device_code = data['device_code']
			self._persist_credentials(data['client_id'], data['client_secret'],
									  data['access_token'], data['refresh_token'])
			return True
		except Exception as e:
			log_utils.error(f'Real Debrid save_account failed: {e}')
			return False

	def auth(self):
		return self.authenticate()

	def account_info(self):
		return self._get('user')

	def account_info_to_dialog(self):
		from datetime import datetime
		import time
		try:
			userInfo = self.account_info()
			try:
				expires = datetime.strptime(userInfo['expiration'], FormatDateTime)
			except Exception as e:
				log_utils.error(f"RealDebrid date parse failed: {e}")
				expires = datetime(*(time.strptime(userInfo['expiration'], FormatDateTime)[0:6]))
			days_remaining = (expires - datetime.today()).days
			expires = expires.strftime("%A, %B %d, %Y")
			items = []
			items += [control.lang(40035) % userInfo['email']]
			items += [control.lang(40036) % userInfo['username']]
			items += [control.lang(40037) % userInfo['type'].capitalize()]
			items += [control.lang(40041) % expires]
			items += [control.lang(40042) % days_remaining]
			items += [control.lang(40038) % userInfo['points']]
			return control.selectDialog(items, 'Real-Debrid')
		except Exception as e:
			log_utils.error(f"RealDebrid account dialog failed: {e}")
		return

	def refresh_token(self):
		try:
			self.client_ID = control.setting('realdebrid.client_id')
			self.secret = control.setting('realdebrid.secret')
			self.device_code = control.setting('realdebrid.refresh')
			if not self.client_ID or not self.secret or not self.device_code:
				return False
			log_utils.log(
				'Refreshing Expired Real Debrid Token: | %s | %s |' % (self.client_ID, self.device_code),
				__name__, log_utils.LOGDEBUG
			)
			success, error = self.get_token()
			if not success:
				if not 'Temporarily Down For Maintenance' in str(error):
					if error and any(value == error.get('error_code') for value in [9, 12, 13, 14]):
						self.revoke()
						control.notification(message='Real-Debrid Auth revoked due to:  %s' % error.get('error'), icon=rd_icon)
				log_utils.log('Unable to Refresh Real Debrid Token: %s' % (error.get('error') if error else ''), level=log_utils.LOGWARNING)
				return False
			else:
				log_utils.log('Real Debrid Token Successfully Refreshed', level=log_utils.LOGDEBUG)
				return True
		except Exception as e:
			log_utils.error(f"RealDebrid refresh failed: {e}")
			return False

	def _post_token(self, client_id, secret, code):
		return requests.post(oauth_base_url + 'token', data={
			'client_id': client_id,
			'client_secret': secret,
			'code': code,
			'grant_type': 'http://oauth.net/grant_type/device/1.0'
		}, timeout=15)

	def _persist_credentials(self, client_id, secret, access_token, refresh_token):
		self.client_ID = client_id
		self.secret = secret
		self.token = access_token
		control.sleep(500)
		account_info = self.account_info()
		username = account_info['username']
		control.setSetting('realdebrid.username', username)
		control.setSetting('realdebrid.client_id', client_id)
		control.setSetting('realdebrid.secret', secret)
		control.setSetting('realdebrid.token', access_token)
		control.setSetting('realdebrid.refresh', refresh_token)

	def get_token(self):
		try:
			response = self._post_token(self.client_ID, self.secret, self.device_code)

			if '[204]' in str(response):
				return False, str(response)
			if 'Temporarily Down For Maintenance' in response.text:
				control.notification(message='Real-Debrid Temporarily Down For Maintenance', icon=rd_icon)
				log_utils.log('Real-Debrid Temporarily Down For Maintenance', level=log_utils.LOGWARNING)
				return False, response.text
			else:
				response = response.json()

			if 'error' in str(response):
				log_utils.log('response=%s' % str(response), __name__)
				message = response.get('error')
				control.notification(message=message, icon=rd_icon)
				log_utils.log('Real-Debrid Error:  %s' % message, level=log_utils.LOGWARNING)
				return False, response

			self._persist_credentials(self.client_ID, self.secret,
									  response['access_token'], response['refresh_token'])
			return True, None
		except Exception as e:
			log_utils.error(f'Real Debrid Authorization Failed: {e}')
			return False, None

	def revoke(self):
		try:
			control.setSetting('realdebrid.client_id', '')
			control.setSetting('realdebrid.secret', '')
			control.setSetting('realdebrid.token', '')
			control.setSetting('realdebrid.refresh', '')
			control.setSetting('realdebrid.username', '')
		except Exception as e:
			log_utils.error(f"RealDebrid revoke failed: {e}")
