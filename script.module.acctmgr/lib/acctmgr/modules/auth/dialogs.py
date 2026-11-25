# -*- coding: utf-8 -*-
"""XML-backed dialog for device authorization."""
import xbmcgui

# Control IDs - must match resources/skins/Default/1080i/acctmgr_device_auth.xml
CTRL_TITLE = 100
CTRL_QR = 101
CTRL_URL = 102
CTRL_CODE = 103
CTRL_PROGRESS = 104
CTRL_TIME = 105
CTRL_LOGO = 106
CTRL_QR_GROUP = 110
CTRL_CANCEL = 200

_CLOSE_ACTIONS = (
    xbmcgui.ACTION_PREVIOUS_MENU,
    xbmcgui.ACTION_NAV_BACK,
)


class DeviceAuthWindow(xbmcgui.WindowXMLDialog):
    XML_FILE = 'acctmgr_device_auth.xml'

    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self)
        self._canceled = False
        self._ready = False
        self._title = ''
        self._qr_path = None
        self._user_code = ''
        self._verification_url = ''
        self._percent = 100
        self._time_text = ''

    def set_auth_details(self, qr_url, user_code, verification_url, title=''):
        """Set auth details and apply to controls if dialog is ready."""
        self._qr_path = qr_url
        self._user_code = user_code
        self._verification_url = verification_url
        self._title = title
        if self._ready:
            self._apply_details()

    def update_progress(self, percent, remaining_time_str):
        self._percent = percent
        self._time_text = remaining_time_str
        if self._ready:
            self._apply_progress()

    def is_canceled(self):
        return self._canceled

    def onInit(self):
        self._ready = True
        self._apply_details()
        self._apply_progress()

    def onAction(self, action):
        if action.getId() in _CLOSE_ACTIONS:
            self._canceled = True
            self.close()
            return
        xbmcgui.WindowXMLDialog.onAction(self, action)

    def onClick(self, controlId):
        if controlId == CTRL_CANCEL:
            self._canceled = True
            self.close()

    def _apply_details(self):
        self._safe(CTRL_TITLE, lambda c: c.setLabel(self._title))
        self._safe(CTRL_URL, lambda c: c.setLabel(self._verification_url))
        self._safe(CTRL_CODE, lambda c: c.setLabel(self._user_code))
        if self._qr_path:
            self._safe(CTRL_QR, lambda c: c.setImage(self._qr_path, False))
        else:
            self._safe(CTRL_QR_GROUP, lambda c: c.setVisible(False))
            
    def _apply_progress(self):
        self._safe(CTRL_PROGRESS, lambda c: c.setPercent(float(self._percent)))
        self._safe(CTRL_TIME, lambda c: c.setLabel(self._time_text))

    def _safe(self, control_id, fn):
        """Safely invoke control callback, ignoring skin control mismatches."""
        try:
            fn(self.getControl(control_id))
        except Exception:
            pass
