"""Account Manager's sign-in QR code, drawn by the Wizard when Account Manager
cannot draw it itself.

Account Manager (script.module.acctmgr 1.2.x) draws the QR of its device
sign-in window (TorBox, Real-Debrid, Trakt ...) with the qrcode module, whose
images need PIL. Its fallback asks qrcode for PyPNGImage, which the qrcode
Kodi installs (6.1.0) does not have -- it has PymagingImage. So on a device
without PIL (Windows and Android Kodi ship it; some TVs and boxes do not) the
window shows no QR: only a code and a link cut short to fit, which a user
reported he could not read (28 Oct 2026). segno, which the Wizard already
carries for its log-upload QR, writes the PNG in pure Python.

make() writes where Account Manager writes its own QR, so Account Manager's
clean-up removes it too. It returns the PNG's path, or None (the window then
shows what it showed before).
"""
import os
import sys
import time

_WIZARD_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))


def make(data, root, prefix, name):
    try:
        if _WIZARD_ROOT not in sys.path:
            sys.path.append(_WIZARD_ROOT)
        import segno
        # 'w': never the folder of Account Manager's own failed attempt.
        folder = os.path.join(root, '%s%dw' % (prefix, int(time.time() * 1000)))
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, name)
        segno.make_qr(data, error='m').save(path, scale=10, border=2)
        return path
    except Exception:
        return None
