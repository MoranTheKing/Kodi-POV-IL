# -*- coding: utf-8 -*-
"""OAuth device flow orchestration for acctmgr providers."""
import glob
import os
import threading
import time

joinPath = os.path.join

from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.auth.dialogs import DeviceAuthWindow

QR_TEMP_DIR = 'special://temp/'
QR_DIR_PREFIX = 'acctmgr_auth_qr_'
QR_FILE_NAME = 'qr.png'

tk_icon = joinPath(control.iconsPath(), 'trakt.png')
mdb_icon = joinPath(control.iconsPath(), 'mdblist.png')
rd_icon = joinPath(control.iconsPath(), 'realdebrid.png')
pm_icon = joinPath(control.iconsPath(), 'premiumize.png')
ad_icon = joinPath(control.iconsPath(), 'alldebrid.png')
tb_icon = joinPath(control.iconsPath(), 'torbox.png')
oc_icon = joinPath(control.iconsPath(), 'offcloud.png')

PROVIDER_ICONS = {
	'trakt': tk_icon,
	'mdblist': mdb_icon,
	'real-debrid': rd_icon,
	'premiumize': pm_icon,
	'all-debrid': ad_icon,
	'torbox': tb_icon,
	'offcloud': oc_icon,
}


class RepeatTimer(threading.Timer):
    """Periodically execute function every interval seconds until cancelled."""

    def run(self):
        while not self.finished.wait(self.interval):
            try:
                self.function(*self.args, **self.kwargs)
            except Exception as e:
                log_utils.error('RepeatTimer: poll raised %s: %s' % (type(e).__name__, e))


class BaseDeviceAuth:
    provider_name = 'Provider'
    icon = None

    msg_success = 'Successfully Authorized!'
    msg_start_failed = 'Unable to start authorization. Please try again.'
    msg_expired = 'Authorization timed out'
    msg_save_failed = 'Authorization failed. Please try again.'

    token_data = None
    _timer = None
    _auth_error = None

    def get_device_code(self):
        """Request device code from provider. Returns code dict or None on failure."""
        raise NotImplementedError

    def poll_token(self, device_data):
        """Execute one token polling attempt."""
        raise NotImplementedError

    def save_account(self):
        """Persist authorization tokens. Returns True on success."""
        raise NotImplementedError

    def increase_poll_interval(self, seconds=5):
        timer = self._timer
        if timer is not None:
            timer.interval += seconds

    def abort_auth(self, message=None):
        """Abort authorization flow early."""
        self._auth_error = message or 'Authorization failed'

    def authenticate(self):
        self.token_data = None
        self._auth_error = None
        self._timer = None

        try:
            device_data = self.get_device_code()
            interval = max(int(device_data.get('interval') or 5), 1)
            expires_in = int(device_data.get('expires_in') or 600)
            user_code = str(device_data['user_code'])
            verification_url = str(device_data['verification_url'])
            device_data['device_code']
        except Exception as e:
            log_utils.error('%s: could not obtain a valid device code: %s' % (self.provider_name, e))
            self._notify(self.msg_start_failed)
            return False

        window = None
        timer = None
        qr_path = None
        outcome = 'error'

        try:
            self._cleanup_qr_files()
            qr_path = self.generate_qr(device_data.get('qr_data') or verification_url)

            window = DeviceAuthWindow(
                DeviceAuthWindow.XML_FILE, control.addonInfo('path'), 'Default', '1080i')
            window.set_auth_details(qr_path, user_code, verification_url,
                                    title='Authorize %s' % self.provider_name)
            window.show()

            timer = RepeatTimer(interval, self._poll, args=(device_data,))
            timer.daemon = True
            self._timer = timer
            timer.start()

            outcome = self._wait_for_authorization(window, expires_in)
        except Exception as e:
            log_utils.error('%s: authorization flow crashed: %s' % (self.provider_name, e))
            outcome = 'error'
        finally:
            if timer is not None:
                timer.cancel()
            if window is not None:
                try:
                    window.close()
                except Exception as e:
                    log_utils.error('%s: closing auth window failed: %s' % (self.provider_name, e))
                del window
            self._cleanup_qr_files(qr_path)

        if outcome == 'success':
            try:
                saved = bool(self.save_account())
            except Exception as e:
                log_utils.error('%s: save_account failed: %s' % (self.provider_name, e))
                saved = False
            if saved:
                self._notify(self.msg_success)
                return True
            self._notify(self.msg_save_failed)
            return False

        if outcome == 'expired':
            self._notify(self.msg_expired)
        elif outcome == 'aborted':
            self._notify(self._auth_error)
        elif outcome == 'error':
            self._notify(self.msg_start_failed)
        return False

    def _poll(self, device_data):
        """Poll token once and cancel timer if finished."""
        if self.token_data is None and self._auth_error is None:
            self.poll_token(device_data)
        if self.token_data is not None or self._auth_error is not None:
            timer = self._timer
            if timer is not None:
                timer.cancel()

    def _wait_for_authorization(self, window, expires_in):
        # Monotonic clock avoids wall-clock jumps from late NTP sync.
        deadline = time.monotonic() + expires_in
        monitor = control.monitor
        while True:
            if self.token_data is not None:
                return 'success'
            if self._auth_error is not None:
                return 'aborted'
            if window.is_canceled() or monitor.abortRequested():
                return 'canceled'
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 'expired'
            window.update_progress(int(100 * remaining / expires_in),
                                   self._format_remaining(remaining))
            # Sleep pumps Kodi window callbacks.
            control.sleep(250)

    @staticmethod
    def _format_remaining(seconds):
        minutes, secs = divmod(max(int(seconds), 0), 60)
        return 'Expires in %d:%02d' % (minutes, secs)

    def _notify(self, message):
        try:
            provider_key = str(self.provider_name or '').strip().lower()
            icon = self.icon or PROVIDER_ICONS.get(provider_key)
            control.notification(title=self.provider_name, message=message, icon=icon)
        except Exception as e:
            log_utils.error('%s: notification failed: %s' % (self.provider_name, e))

    def generate_qr(self, data):
        """Render data to a QR PNG in a unique directory and return its path, or None on failure."""
        try:
            import qrcode
            from qrcode.constants import ERROR_CORRECT_M
        except ImportError:
            log_utils.error('qrcode library not available - showing code/URL without QR')
            return None

        qr_root = control.translatePath(QR_TEMP_DIR)
        qr_dir = os.path.join(
            qr_root, '%s%d' % (QR_DIR_PREFIX, int(time.time() * 1000)))
        path = os.path.join(qr_dir, QR_FILE_NAME)
        try:
            if not os.path.exists(qr_dir):
                os.makedirs(qr_dir)
            qr = qrcode.QRCode(
                version=None,
                error_correction=ERROR_CORRECT_M,
                box_size=10,
                border=2)
            qr.add_data(data)
            qr.make(fit=True)
            try:
                img = qr.make_image(fill_color='black', back_color='white')
            except Exception:
                from qrcode.image.pure import PyPNGImage
                img = qr.make_image(image_factory=PyPNGImage)
            with open(path, 'wb') as f:
                img.save(f)
            return path
        except Exception as e:
            log_utils.error('QR generation failed: %s' % e)
            self._cleanup_qr_files(path)
            return None

    @staticmethod
    def _cleanup_qr_files(path=None):
        try:
            if path:
                qr_dir = os.path.dirname(path)
                try:
                    os.remove(path)
                except OSError:
                    pass
                try:
                    os.rmdir(qr_dir)
                except OSError:
                    pass
            else:
                pattern = os.path.join(
                    control.translatePath(QR_TEMP_DIR), QR_DIR_PREFIX + '*')
                for qr_dir in glob.glob(pattern):
                    if not os.path.isdir(qr_dir):
                        continue
                    for p in glob.glob(os.path.join(qr_dir, '*')):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                    try:
                        os.rmdir(qr_dir)
                    except OSError:
                        pass
        except Exception as e:
            log_utils.error('QR cleanup failed: %s' % e)
