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


def _is_complete_document(content):
    """True only for a settings file that was fully written.

    A HALF-WRITTEN FILE MUST NOT ANSWER. Account Manager rewrites this file
    whole. Read it in the middle of that and you get a valid-looking prefix
    with the key not in it yet -- and the three-way return above would then
    treat "the file says there is no key" as a definitive answer and hide the
    MDBList row from a user who is, in fact, connected. That is the same
    failure this module exists to prevent, arriving from the other side.

    The test is the closing tag, which is written last: without it the file is
    a fragment, we cannot answer from it, and the caller falls back to Kodi's
    in-memory copy. A deliberately empty <settings/> is a complete document and
    is accepted -- that one really does mean "no key".

    AT THE END, not merely somewhere. Asking `'</settings>' in content` passed
    a file whose only closing tag was inside a comment, or inside an attribute
    value, while the live document was still half-written -- and the reader
    then answered from it with confidence. The closing tag has to be the last
    thing in the file, which is precisely what "the writer finished" means.
    """
    tail = _trim_tail(content)
    if tail.endswith('</settings>'):
        return True
    return re.search(r'<settings\b[^>]*/>$', tail) is not None


def _trim_tail(content):
    """Everything after the document's last real element, removed.

    Two things live past the closing tag on a file that is nevertheless
    complete. NUL padding, because a block-based filesystem -- Android flash,
    where most of these devices are -- can zero-fill the tail of the last
    block, and rstrip() does not treat NUL as whitespace. And a trailing
    comment or processing instruction, which the XML spec explicitly allows
    after the root element. Rejecting either would send a perfectly readable
    file down the "I cannot tell" path and cost this module its point."""
    tail = content.rstrip('\x00 \t\r\n')
    while True:
        stripped = re.sub(r'(?:<!--.*?-->|<\?.*?\?>)$', '', tail, flags=re.S)
        stripped = stripped.rstrip('\x00 \t\r\n')
        if stripped == tail:
            return tail
        tail = stripped


def _strip_comments(content):
    """Comments removed, or None when the file cannot be trusted.

    WHY NOT A REGEX. `re.sub(r'<!--.*?-->', ...)` rescans to end-of-string for
    every `<!--` that has no closer ahead of it, so a file carrying many of
    them costs O(n^2) -- measured at six seconds on 80KB, inside a call that
    runs while a menu is being drawn. find() walks the string once.

    An unterminated comment means the file is malformed, and the honest answer
    to "is MDBList connected" is then "I cannot tell": returning None sends the
    caller to Kodi's in-memory copy instead of to a half-parsed guess.

    A comment ends at its FIRST `-->`, so text after that is live content even
    if the author meant it to stay commented out. That is what the XML spec
    says and what Kodi's own parser does -- matching it is the point, because a
    reader that disagreed with Kodi about what the file contains would be worse
    than one that is occasionally surprising.
    """
    if '<!--' not in content:
        return content
    out = []
    idx = 0
    while True:
        start = content.find('<!--', idx)
        if start < 0:
            out.append(content[idx:])
            return ''.join(out)
        end = content.find('-->', start + 4)
        if end < 0:
            return None
        out.append(content[idx:start])
        idx = end + 3


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
    if not _is_complete_document(content):
        return None
    # Commented-out settings are not settings. A parser whose whole job is to
    # read this file correctly should not be fooled by <!-- ... -->.
    content = _strip_comments(content)
    if content is None:
        return None
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
