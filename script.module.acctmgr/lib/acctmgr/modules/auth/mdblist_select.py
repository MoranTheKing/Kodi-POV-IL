# -*- coding: utf-8 -*-
import xbmc
import xbmcaddon
import xbmcgui


ADDON_ID = 'script.module.acctmgr'
API_KEY_XML = 'acctmgr_mdblist_select.xml'
SETUP_XML = 'acctmgr_mdblist_setup.xml'
LIST_ID = 100
CONTINUE_ID = 101
CANCEL_ID = 102
QR_COUNT_ID = 200
QR_LIST_ID = 201
API_COUNT_ID = 202
API_LIST_ID = 203


class MDBListSelectDialog(xbmcgui.WindowXMLDialog):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.result = -1

	def onInit(self):
		options = (
			'Enter on my phone (scan QR code)',
			'Enter manually (keyboard/remote)',
		)
		control = self.getControl(LIST_ID)
		control.reset()
		control.addItems([xbmcgui.ListItem(label=label) for label in options])
		self.setFocusId(LIST_ID)

	def onClick(self, control_id):
		if control_id == LIST_ID:
			position = self.getControl(LIST_ID).getSelectedPosition()
			if position in (0, 1):
				self.result = position
				self.close()
		elif control_id == CANCEL_ID:
			self.result = -1
			self.close()

	def onAction(self, action):
		if action.getId() in (
			xbmcgui.ACTION_PREVIOUS_MENU,
			xbmcgui.ACTION_NAV_BACK,
			xbmcgui.ACTION_PARENT_DIR,
		):
			self.result = -1
			self.close()


class MDBListSetupDialog(xbmcgui.WindowXMLDialog):
	def __init__(self, *args, **kwargs):
		self.oauth_targets = kwargs.pop('oauth_targets', [])
		self.key_targets = kwargs.pop('key_targets', [])
		super().__init__(*args, **kwargs)
		self.result = False

	def onInit(self):
		qr_names = '[CR]'.join(t['label'] for t in self.oauth_targets) or 'None'
		key_names = '[CR]'.join(t['label'] for t in self.key_targets) or 'None'
		qr_count = len(self.oauth_targets)
		key_count = len(self.key_targets)
		self.getControl(QR_COUNT_ID).setLabel('Detected {0} add-on(s) requiring QR Code authorization.'.format(qr_count))
		self.getControl(QR_LIST_ID).setLabel(qr_names)
		self.getControl(API_COUNT_ID).setLabel('Detected {0} add-on(s) requiring API Key authorization.'.format(key_count))
		self.getControl(API_LIST_ID).setLabel(key_names)
		self.setFocusId(CONTINUE_ID)

	def onClick(self, control_id):
		if control_id == CONTINUE_ID:
			self.result = True
			self.close()
		elif control_id == CANCEL_ID:
			self.result = False
			self.close()

	def onAction(self, action):
		if action.getId() in (
			xbmcgui.ACTION_PREVIOUS_MENU,
			xbmcgui.ACTION_NAV_BACK,
			xbmcgui.ACTION_PARENT_DIR,
		):
			self.result = False
			self.close()


def _run_dialog(dialog_class, xml_file, **kwargs):
	addon_path = xbmcaddon.Addon(ADDON_ID).getAddonInfo('path')
	dialog = dialog_class(xml_file, addon_path, 'Default', '1080i', **kwargs)
	try:
		dialog.doModal()
		return dialog.result
	finally:
		del dialog


def select_api_key_method():
	return _run_dialog(MDBListSelectDialog, API_KEY_XML)


def confirm_setup(oauth_targets, key_targets):
	return _run_dialog(
		MDBListSetupDialog,
		SETUP_XML,
		oauth_targets=oauth_targets,
		key_targets=key_targets,
	)
