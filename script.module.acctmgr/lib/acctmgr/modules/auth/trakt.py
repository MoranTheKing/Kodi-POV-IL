# -*- coding: utf-8 -*-
import xbmc, xbmcaddon
import os
import requests
import time
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.auth.base_auth import BaseDeviceAuth

# Variables
trakt_icon = control.joinPath(control.iconsPath(), 'trakt.png')

class Trakt(BaseDeviceAuth):
	provider_name = 'Trakt'

	def __init__(self):
		self.api_endpoint = 'https://api.trakt.tv/%s'
		self.client_id = self.traktClientID()
		self.client_secret = self.traktClientSecret()
		self.expires_at = control.setting('trakt.expires')
		self.token = control.setting('trakt.token')

	def call(self, path, data=None, with_auth=True, method=None, return_str=False, suppress_error_notification=False):
		try:
			def error_notification(line1, error):
				if suppress_error_notification: return
				return control.notification(title='default', message='%s: %s' % (line1, error), icon=trakt_icon)

			def send_query():
				resp = None
				if with_auth:
					try:
						try:
							expires_at = float(control.setting('trakt.expires') or 0)
						except Exception as e:
							log_utils.error(f"Error converting expires_at to float: {e}")
							expires_at = 0

						if expires_at > 0 and time.time() >= expires_at:
							if not self.refresh_token():
								return None
					except Exception as e:
						log_utils.error(f"Error refreshing token: {e}")
						pass
					headers['Authorization'] = 'Bearer ' + (control.setting('trakt.token') or self.token)

				try:
					request_method = (method or ('POST' if data is not None else 'GET')).upper()
					if request_method == 'POST':
						resp = requests.post(self.api_endpoint % path, json=data, headers=headers, timeout=timeout)
					else:
						resp = requests.get(self.api_endpoint % path, headers=headers, timeout=timeout)
				except requests.exceptions.RequestException as e:
					error_notification('Trakt Error', str(e))
				except Exception as e:
					error_notification('', str(e))
				return resp

			timeout = 15.0
			headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': self.traktClientID()}
			response = send_query()

			if response is None:
				return None

			response.encoding = 'utf-8'
			if return_str:
				return response

			if response.status_code not in (200, 201):
				try:
					error_result = response.json()
				except Exception:
					try:
						error_result = response.text
					except Exception:
						error_result = ''
				log_utils.error(f"Trakt API {path} failed: HTTP {response.status_code} - {error_result}")
				return None

			try:
				result = response.json()
			except Exception as e:
				log_utils.error(f"Error parsing JSON response: {e}")
				result = None

			return result
		except Exception as e:
			log_utils.error(f"Trakt call failed: {e}")

	def get_device_code(self):
                data = {'client_id': self.traktClientID()}
                result = self.call("oauth/device/code", data=data, with_auth=False, method='POST')
                if result:
                        result['qr_data'] = f"{result['verification_url'].rstrip('/')}/{result['user_code']}"
                return result

	def poll_token(self, device_data):
		# Runs in the RepeatTimer thread
		data = {
			"code": device_data["device_code"],
			"client_id": self.traktClientID(),
			"client_secret": self.traktClientSecret()
		}
		headers = {
			'Content-Type': 'application/json',
			'trakt-api-version': '2',
			'trakt-api-key': self.traktClientID()
		}
		try:
			response = requests.post(self.api_endpoint % "oauth/device/token",
									 json=data, headers=headers, timeout=15.0)
		except requests.exceptions.RequestException as e:
			log_utils.log('Trakt poll request error: %s' % str(e), __name__, log_utils.LOGDEBUG)
			return

		code = response.status_code

		if code == 200:
			try:
				token_data = response.json()
			except ValueError:
				log_utils.error('Trakt poll: 200 response was not valid JSON')
				return
			if token_data and token_data.get("access_token") and token_data.get("refresh_token"):
				self.token_data = token_data
			else:
				self.abort_auth('Trakt returned an incomplete token response')
			return

		if code == 400:  # authorization_pending (Trakt sends an empty body)
			try:
				error_code = (response.json() or {}).get('error', '')
			except Exception:
				error_code = ''
			if error_code == 'slow_down':
				self.increase_poll_interval(5)
			elif error_code in ('authorization_declined', 'access_denied'):
				self.abort_auth('Trakt authorization was declined')
			elif error_code == 'expired_token':
				self.abort_auth(self.msg_expired)
			return

		if code == 429:  # polling too fast
			self.increase_poll_interval(5)
		elif code == 418:
			self.abort_auth('Trakt authorization was declined')
		elif code == 410:
			self.abort_auth(self.msg_expired)
		elif code in (404, 409):
			self.abort_auth('Trakt device code is invalid or was already used')
		else:
			log_utils.log('Trakt poll unexpected HTTP %s: %s' % (code, response.text[:200]),
						  __name__, log_utils.LOGDEBUG)

	def save_account(self):
		token = self.token_data
		if not token or not token.get("access_token") or not token.get("refresh_token"):
			return False
		try:
			try:
				expires_in = max(int(token.get("expires_in", 86400)), 1)
			except Exception:
				expires_in = 86400
			expires_at = int(time.time()) + expires_in
			control.setSetting('trakt.expires', str(expires_at))
			control.setSetting('trakt.expires_in', str(expires_in))
			control.setSetting('trakt.token', token["access_token"])
			control.setSetting('trakt.refresh', token["refresh_token"])
			self.expires_at = str(expires_at)
			self.token = token["access_token"]
			control.sleep(1000)
			try:
				user = self.call("users/me", with_auth=True)
				control.setSetting('trakt.username', str(user['username']))
			except Exception as e:
				log_utils.error(f"Error fetching user info: {e}")
			return True
		except Exception as e:
			log_utils.error(f"Trakt save_account failed: {e}")
			return False

	def refresh_token(self):
		data = {
			"client_id": self.traktClientID(),
			"client_secret": self.traktClientSecret(),
			"redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
			"grant_type": "refresh_token",
			"refresh_token": control.setting('trakt.refresh')
		}

		response = self.call("oauth/token", data=data, with_auth=False, method='POST', return_str=True)

		if response is None:
			log_utils.log('Temporary Trakt Server Problems', level=log_utils.LOGWARNING)
			control.notification(title=32315, message=32685)
			return False

		code = str(response.status_code)

		try:
			response_text = response.text or ''
		except Exception:
			response_text = ''

		xbmc.log(f'AM Lite: Trakt refresh HTTP {code}', xbmc.LOGINFO)

		if not response_text.strip():
			log_utils.error('Trakt refresh returned empty response body')
			return False

		if code.startswith('5') or '<html' in response_text.lower():
			log_utils.log('Temporary Trakt Server Problems', level=log_utils.LOGWARNING)
			control.notification(title=32315, message=32685)
			return False

		if code == '423':
			log_utils.log('Locked User Account - Contact Trakt Support', level=log_utils.LOGWARNING)
			control.notification(title=32315, message=32686)
			return False

		if code == '429':
			log_utils.log('Trakt rate limit hit - refresh suppressed', level=log_utils.LOGWARNING)
			control.notification(title=32315, message='Trakt rate limit hit. Try again later.')
			return False

		try:
			response_json = response.json()
		except Exception as e:
			log_utils.error(f"Error parsing refresh token response: {e}")
			return False

		if code != '200':
			error = response_json.get('error', '') if isinstance(response_json, dict) else ''

			if error == 'invalid_grant':
				log_utils.log('Please Re-Authorize your Trakt Account', level=log_utils.LOGWARNING)
				control.notification(title=32315, message=32687)
			else:
				log_utils.error(f"Trakt refresh failed: HTTP {code} - {response_text}")

			return False

		if response_json.get('error') == 'invalid_grant':
			log_utils.log('Please Re-Authorize your Trakt Account', level=log_utils.LOGWARNING)
			control.notification(title=32315, message=32687)
			return False

		traktToken = response_json.get("access_token")
		traktRefresh = response_json.get("refresh_token")

		if not traktToken or not traktRefresh:
			log_utils.error(f"Trakt refresh failed: missing token data - {response_json}")
			return False

		try:
			expires_in = max(int(response_json.get("expires_in", 86400)), 1)
		except Exception:
			expires_in = 86400
		traktExpires = int(time.time()) + expires_in
		control.setSetting('trakt.token', traktToken)
		control.setSetting('trakt.refresh', traktRefresh)
		control.setSetting('trakt.expires', str(traktExpires))
		control.setSetting('trakt.expires_in', str(expires_in))
		self.token = traktToken
		self.expires_at = str(traktExpires or '')

		return True

	def auth(self):
		try:
			return self.authenticate()
		except Exception as e:
			log_utils.error(f"Trakt auth failed: {e}")
			return False

	def revoke(self):
		data = {"token": control.setting('trakt.token')}
		try:
			self.call("oauth/revoke", data=data, with_auth=False, method='POST')
		except Exception as e:
			log_utils.error(f"Trakt revoke failed: {e}")
			pass
		try:
			from acctmgr.modules.sync import tmdbh_provider
			tmdbh_provider.revoke()
		except Exception as exc:
			log_utils.error('TMDb Helper provider revoke failed: %s' % exc)
		control.setSetting('trakt.username', '')
		control.setSetting('trakt.expires', '')
		control.setSetting('trakt.expires_in', '')
		control.setSetting('trakt.token', '')
		control.setSetting('trakt.refresh', '')

	def account_info(self):
		response = self.call("users/me", with_auth=True)
		return response

	def extended_account_info(self):
		account_info = self.call("users/settings", with_auth=True)

		if not account_info or not isinstance(account_info, dict) or 'user' not in account_info or 'ids' not in account_info.get('user', {}):
			try:
				if self.refresh_token():
					account_info = self.call("users/settings", with_auth=True)
			except Exception as e:
				log_utils.error(f"Trakt account settings retry failed: {e}")

		if not account_info or not isinstance(account_info, dict):
			return None, None
		if 'user' not in account_info or 'ids' not in account_info.get('user', {}):
			return None, None

		slug = account_info['user']['ids'].get('slug')
		if not slug:
			return None, None

		stats = self.call("users/%s/stats" % slug, with_auth=True)

		if not stats or not isinstance(stats, dict):
			try:
				if self.refresh_token():
					stats = self.call("users/%s/stats" % slug, with_auth=True)
			except Exception as e:
				log_utils.error(f"Trakt stats retry failed: {e}")

		if not stats or not isinstance(stats, dict):
			return None, None

		return account_info, stats

	def account_info_to_dialog(self):
		from datetime import datetime, timedelta
		try:
			account_info, stats = self.extended_account_info()
			if not account_info or not stats:
				control.dialog.ok(control.lang(32315), 'Failed to retrieve Trakt account information.')
				return

			username = account_info['user']['username']
			timezone = account_info['account']['timezone']
			joined = control.jsondate_to_datetime(account_info['user']['joined_at'], "%Y-%m-%dT%H:%M:%S.%fZ")
			private = account_info['user']['private']
			vip = account_info['user']['vip']
			if vip:
				vip = '%s Years' % str(account_info['user']['vip_years'])

			total_given_ratings = stats['ratings']['total']

			movies_collected = stats['movies']['collected']
			movies_watched = stats['movies']['watched']
			movie_minutes = stats['movies']['minutes']

			if movie_minutes == 0:
				movies_watched_minutes = ['0 days', '0:00:00']
			elif movie_minutes < 1440:
				movies_watched_minutes = ['0 days', "{:0>8}".format(str(timedelta(minutes=movie_minutes)))]
			else:
				movies_watched_minutes = ("{:0>8}".format(str(timedelta(minutes=movie_minutes)))).split(', ')

			movies_watched_minutes = control.lang(40071) % (
				movies_watched_minutes[0],
				movies_watched_minutes[1].split(':')[0],
				movies_watched_minutes[1].split(':')[1]
			)

			shows_collected = stats['shows']['collected']
			shows_watched = stats['shows']['watched']

			episodes_watched = stats['episodes']['watched']
			episode_minutes = stats['episodes']['minutes']

			if episode_minutes == 0:
				episodes_watched_minutes = ['0 days', '0:00:00']
			elif episode_minutes < 1440:
				episodes_watched_minutes = ['0 days', "{:0>8}".format(str(timedelta(minutes=episode_minutes)))]
			else:
				episodes_watched_minutes = ("{:0>8}".format(str(timedelta(minutes=episode_minutes)))).split(', ')

			episodes_watched_minutes = control.lang(40071) % (
				episodes_watched_minutes[0],
				episodes_watched_minutes[1].split(':')[0],
				episodes_watched_minutes[1].split(':')[1]
			)

			heading = control.lang(32315)
			items = []
			items += [control.lang(40036) % username]
			items += [control.lang(40063) % timezone]
			items += [control.lang(40064) % joined]
			items += [control.lang(40065) % private]
			items += [control.lang(40066) % vip]
			items += [control.lang(40067) % str(total_given_ratings)]
			items += [control.lang(40068) % (movies_collected, movies_watched, movies_watched_minutes)]
			items += [control.lang(40069) % (shows_collected, shows_watched)]
			items += [control.lang(40070) % (episodes_watched, episodes_watched_minutes)]

			return control.selectDialog(items, heading)
		except Exception as e:
			log_utils.error(f"Trakt account dialog failed: {e}")
			return

	def traktClientID(self):
		traktId = 'ce7457fe1e42f09919b57171e9196109717474bad5b13b2a70959aef2f8e5624'
		return traktId

	def traktClientSecret(self):
		traktSecret = '004d641c35178c7d3c5798313919bec181e9a162bc84f16a2e78dc82a37150db'
		return traktSecret
