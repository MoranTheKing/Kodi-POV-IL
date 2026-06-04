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
    '[B][COLOR orange]הגדרת התראות מנוי[/COLOR][/B]',
    '[B]הסדרות שלי (TMDB)[/B]',
    '[B]הסדרות שלי (Trakt)[/B]',
    '[B]הסדרות שלי (POV)[/B]',
    '[B]הסרטים שלי (TMDB)[/B]',
    '[B]הסרטים שלי (Trakt)[/B]',
    '[B]הסרטים שלי (POV)[/B]',
)

BUILD_SERVICE_TILE_NAMES = (
    '[B]סטטוס מנוי Premiumize[/B]',
)
PREMIUMIZE_ACTION = 'premiumize.show_account_info'
TORBOX_ACTION = 'torbox.show_account_info'
TORBOX_STATUS_ACTION = (
    'RunScript(service.subtitles.kodipovilai,action=torbox_status)')

# Marker comments written into favourites.xml. RESTORE_MARKER keeps
# compatibility with earlier restores. SEEN_MARKER means "the build
# already had these tiles at least once"; if the user deletes them after
# that, we respect the deletion and do not bring them back on every boot.
MARKER = '<!-- AI_SUBS_FAVOURITES_PERSONAL_TILES_v1 -->'
SEEN_MARKER = '<!-- AI_SUBS_FAVOURITES_PERSONAL_TILES_SEEN_v2 -->'
RESTORE_MARKERS = (MARKER, SEEN_MARKER)
SERVICE_SEEN_MARKER = '<!-- AI_SUBS_FAVOURITES_BUILD_SERVICE_TILES_SEEN_v1 -->'
FULL_BUILD_SEEN_MARKER = '<!-- AI_SUBS_FAVOURITES_FULL_BUILD_TILES_SEEN_v1 -->'
BROKEN_DEBRID_NOTICE_ACTION = (
    'RunPlugin("plugin://service.subtitles.kodipovilai/?'
    'action=open_pov_settings")')
OLD_DEBRID_NOTICE_ACTION = 'Addon.OpenSettings(plugin.video.pov)'
FIXED_DEBRID_NOTICE_ACTION = (
    'RunScript(service.subtitles.kodipovilai,'
    'action=debrid_notice_settings)')
OLD_TORBOX_STATUS_ACTIONS = (
    'PlayMedia("plugin://plugin.video.pov/?mode=torbox.show_account_info'
    '&amp;name=Account+Info&amp;isFolder=false&amp;iconImage='
    'special%3A%2F%2Fhome%2Faddons%2Fplugin.video.pov%2Fresources%2Fskins'
    '%2FDefault%2Fmedia%2Ftorbox.png")',
    'plugin://plugin.video.pov/?mode=torbox.show_account_info',
)


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


def _missing_tiles(content_bytes, tile_names=PERSONAL_TILE_NAMES):
    """Return the subset of tile_names that are NOT present
    in the current favourites.xml. Substring check is sufficient
    because the name strings are uniquely identifying -- they only
    appear once in the file when present."""
    return tuple(
        name for name in tile_names
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


def _service_tile_pattern(action):
    return re.compile(
        rb'([ \t]*<favourite\b(?:(?!</favourite>).)*?'
        + re.escape(action.encode('utf-8'))
        + rb'(?:(?!</favourite>).)*?</favourite>\s*\n)',
        re.DOTALL,
    )


def _move_existing_service_tile_after_torbox(content):
    premiumize_pattern = _service_tile_pattern(PREMIUMIZE_ACTION)
    matches = list(premiumize_pattern.finditer(content))
    if not matches:
        return content, False
    torbox_pattern = _service_tile_pattern(TORBOX_STATUS_ACTION)
    torbox_match = torbox_pattern.search(content)
    if torbox_match is None:
        torbox_pattern = _service_tile_pattern(TORBOX_ACTION)
        torbox_match = torbox_pattern.search(content)
    if torbox_match is None:
        return content, False

    premiumize_tile = matches[0].group(1)
    without_premiumize = premiumize_pattern.sub(b'', content)
    torbox_match = torbox_pattern.search(without_premiumize)
    if torbox_match is None:
        return content, False
    moved = (
        without_premiumize[:torbox_match.end(1)]
        + premiumize_tile
        + without_premiumize[torbox_match.end(1):]
    )
    return moved, moved != content


def _insert_service_tile_after_torbox(content, tile_bytes):
    torbox_match = _service_tile_pattern(TORBOX_STATUS_ACTION).search(content)
    if torbox_match is None:
        torbox_match = _service_tile_pattern(TORBOX_ACTION).search(content)
    if torbox_match is None:
        return None
    return (
        content[:torbox_match.end(1)]
        + tile_bytes
        + content[torbox_match.end(1):]
    )


def _fix_existing_debrid_notice_action(content):
    """Fix v0.2.106 installs where the tile existed but used a
    plugin:// URL against our subtitle/service addon, which Kodi does
    not execute as a normal plugin from favourites."""
    fixed = content
    for old in (BROKEN_DEBRID_NOTICE_ACTION, OLD_DEBRID_NOTICE_ACTION):
        fixed = fixed.replace(
            old.encode('utf-8'),
            FIXED_DEBRID_NOTICE_ACTION.encode('utf-8'))
    return fixed, fixed != content


def _fix_existing_torbox_status_action(content):
    fixed = content
    fixed = fixed.replace(
        OLD_TORBOX_STATUS_ACTIONS[0].encode('utf-8'),
        TORBOX_STATUS_ACTION.encode('utf-8'))
    pattern = re.compile(
        rb'(<favourite\b(?:(?!</favourite>).)*?'
        rb'name="\[B\](?:[^"]*TorBox[^"]*)\[/B\]"'
        rb'(?:(?!</favourite>).)*?>)'
        rb'(?:(?!</favourite>).)*?'
        rb'(</favourite>)',
        re.DOTALL,
    )
    fixed = pattern.sub(
        rb'\1' + TORBOX_STATUS_ACTION.encode('utf-8') + rb'\2',
        fixed,
        count=1,
    )
    return fixed, fixed != content


def _has_restore_marker(content):
    return any(marker.encode('utf-8') in content
               for marker in RESTORE_MARKERS)


def _has_marker(content, marker):
    return marker.encode('utf-8') in content


def _insert_marker(content, marker=SEEN_MARKER):
    if _has_marker(content, marker):
        return content, False
    closing_tag = b'</favourites>'
    close_idx = content.rfind(closing_tag)
    if close_idx == -1:
        return content, False
    marker_line = ('    ' + marker + '\n').encode('utf-8')
    return (
        content[:close_idx] + marker_line + content[close_idx:],
        True)


def _extract_fixture_tiles(fixture_text):
    return re.findall(
        r'([ \t]*<favourite\s[^>]*?name="[^"]+"[^>]*>'
        r'(?:(?!</favourite>).)*?</favourite>\s*\n)',
        fixture_text,
        flags=re.DOTALL,
    )


def _tile_identity(tile_text):
    name_match = re.search(r'name="([^"]+)"', tile_text)
    name = name_match.group(1) if name_match else ''
    action_match = re.search(
        r'<favourite\b[^>]*>(?P<action>(?:(?!</favourite>).)*)'
        r'</favourite>',
        tile_text,
        flags=re.DOTALL,
    )
    action = (action_match.group('action') if action_match else '').strip()
    return name, action


def _canonical_tiles_missing_from_content(content, fixture_text):
    """Return canonical build tiles missing from userdata/favourites.xml.

    Older wizard/favourites seeds can overwrite the user's FENtastic
    favourites with a partial set: personal tiles survive, but genre and
    popular rows disappear. This repairs the whole canonical build surface
    once without replacing the user's file or deleting custom favourites.
    """
    missing = []
    for tile_text in _extract_fixture_tiles(fixture_text):
        name, _action = _tile_identity(tile_text)
        if not name:
            continue
        name_b = name.encode('utf-8')
        if name_b in content:
            continue
        missing.append(tile_text.encode('utf-8'))
    return missing


def _insert_tiles_before_close(content, tiles):
    if not tiles:
        return content
    closing_tag = b'</favourites>'
    close_idx = content.rfind(closing_tag)
    if close_idx == -1:
        return None
    return content[:close_idx] + b''.join(tiles) + content[close_idx:]


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

    try:
        with open(fixture_path, 'r', encoding='utf-8') as f:
            fixture_text = f.read()
    except OSError as e:
        _log('fixture read failed: {0}'.format(e), level='WARNING')
        return 'fixture_unreadable'

    had_restore_marker = _has_restore_marker(content)
    had_service_marker = _has_marker(content, SERVICE_SEEN_MARKER)
    had_full_marker = _has_marker(content, FULL_BUILD_SEEN_MARKER)
    content, fixed_existing = _fix_existing_debrid_notice_action(content)
    content, fixed_torbox_status = _fix_existing_torbox_status_action(content)
    content, service_position_fixed = (
        _move_existing_service_tile_after_torbox(content))

    # Wizard installs on clean Kodi can seed a partial favourites.xml:
    # the top personal tiles exist, but genre/popular/network rows are
    # missing. Restore the whole canonical build surface once, without
    # replacing the file or deleting user custom favourites.
    missing_full_tiles = []
    if not had_full_marker:
        missing_full_tiles = _canonical_tiles_missing_from_content(
            content, fixture_text)
        if missing_full_tiles:
            positioned_tiles = []
            append_tiles = []
            for tile in missing_full_tiles:
                if PREMIUMIZE_ACTION.encode('utf-8') in tile:
                    positioned = _insert_service_tile_after_torbox(
                        content, tile)
                    if positioned is not None:
                        content = positioned
                    else:
                        append_tiles.append(tile)
                else:
                    append_tiles.append(tile)
            if append_tiles:
                inserted = _insert_tiles_before_close(content, append_tiles)
                if inserted is None:
                    _log('userdata/favourites.xml has no </favourites> '
                         'closing tag -- file structure unrecognised, '
                         'leaving alone', level='WARNING')
                    return 'unparseable_fixture'
                content = inserted
            content, service_position_fixed_2 = (
                _move_existing_service_tile_after_torbox(content))
            service_position_fixed = (
                service_position_fixed or service_position_fixed_2)

    missing_personal = _missing_tiles(content)
    missing_service = _missing_tiles(content, BUILD_SERVICE_TILE_NAMES)
    if missing_personal and had_restore_marker:
        if (not fixed_existing and not fixed_torbox_status
                and not service_position_fixed
                and (not missing_service or had_service_marker)):
            return 'user_removed_tiles'
        # A user may delete the tiles after receiving the broken-action
        # version. Keep the deletion respected, but still persist the
        # action fix if that old action exists elsewhere in favourites.
        missing_personal = ()
    if missing_service and had_service_marker:
        missing_service = ()
    missing = missing_personal + missing_service

    new_content = content
    marker_added = False
    service_marker_added = False
    full_marker_added = False
    if not missing:
        new_content, marker_added = _insert_marker(new_content)
        new_content, service_marker_added = _insert_marker(
            new_content, SERVICE_SEEN_MARKER)
        new_content, full_marker_added = _insert_marker(
            new_content, FULL_BUILD_SEEN_MARKER)
    elif not missing_service:
        new_content, service_marker_added = _insert_marker(
            new_content, SERVICE_SEEN_MARKER)
    elif not missing_personal:
        new_content, marker_added = _insert_marker(new_content)

    if (not missing and not fixed_existing and not marker_added
            and not fixed_torbox_status and not service_marker_added
            and not service_position_fixed and not full_marker_added
            and not missing_full_tiles):
        return 'already_complete'

    if missing:
        personal_tiles_to_inject = []
        service_tiles_to_inject = []
        for name in missing:
            snippet = _extract_tile(fixture_text, name)
            if snippet is None:
                _log('fixture is missing the canonical entry for {0}; '
                     'cannot restore'.format(name), level='WARNING')
                return 'unparseable_fixture'
            if name in BUILD_SERVICE_TILE_NAMES:
                service_tiles_to_inject.append(snippet.encode('utf-8'))
            else:
                personal_tiles_to_inject.append(snippet.encode('utf-8'))

        # Insert the missing tiles just before the closing </favourites>
        # tag, preserving everything the user already has.
        closing_tag = b'</favourites>'
        close_idx = new_content.rfind(closing_tag)
        if close_idx == -1:
            _log('userdata/favourites.xml has no </favourites> closing tag '
                 '-- file structure unrecognised, leaving alone',
                 level='WARNING')
            return 'unparseable_fixture'

        marker_lines = []
        if missing_personal and not _has_restore_marker(new_content):
            marker_lines.append(SEEN_MARKER)
        if missing_service and not _has_marker(new_content, SERVICE_SEEN_MARKER):
            marker_lines.append(SERVICE_SEEN_MARKER)
        marker_bytes = ''.join(
            '    ' + marker + '\n' for marker in marker_lines
        ).encode('utf-8')
        new_content = (
            new_content[:close_idx]
            + marker_bytes
            + b''.join(personal_tiles_to_inject)
            + new_content[close_idx:]
        )
        for tile in service_tiles_to_inject:
            positioned = _insert_service_tile_after_torbox(new_content, tile)
            if positioned is None:
                close_idx = new_content.rfind(closing_tag)
                if close_idx == -1:
                    return 'unparseable_fixture'
                positioned = (
                    new_content[:close_idx] + tile + new_content[close_idx:])
            new_content = positioned

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

    if missing:
        _log('restored {0} missing personal tile(s): {1}'.format(
            len(missing), ', '.join(missing)), level='INFO')
    if fixed_existing:
        _log('fixed debrid notification settings tile action', level='INFO')
    if fixed_torbox_status:
        _log('fixed TorBox status tile action', level='INFO')
    if marker_added:
        _log('marked favourites personal tiles as seen', level='INFO')
    if service_marker_added:
        _log('marked favourites build service tiles as seen', level='INFO')
    if full_marker_added:
        _log('marked full build favourites tiles as seen', level='INFO')
    if service_position_fixed:
        _log('moved Premiumize status tile next to TorBox', level='INFO')
    if missing_full_tiles:
        _log('restored {0} missing canonical build tile(s)'.format(
            len(missing_full_tiles)), level='INFO')
    if missing and fixed_existing:
        return 'restored_and_fixed'
    if missing_full_tiles:
        return 'restored_full'
    if missing:
        return 'restored'
    if marker_added and fixed_existing:
        return 'marked_and_fixed'
    if marker_added:
        return 'marked'
    return 'fixed'
