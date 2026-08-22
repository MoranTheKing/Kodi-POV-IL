# "Is this add-on installed?" -- asked without making Kodi log an error.
#
# WHY THIS FILE EXISTS. The obvious presence test is
#
#     try:
#         xbmcaddon.Addon(other_id)
#         return True
#     except Exception:
#         return False
#
# and it works. It also leaves a line in the Kodi log every time the answer is
# no, because Kodi writes
#
#     EXCEPTION: Unknown addon id 'plugin.video.umbrella'.
#
# at ERROR level BEFORE raising. Catching the exception does not unwrite the
# line. Five sites in this add-on asked that question at startup about add-ons
# a device may perfectly well not have -- Umbrella, CocoScrapers -- so a device
# without them collected a fistful of red lines on every boot for a question
# whose answer was "no, and that is fine".
#
# That is not cosmetic. Users open the wizard's "Viewing Errors in Log" screen,
# see red, and report a broken build. Two did, and the real defect in the same
# log was a sixth line that scrolled past unnoticed.
#
# THE DISK IS THE ANSWER. An add-on Kodi knows about has a directory with an
# addon.xml under special://home/addons. Reading that is silent, needs no
# add-on manager lookup, and cannot raise.
#
# WHAT THIS DELIBERATELY DOES NOT ANSWER: whether the add-on is ENABLED, or
# usable right now. A disabled add-on is still on disk. Callers that need the
# Addon object still construct it -- they just do it only after this says the
# files are there, which is what removes the noise for the ordinary
# not-installed case. For "is it usable this instant", see pov_reload
# ._is_resolvable, which exists because during a disable/enable cycle the
# answer changes twice in two seconds.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None


def addon_dir(addon_id):
    """The add-on's directory under special://home/addons, or '' if unknown."""
    if xbmcvfs is None or not addon_id:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/')
    except Exception:
        return ''
    return os.path.join(base, addon_id)


def installed(addon_id):
    """True when the add-on's files are on disk. Never raises, never logs."""
    d = addon_dir(addon_id)
    if not d:
        return False
    try:
        return os.path.isfile(os.path.join(d, 'addon.xml'))
    except Exception:
        return False


def addon(addon_id):
    """The Addon object, or None -- without an error line when it is absent.

    The construction is still guarded: `installed` says the files are there,
    which is not the same as Kodi being willing to hand out an Addon for them
    (mid-cycle, mid-install, a broken addon.xml). When that happens the error
    line is worth having, because then something really is wrong.
    """
    if not installed(addon_id):
        return None
    try:
        import xbmcaddon
        return xbmcaddon.Addon(addon_id)
    except Exception:
        return None
