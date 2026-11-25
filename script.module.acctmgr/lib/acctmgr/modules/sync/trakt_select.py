# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcaddon, xbmcvfs
import os
import json
import xml.etree.ElementTree as ET
from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils

# Variables
joinPath = os.path.join
dialog = xbmcgui.Dialog()
trakt_icon = joinPath(control.iconsPath(), 'trakt.png')


def get_fenlight_name():
	try:
		addon_xml = xbmcvfs.translatePath('special://home/addons/plugin.video.fenlight/addon.xml')
		addon_name = ET.parse(addon_xml).getroot().get('name', '')
		return 'Fen Light+' if '+' in addon_name else 'Fen Light'
	except Exception:
		return 'Fen Light'

class TraktSelectDialog(xbmcgui.WindowXMLDialog):
	LIST_ID = 100
	DONE_ID = 101
	CANCEL_ID = 102

	def __init__(self, *args, **kwargs):
		self.menu = kwargs.pop('menu', [])
		self.locked = kwargs.pop('locked', [])
		self.selected = []
		self.confirmed = False
		self.warned_count = False

	def onInit(self):
		self._refresh_list()
		self.setFocusId(self.LIST_ID)

	def _refresh_list(self, position=None):
		list_control = self.getControl(self.LIST_ID)
		if position is None:
			position = list_control.getSelectedPosition()
		list_control.reset()

		for name in self.menu:
			display_name = get_fenlight_name() if name == 'Fen Light' else name
			item = xbmcgui.ListItem(label=display_name)
			item.setProperty('selected', 'true' if name in self.selected else 'false')
			list_control.addItem(item)

		if self.menu:
			position = max(0, min(position, len(self.menu) - 1))
			list_control.selectItem(position)

	def _toggle_selection(self):
		list_control = self.getControl(self.LIST_ID)
		position = list_control.getSelectedPosition()
		if position < 0 or position >= len(self.menu):
			return

		name = self.menu[position]
		if name in self.selected:
                        self.selected.remove(name)
                        if len(self.selected) <= 5:
                                self.warned_count = False
                        self._refresh_list(position)
                        return

		self.selected.append(name)

		if name == 'Seren':
                        if not control.yesnoDialog('Seren’s initial Trakt sync may trigger API rate limiting when multiple add-ons are syncing at the same time.[CR][CR]Continue with Seren selected?'):
                                self.selected.remove(name)
                                self._refresh_list(position)
                                return

		if len(self.selected) > 5 and not self.warned_count:
                        self.warned_count = True
                        if not control.yesnoDialog('Syncing more than 5 add-ons may trigger Trakt API rate limiting during the initial sync.[CR][CR]Continue with your selections?'):
                                self.selected.remove(name)
                                self.warned_count = False
                                self._refresh_list(position)
                                return

		self._refresh_list(position)

	def onClick(self, control_id):
		if control_id == self.LIST_ID:
			self._toggle_selection()
		elif control_id == self.DONE_ID:
			self.confirmed = True
			self.close()
		elif control_id == self.CANCEL_ID:
			self.close()

	def onAction(self, action):
		if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
			self.close()


class tk_list():
	def create_list(self):
		locked = [] # List of previously added items
		if xbmcvfs.exists(var.tk_sync_list):
			try:
				with open(var.tk_sync_list, 'r') as f:
					locked = json.load(f).get('addon_list', [])
			except Exception as e:
				log_utils.error(f"Failed to load Trakt sync list: {e}")
				locked = []

		menu = [] # List of supported add-ons
		def add_if(path, name):
			if xbmcvfs.exists(path) and name not in locked: # List only installed and not previously selected add-ons 
				menu.append(name)

		# Fen Light & Forks
		add_if(var.chk_fenlt,       'Fen Light')
		add_if(var.chk_gears,       'The Gears')
		add_if(var.chk_red,         'Red Light')
		
		# Uniques
		add_if(var.chk_umb,         'Umbrella')
		
		# Fen & Forks
		add_if(var.chk_pov,         'POV')
				
		# Dradis & Forks
		#add_if(var.chk_dradis,      'Dradis')
		add_if(var.chk_genocide,    'Genocide')
		
		# Uniques
		add_if(var.chk_seren,       'Seren')
		add_if(var.chk_luc,         'Luc_Kodi')
		add_if(var.chk_a4k,         'a4kStreaming')
		add_if(var.chk_madtitan,    'Mad Titan Sports')
		
		# Shadow & Forks
		add_if(var.chk_shadow,      'Shadow')
		add_if(var.chk_ghost,       'Ghost')
		add_if(var.chk_chains,      'The Chains')
		
		# Homelander & Forks
		add_if(var.chk_home,        'Homelander')
		add_if(var.chk_night,       'Nightwing')
		add_if(var.chk_absol,       'Absolution')
		# Others
		add_if(var.chk_crew,        'The Crew')
		add_if(var.chk_salts,       'SALTS')
		#Scrubs V2 & Forks
		add_if(var.chk_scrubs,      'Scrubs V2')
		add_if(var.chk_redg,        'Gratis Red')
		# Others
		add_if(var.chk_tmdbh,       'TMDb Helper')
		add_if(var.chk_trakt,       'Trakt Addon')

		if not menu:
			control.notification('AM Lite', 'No supported add-ons found!', icon=trakt_icon)
			return

		try:
			addon_path = xbmcvfs.translatePath(xbmcaddon.Addon('script.module.acctmgr').getAddonInfo('path'))
			select_dialog = TraktSelectDialog('acctmgr_trakt_select.xml', addon_path, 'Default', '1080i', menu=menu, locked=locked)
			select_dialog.doModal()
			confirmed = select_dialog.confirmed
			selected = select_dialog.selected[:]
			del select_dialog
		except Exception as e:
			log_utils.error(f"Error displaying selection dialog: {e}")
			return False

		if not confirmed or not selected:
			control.notification('AM Lite', 'No Changes Made!', icon=trakt_icon)
			control.openSettings()
			return False

		# Build final list
		addon_list = locked[:] # keep locked items
		addon_list.extend(selected)

		if not xbmcvfs.exists(var.acctmgr_datapath):
			xbmcvfs.mkdirs(var.acctmgr_datapath)

		try:
			if not control.setting('trakt.token'):
				if not control.yesnoDialog('Your list has been updated![CR]Would you like to authorize Trakt and sync with supported add-ons?'):
					control.notification('AM Lite', 'Changes discarded.', icon=trakt_icon)
					return False
			else:
				if not control.yesnoDialog('Your list has been updated![CR]Would you like to sync Trakt with supported add-ons?'):
					control.notification('AM Lite', 'Changes discarded.', icon=trakt_icon)
					return False
				
		except Exception as e:
			log_utils.error(f"Error displaying yes/no dialog: {e}")
			return False

		try:
			with open(var.tk_sync_list, 'w') as synclist: # Save list
				json.dump({'addon_list': addon_list}, synclist, indent=4)
		except Exception as e:
			log_utils.error(f"Failed to save Trakt sync list: {e}")
			return False

		control.notification('AM Lite', 'Trakt Sync List Saved!', icon=trakt_icon)
		return True
