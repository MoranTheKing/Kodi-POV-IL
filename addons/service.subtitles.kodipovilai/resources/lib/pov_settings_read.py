# Read a POV setting the way Account Manager WRITES it: from the file.
#
# THE BUG THIS EXISTS FOR. "I connected MDBList and it does not show up in My
# Movies / My Series." The MDBList row and the MDBList tiles are both gated on
# POV actually holding a key -- they route to POV's mdblist_watchlist action,
# which errors without one, so surfacing them unconnected would trade a missing
# entry for a broken one. Both gates asked Kodi:
#
#     xbmcaddon.Addon('plugin.video.pov').getSetting('mdblist.token')
#
# which answers from Kodi's IN-MEMORY copy of POV's settings.
#
# Account Manager does not write through Kodi. Its own table says so:
#
#     'path'        : .../plugin.video.pov
#     'settings'    : .../addon_data/plugin.video.pov/settings.xml
#     'default_mdb' : 'mdblist.token'
#
# It writes the FILE directly. So after AM connects MDBList -- which is how
# everyone connects it now -- the file holds the key and Kodi's in-memory copy
# still holds the empty string it loaded earlier. The gate reads empty, the row
# stays on its old version, and the tiles are never offered. Confirmed on a
# device: the key is present in settings.xml while the personal area is still
# missing MDBList.
#
# Reading the file is right for a second reason too: this build's own notes
# record that AM re-runs "restore default service / restore default API keys"
# over POV at every startup, so the in-memory copy and the file can disagree in
# either direction at any moment. The file is what AM and POV both persist to,
# so it is the one that answers "is this connected".

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None


POV_ADDON_ID = 'plugin.video.pov'


def _settings_path(addon_id=POV_ADDON_ID):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://profile/addon_data/' + addon_id + '/')
    except Exception:
        return ''
    path = os.path.join(base, 'settings.xml')
    return path if os.path.isfile(path) else ''


def get_setting(setting_id, addon_id=POV_ADDON_ID):
    """The stored value, '' when the file says there is none, or None when the
    file could not be read at all.

    THE THREE-WAY ANSWER IS THE POINT. An earlier version returned '' for all
    three, and mdblist_connected() then fell back to Kodi's in-memory copy on
    every one of them -- including the case where the file explicitly says the
    key is gone. A user who revokes MDBList without restarting Kodi would have
    kept the stale token in memory and been shown the row and the tiles
    pointing at an action that now errors: exactly the broken-entry outcome
    this module exists to prevent, in the opposite direction.

    Both settings.xml shapes are handled, in either attribute order. Kodi 18+
    writes

        <setting id="mdblist.token">abc</setting>

    and the older shape, which some writers still emit, is

        <setting id="mdblist.token" value="abc" />

    An add-on's file can carry both at once after a migration, so both are
    tried rather than assuming which one this install has.
    """
    path = _settings_path(addon_id)
    if not path:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            content = handle.read()
    except Exception:
        return None
    # Commented-out settings are not settings. A parser whose whole job is to
    # read this file correctly should not be fooled by <!-- ... -->.
    content = re.sub(r'<!--.*?-->', '', content, flags=re.S)
    quoted = re.escape(setting_id)
    match = re.search(
        r'<setting[^>]*\bid="%s"[^>]*>([^<]*)</setting>' % quoted, content)
    if match:
        return _unescape(match.group(1)).strip()
    # value="..." in either order: id first, or value first.
    for pattern in (r'<setting[^>]*\bid="%s"[^>]*\bvalue="([^"]*)"' % quoted,
                    r'<setting[^>]*\bvalue="([^"]*)"[^>]*\bid="%s"' % quoted):
        match = re.search(pattern, content)
        if match:
            return _unescape(match.group(1)).strip()
    return ''


def _unescape(text):
    # &amp; last, so an escaped entity survives one round trip.
    for entity, char in (('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'),
                         ('&apos;', "'"), ('&amp;', '&')):
        text = text.replace(entity, char)
    return text


def mdblist_connected():
    """True when POV holds an MDBList key, whoever wrote it.

    Kodi's in-memory copy is consulted ONLY when the file could not be read at
    all -- a fresh install with no addon_data yet, for instance. A file that
    says the key is empty is an answer, not a gap, and must not be overridden
    by a value Kodi loaded before the user revoked it."""
    value = get_setting('mdblist.token')
    if value is not None:
        return bool(value)
    try:
        import xbmcaddon
        token = xbmcaddon.Addon(POV_ADDON_ID).getSetting('mdblist.token') or ''
        return bool(token.strip())
    except Exception:
        return False
