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
# addon.xml under one of the add-on roots. Reading that is silent, needs no
# add-on manager lookup, and cannot raise.
#
# WHAT THIS DELIBERATELY DOES NOT ANSWER: whether the add-on is ENABLED, or
# usable right now. A disabled add-on is still on disk, so a device with
# Umbrella installed and switched off still gets the error line from a caller
# that goes on to construct the Addon. For "is it usable this instant", see
# pov_reload._is_resolvable, which exists because during a disable/enable
# cycle the answer changes twice in two seconds.
#
# BOTH ROOTS, NOT ONE. This checked only special://home/addons, with a note
# saying that anything asking about an add-on that could live in the Kodi
# package "has to widen this rather than assume it already covers them". Two
# callers then did exactly that -- the MDBList and Trakt mirrors ask about POV
# -- and pov_reload._is_installed has walked BOTH roots for that same id since
# it was written. Left narrow, a device with POV under special://xbmc/addons
# would answer "not installed" and both mirrors would return 'no_pov' on every
# pass, forever, without a single log line: the caller says nothing for that
# answer. A silent, permanent feature loss in a helper added to remove log
# noise.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None


# In lookup order. special://home is where a user or a build installs; the
# second is where the Kodi package's own bundled add-ons live.
ADDON_ROOTS = ('special://home/addons/', 'special://xbmc/addons/')


def addon_dir(addon_id):
    """The directory the add-on's files are in, or '' if it is not there.

    Returns the FIRST root that actually has an addon.xml, so callers get a
    path they can read rather than a path that may not exist. '' means "not
    found in any root", which is also what an unreadable filesystem gives --
    both answers mean the same thing to every caller here.
    """
    if xbmcvfs is None or not addon_id:
        return ''
    # AN ID IS A NAME, NOT A PATH. os.path.join throws the base away the
    # moment the second argument is absolute, so `addon_dir('/etc/whatever')`
    # would resolve OUTSIDE both roots and answer "installed" for anything
    # with an addon.xml there. Every caller in this build passes a hardcoded
    # literal, so this is not reachable today -- which is exactly the moment
    # to close it, rather than after somebody wires a setting to it.
    if (os.path.isabs(addon_id) or '/' in addon_id or '\\' in addon_id
            or addon_id in ('.', '..')):
        return ''
    for root in ADDON_ROOTS:
        try:
            base = xbmcvfs.translatePath(root)
            candidate = os.path.join(base, addon_id)
            if os.path.isfile(os.path.join(candidate, 'addon.xml')):
                return candidate
        except Exception:
            continue
    return ''


def installed(addon_id):
    """True when the add-on's files are on disk. Never raises, never logs."""
    return bool(addon_dir(addon_id))


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
