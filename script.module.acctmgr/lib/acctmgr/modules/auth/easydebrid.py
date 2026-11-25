# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcgui
import os
import json
import urllib.request
import urllib.error
from acctmgr.modules import control
from acctmgr.modules import log_utils

# Variables
easyd_icon = control.joinPath(control.artPath(), 'easydebrid.png')
API_BASE = "https://easydebrid.com/api/v1"
ACCOUNT_INFO = "/user/details"

class Easydebrid:
	def auth(self):
		# ask user for key
		api = xbmcgui.Dialog().input('Enter EasyDebrid API Key:')
		if not api:
			control.notification(message="EasyDebrid authorization cancelled!", icon=easyd_icon)
			return False

		api = api.strip()
		if not api:
			control.notification(message="EasyDebrid authorization failed!", icon=easyd_icon)
			return False

		# build API request to validate key
		url = "%s%s" % (API_BASE, ACCOUNT_INFO)
		req = urllib.request.Request(url)
		req.add_header("Authorization", "Bearer %s" % api)

		try:
			response = urllib.request.urlopen(req, timeout=10)
			data = json.loads(response.read().decode("utf-8"))

			if "id" not in data:
				raise Exception("Invalid response")

			# only save if validation succeeded
			control.setSetting('easydebrid.token', api)
			control.setSetting('easydebrid.acct_id', str(data.get("id", "")))
			return True

		except urllib.error.HTTPError as e:
			if e.code in (401, 403):
				control.notification(
					message="EasyDebrid authorization failed! Invalid API Key.",
					icon=easyd_icon
				)
			else:
				control.notification(
					message="EasyDebrid authorization failed! HTTP %s" % e.code,
					icon=easyd_icon
				)
			return False

		except Exception as e:
			log_utils.error(f"EasyDebrid authorization failed: {e}")
			control.notification(
				message="EasyDebrid authorization failed!",
				icon=easyd_icon
			)
			return False
