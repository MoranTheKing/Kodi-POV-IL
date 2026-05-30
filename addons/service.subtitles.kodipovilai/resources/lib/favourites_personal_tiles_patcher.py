# Self-healing patcher for userdata/favourites.xml that RESTORES the
# 6 personal "הסרטים שלי / הסדרות שלי" home tiles (TMDB / Trakt / POV
# variants for movies + TV) when they're missing.
#
# Why this exists:
#
# The build ships userdata/favourites.xml with 32 tiles -- 11 service
# tiles (POV, Real Debrid, TorBox, Wizard, ...) PLUS 21 content
# tiles INCLUDING the 6 personal-list tiles users actually click on
# to see their saved movies/shows.
#
# But the per-skin seed at
#   media/builds_favourites_xml/skin.fentastic/favourites.xml
# only contains the 11 service tiles. The wizard's
# update_favourites_xml_file() OVERWRITES userdata/favourites.xml
# with this stripped seed every time the user switches skin. Result:
# user switches to AF3 (because the AF3 seed gets installed) then
# switches back to FENtastic (which copies the broken 11-tile seed
# over their working 32-tile favourites.xml) and loses every tile
# beyond the service set, INCLUDING the 6 personal tiles.
#
# This patcher detects the partial-state by scanning userdata/
# favourites.xml for the 6 canonical "הסרטים שלי / הסדרות שלי" tile
# name strings. If ANY of them is missing, it appends the missing
# entries from the bundled canonical fixture, preserving the user's
# existing tiles + any customisations they added.
#
# The existing favourites_xml_patcher (separate file) handles
# DIFFERENT logic: it migrates already-present Trakt-collection
# tiles to TMDB-favorites tiles and restores Trakt tiles for users
# with Trakt connected. It explicitly does NOT inject missing tiles
# from scratch -- that's what this patcher is for.
#
# Marker-gated, idempotent, atomic write. Quiet on no-op (all 6 tiles
# present). Logs INFO when restoring missing tiles.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


FAVOURITES_REL = 'favourites.xml'

# The 6 personal tiles, identified by the unique substring of their
# name attribute. If any is missing from the user's favourites.xml,
# we restore it from the bundled canonical fixture.
PERSONAL_TILE_NAMES = (
    '[B]הסדרות שלי (TMDB)[/B]',
    '[B]הסדרות שלי (Trakt)[/B]',
    '[B]הסדרות שלי (POV)[/B]',
    '[B]הסרטים שלי (TMDB)[/B]',
    '[B]הסרטים שלי (Trakt)[/B]',
    '[B]הסרטים שלי (POV)[/B]',
)

# Marker comment we write inside favourites.xml after a successful
# restore. Lets a future iteration of this patcher detect "we touched
# this once already; don't redo unnecessary work" without a separate
# marker file in addon_data.
MARKER = '<!-- AI_SUBS_FAVOURITES_PERSONAL_TILES_v1 -->'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log(
            'favourites_personal_tiles_patcher: ' + msg, level=level)
    except Exception:
        pass


def _favourites_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://userdata/' + FAVOURITES_REL)
    except Exception:
        return ''


def _fixture_path():
    """The canonical favourites.xml fixture lives bundled inside this
    addon -- so we never have to rely on the build's media/ seed file
    being correct or even present on disk."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(
        here, '..', 'fixtures', 'favourites_fentastic_canonical.xml')


def _missing_tiles(content_bytes):
    """Return the subset of PERSONAL_TILE_NAMES that are NOT present
    in the current favourites.xml. Substring check is sufficient
    because the name strings are uniquely identifying -- they only
    appear once in the file when present."""
    return tuple(
        name for name in PERSONAL_TILE_NAMES
        if name.encode('utf-8') not in content_bytes
    )


def _extract_tile(fixture_text, tile_name):
    """Extract a single <favourite ...>...</favourite> element from
    the fixture whose name attribute contains tile_name. Returns the
    full element as bytes (including leading whitespace + trailing
    newline) ready to splice into the user's file."""
    pattern = re.compile(
        r'([ \t]*<favourite\s[^>]*?name="' + re.escape(tile_name)
        + r'"[^>]*>(?:(?!</favourite>).)*?</favourite>\s*\n)',
        re.DOTALL,
    )
    m = pattern.search(fixture_text)
    if m is None:
        return None
    return m.group(1)


def ensure_patched():
    """Returns one of:
    'no_kodi' | 'no_favourites' | 'no_fixture' | 'fixture_unreadable'
    | 'already_complete' | 'unparseable_fixture' | 'read_failed'
    | 'write_failed' | 'restored'."""
    if xbmcvfs is None:
        return 'no_kodi'
    fav_path = _favourites_path()
    if not fav_path or not os.path.isfile(fav_path):
        # No favourites.xml at all. Could happen on a completely
        # empty userdata. Don't auto-create -- that's the wizard's
        # job. Just no-op.
        return 'no_favourites'
    fixture_path = _fixture_path()
    if not os.path.isfile(fixture_path):
        _log('bundled fixture missing at {0}'.format(fixture_path),
             level='WARNING')
        return 'no_fixture'

    try:
        with open(fav_path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(fav_path, e),
             level='WARNING')
        return 'read_failed'

    missing = _missing_tiles(content)
    if not missing:
        return 'already_complete'

    try:
        with open(fixture_path, 'r', encoding='utf-8') as f:
            fixture_text = f.read()
    except OSError as e:
        _log('fixture read failed: {0}'.format(e), level='WARNING')
        return 'fixture_unreadable'

    tiles_to_inject = []
    for name in missing:
        snippet = _extract_tile(fixture_text, name)
        if snippet is None:
            _log('fixture is missing the canonical entry for {0}; '
                 'cannot restore'.format(name), level='WARNING')
            return 'unparseable_fixture'
        tiles_to_inject.append(snippet.encode('utf-8'))

    # Insert the missing tiles just before the closing </favourites>
    # tag, preserving everything the user already has.
    closing_tag = b'</favourites>'
    close_idx = content.rfind(closing_tag)
    if close_idx == -1:
        _log('userdata/favourites.xml has no </favourites> closing tag '
             '-- file structure unrecognised, leaving alone',
             level='WARNING')
        return 'unparseable_fixture'

    marker_line = ('    ' + MARKER + '\n').encode('utf-8')
    new_content = (
        content[:close_idx]
        + marker_line
        + b''.join(tiles_to_inject)
        + content[close_idx:]
    )

    tmp_path = fav_path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(new_content)
        os.replace(tmp_path, fav_path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(fav_path, e),
             level='WARNING')
        return 'write_failed'

    _log('restored {0} missing personal tile(s): {1}'.format(
        len(missing), ', '.join(missing)), level='INFO')
    return 'restored'
