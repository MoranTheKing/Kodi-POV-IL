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
import json

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    import xbmc
except Exception:
    xbmc = None

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

# MDBList personal tiles ("My Movies / My Series (MDBList)"). Unlike the 6 core
# personal tiles, these are OPT-IN: they only make sense once MDBList is connected
# in POV, so we insert them exactly once and ONLY for installs that have an MDBList
# key set. Add-only + fire-once (json sidecar), so a later user deletion sticks.
# New/clean installs get them from the shipped canonical favourites.xml. The tiles
# route to POV's mdblist_watchlist, which pov_mdblist_patcher patches to MERGE the
# Collection ("Recently Added") in -- so one pair of tiles shows everything.
MDBLIST_WATCHLIST_TILE_NAMES = (
    '[B]הסדרות שלי (MDBList)[/B]',
    '[B]הסרטים שלי (MDBList)[/B]',
)
MDBLIST_TILES_SEEN_MARKER = '<!-- AI_SUBS_FAVOURITES_MDBLIST_TILES_SEEN_v1 -->'
# ONE forced restore of the MDBList pair, for everyone still connected.
#
# The add-only + fire-once rule above is right in the steady state, but it has
# no way to tell "the user deleted these" from "something else wiped them" --
# a skin switch, a favourites reseed, a home-widget edit that rewrites the file.
# Installs that lost the tiles that way were then refused forever, because the
# sidecar already said 'mdblist_tiles'. Field reports of exactly that are what
# this is for: put them back once, for anyone who still has MDBList connected,
# then hand control back to the normal rule -- so a deletion made AFTER this
# fires is respected permanently, like any other.
# v2 spends one more, for the devices that lost the tiles across a
# revoke-and-reconnect of MDBList: the file was rewritten while MDBList was
# disconnected, so the tiles went, and the sidecar then refused to bring them
# back because it said we had already put them there once. Same mechanism as
# v1, same class of loss, one more time.
#
# A re-arm fired from the connect action was tried instead and removed: POV's
# connect row fires whatever the outcome, so a declined confirmation counted
# as a connect, and there is no reliable "a human just connected" signal to be
# had there. A one-shot needs no signal.
MDBLIST_RESEED_MARKER = '<!-- AI_SUBS_FAVOURITES_MDBLIST_RESEED_v2 -->'
MDBLIST_RESEED_KEY = 'mdblist_reseed_v2'
# The POV movies personal tile: we splice the MDBList tiles right after it so they
# land next to the existing "My Movies/My Series" group rather than at the bottom.
_POV_MOVIES_TILE_NAME = '[B]הסרטים שלי (POV)[/B]'
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
# One-time re-seed of the Premiumize status tile. Some installs lost it to a
# wizard/POV cache reseed + restart (NOT a user deletion), and the SEEN-marker
# logic then refused to bring it back. This marker forces a single restore for
# everyone; once written, genuine future deletions are respected again.
SERVICE_RESEED_MARKER = '<!-- AI_SUBS_FAVOURITES_PREMIUMIZE_RESEED_v1 -->'
# One-time re-seed of the personal tiles (subscription-reminder settings +
# "My Movies/My Series" TMDB/Trakt/POV). Same idea as the Premiumize re-seed:
# some installs lost them to a favourites reseed (not a user deletion) and the
# respect-deletion logic then refused to bring them back. Fires once, then
# genuine future deletions are respected again.
PERSONAL_RESEED_MARKER = '<!-- AI_SUBS_FAVOURITES_PERSONAL_RESEED_v1 -->'
FULL_BUILD_SEEN_MARKER = '<!-- AI_SUBS_FAVOURITES_FULL_BUILD_TILES_SEEN_v2 -->'
# One-time re-seed of the WHOLE canonical build surface (genre / popular /
# per-service network rows -- e.g. the "Netflix/Disney+/HBO... סדרות" home
# tiles). These live in Kodi favourites, not in navigator.db or the skin; some
# installs lost the service rows to a favourites reseed (not a user deletion),
# and _should_restore_full_build_tiles() deliberately refuses to rebuild on
# every update. This marker forces exactly one insert-only restore of every
# canonical tile the user is missing, then never repeats -- so genuine future
# deletions stay respected. User-added custom favourites are never touched.
FULL_BUILD_RESEED_MARKER = '<!-- AI_SUBS_FAVOURITES_FULL_BUILD_RESEED_v1 -->'
DEBRID_NOTICE_SEEN_MARKER = '<!-- AI_SUBS_FAVOURITES_DEBRID_NOTICE_SEEN_v1 -->'
BROKEN_DEBRID_NOTICE_ACTION = (
    'RunPlugin("plugin://service.subtitles.kodipovilai/?'
    'action=open_pov_settings")')
OLD_DEBRID_NOTICE_ACTION = 'Addon.OpenSettings(plugin.video.pov)'
FIXED_DEBRID_NOTICE_ACTION = (
    'RunScript(service.subtitles.kodipovilai,'
    'action=debrid_notice_settings)')
CONNECT_SERVICES_ICON = 'Connect_Services.png'
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


def _extract_tile_by_action(fixture_text, action):
    pattern = re.compile(
        r'([ \t]*<favourite\s[^>]*?>(?:(?!</favourite>).)*?'
        + re.escape(action)
        + r'(?:(?!</favourite>).)*?</favourite>\s*\n)',
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


_SEEN_STATE_FILE = 'personal_tiles_state.json'


def _seen_state_path():
    if kodi_utils is None:
        return ''
    try:
        return os.path.join(kodi_utils.addon_profile_path(), _SEEN_STATE_FILE)
    except Exception:
        return ''


def _load_seen_state():
    """Persistent set of tile keys we've inserted at least once. Survives
    Kodi's comment-stripping favourites rewrites (unlike the XML markers)."""
    p = _seen_state_path()
    if not p or not os.path.isfile(p):
        return set()
    try:
        with open(p, 'r', encoding='utf-8') as f:
            d = json.loads(f.read())
        return set(d.get('seen') or [])
    except (IOError, OSError, ValueError):
        return set()


def _save_seen_state(seen):
    p = _seen_state_path()
    if not p:
        return
    try:
        with open(p, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'seen': sorted(seen)}))
    except OSError:
        pass


def _insert_debrid_notice_tile(content, fixture_text):
    """Restore the subscription-notification settings tile once.

    This is intentionally not a mandatory tile. After the tile has been
    seen/restored once, we record it in a PERSISTENT JSON sidecar so users can
    delete it without quick updates adding it back forever.

    Why JSON and not just the XML comment marker: when a user deletes a
    favourite via Kodi's GUI, Kodi rewrites favourites.xml and STRIPS XML
    comments -- so the marker vanishes, the patcher thinks the tile was never
    added, and re-inserts it on the next startup ("the tile that keeps coming
    back"). A separate JSON file Kodi never touches, so the deletion sticks.
    (Same reason the home-tiles patcher uses home_tiles_state.json.)
    """
    action_b = FIXED_DEBRID_NOTICE_ACTION.encode('utf-8')
    seen = _load_seen_state()
    if action_b in content:
        # Tile present -> persist "seen" so a LATER delete sticks even after
        # Kodi strips the comment marker.
        if 'debrid_notice' not in seen:
            seen.add('debrid_notice')
            _save_seen_state(seen)
        new_content, marker_added = _insert_marker(
            content, DEBRID_NOTICE_SEEN_MARKER)
        return new_content, marker_added
    # Tile absent: if we've ever seen it (persistent flag OR legacy comment),
    # respect the deletion and never re-add.
    if 'debrid_notice' in seen or _has_marker(content, DEBRID_NOTICE_SEEN_MARKER):
        return content, False

    snippet = _extract_tile_by_action(fixture_text, FIXED_DEBRID_NOTICE_ACTION)
    if snippet is None:
        return content, False
    tile = snippet.encode('utf-8')

    connect_pattern = re.compile(
        rb'([ \t]*<favourite\b(?:(?!</favourite>).)*?'
        + re.escape(CONNECT_SERVICES_ICON.encode('utf-8'))
        + rb'(?:(?!</favourite>).)*?</favourite>\s*\n)',
        re.DOTALL,
    )
    connect_match = connect_pattern.search(content)
    if connect_match is not None:
        new_content = (
            content[:connect_match.end(1)]
            + tile
            + content[connect_match.end(1):]
        )
    else:
        pov_match = _service_tile_pattern('RunAddon("plugin.video.pov")').search(
            content)
        if pov_match is not None:
            new_content = (
                content[:pov_match.end(1)]
                + tile
                + content[pov_match.end(1):]
            )
        else:
            inserted = _insert_tiles_before_close(content, (tile,))
            if inserted is None:
                return content, False
            new_content = inserted
    # Persist "seen" the first (and only) time we insert it.
    seen.add('debrid_notice')
    _save_seen_state(seen)
    new_content, _marker_added = _insert_marker(
        new_content, DEBRID_NOTICE_SEEN_MARKER)
    return new_content, True


def _mdblist_connected():
    """True only when POV has an MDBList API key stored. The MDBList tiles route
    through POV's mdblist_watchlist action, which errors without a key -- so we
    never surface them unless MDBList is actually connected."""
    try:
        import xbmcaddon
        tok = xbmcaddon.Addon('plugin.video.pov').getSetting('mdblist.token') or ''
        return bool(tok.strip())
    except Exception:
        return False


def _xml_unescape(s):
    """The five predefined XML entities, &amp; LAST so an escaped entity like
    &amp;lt; survives one round trip instead of collapsing to '<'."""
    for ent, ch in (('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'),
                    ('&apos;', "'"), ('&amp;', '&')):
        s = s.replace(ent, ch)
    return s


_ACTIVATE_RE = re.compile(
    r'ActivateWindow\(\s*([^,()"]+?)\s*,\s*"(.*)"\s*,\s*return\s*\)\s*$',
    re.DOTALL)


def _tile_to_jsonrpc(tile_text):
    """Translate one canonical <favourite> element into the arguments Kodi's
    Favourites.AddFavourite takes. Returns None for any tile shape we don't
    fully understand -- a partial translation would create a BROKEN favourite,
    which is worse than the tile simply appearing one restart later."""
    name = re.search(r'name="([^"]*)"', tile_text)
    body = re.search(r'>((?:(?!</favourite>).)*)</favourite>', tile_text,
                     re.DOTALL)
    if not name or not body:
        return None
    act = _ACTIVATE_RE.search(_xml_unescape(body.group(1).strip()))
    if not act:
        return None
    thumb = re.search(r'thumb="([^"]*)"', tile_text)
    params = {
        'title': _xml_unescape(name.group(1)),
        'type': 'window',
        'window': act.group(1),
        'windowparameter': act.group(2),
    }
    if thumb:
        params['thumbnail'] = _xml_unescape(thumb.group(1))
    return params


def _jsonrpc(method, params):
    if xbmc is None:
        return None
    try:
        raw = xbmc.executeJSONRPC(json.dumps(
            {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}))
        resp = json.loads(raw)
    except Exception:
        return None
    if not isinstance(resp, dict) or 'result' not in resp:
        return None
    return resp['result']


def _live_favourite_keys():
    """Everything that identifies a favourite Kodi is holding IN MEMORY right
    now -- its title AND its target -- or None if we can't ask.

    Both, because AddOrRemove decides "already there?" by the favourite's URL,
    not by its title. Matching on the title alone would let a tile that Kodi has
    under any other label slip through the guard and be TOGGLED OFF, deleting a
    tile the user still has. Collecting the targets too means the guard errs the
    only safe way: a false match just leaves the tile to appear next restart.

    None is deliberately different from the empty set: 'we don't know' must not
    be read as 'Kodi has nothing'."""
    result = _jsonrpc('Favourites.GetFavourites',
                      {'properties': ['window', 'windowparameter', 'path']})
    if not isinstance(result, dict):
        return None
    favs = result.get('favourites')
    if favs is None:            # Kodi may omit/null the key when there are 0
        return set() if result.get('limits') is not None else None
    if not isinstance(favs, list):
        return None
    keys = set()
    for f in favs:
        if not isinstance(f, dict):
            continue
        for field in ('title', 'windowparameter', 'path'):
            val = f.get(field)
            if isinstance(val, str) and val:
                keys.add(val)
    return keys


def _live_add_tiles(tiles):
    """Push freshly-inserted tiles into Kodi's LIVE favourites list.

    Kodi reads favourites.xml exactly once, when the profile loads, and serves
    every later query from that in-memory copy -- CFavouritesService::ReInit()
    fills m_favourites, GetAll() copies out of it, and nothing watches the file.
    The home screen's <content>favourites://</content> therefore cannot see a
    tile we appended to the file behind Kodi's back: it shows up only after the
    NEXT restart. That is the whole bug behind "I connected MDBList, ran a quick
    update, and the tiles still aren't on the home screen" -- one restart writes
    them, and a second, unprompted one is what finally reveals them.

    Favourites.AddFavourite adds to the in-memory list, so the tile appears at
    once. Two things make that safe:
      * It TOGGLES (AddOrRemove): asking for a tile Kodi already has would
        DELETE it. So we ask Kodi what it has first -- by title AND by target,
        since the toggle keys on the target -- skip anything that matches, and
        do nothing at all when the query fails.
      * It persists the in-memory list over favourites.xml, dropping our markers
        and tile positioning. So this runs BEFORE our own atomic write, never
        after -- ours is the copy that survives on disk, Kodi's is the copy that
        renders this session, and the next restart makes them one.
    Best-effort throughout: any failure just means the old one-restart delay.
    """
    live = _live_favourite_keys()
    if live is None:
        return 0
    added = 0
    for tile_text in tiles:
        params = _tile_to_jsonrpc(tile_text)
        if not params:
            continue
        if params['title'] in live or params['windowparameter'] in live:
            continue
        if _jsonrpc('Favourites.AddFavourite', params) == 'OK':
            added += 1
    return added


# The two Umbrella-era tiles: the search-engine switch and Umbrella itself.
# Both are meaningless without Umbrella, so they are inserted ONLY on installs
# that have it -- exactly the rule the MDBList pair follows. Add-only and
# fire-once through the json sidecar, so deleting one makes it stay deleted.
UMBRELLA_TILE_NAMES = (
    '[B][COLOR orange]מנוע החיפוש - POV / Umbrella[/COLOR][/B]',
    '[B][COLOR orange]Umbrella[/COLOR][/B]',
)
UMBRELLA_TILES_SEEN_KEY = 'umbrella_tiles'
UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
# Anchor: the subscription-notification tile, itself anchored to the
# "חיבור שירותים" tile. That puts the pair with the other build-service tiles
# at the top of the home row instead of at the very bottom past the content.
_DEBRID_NOTICE_TILE_NAME = '[B][COLOR orange]הגדרת התראות מנוי[/COLOR][/B]'


def _umbrella_installed():
    try:
        import xbmcaddon
        xbmcaddon.Addon(UMBRELLA_ADDON_ID)
        return True
    except Exception:
        return False


def _drop_umbrella_tiles(fixture_text):
    """The fixture minus the two Umbrella-gated tiles. For the one caller that
    writes the fixture WHOLE rather than tile by tile."""
    out = fixture_text
    for name in UMBRELLA_TILE_NAMES:
        snippet = _extract_tile(out, name)
        if snippet is not None:
            out = out.replace(snippet, '', 1)
    return out


# The "שליחת לוג" tile used to open POV's own Changelog & Log Utils MENU in a
# video window (mode=navigator.log_utils) and leave the user to find the
# upload inside it. Field report: it loads forever and never gets anywhere --
# a container that never returns a directory just spins, with no error and no
# way out but Back.
#
# Whatever is wrong inside POV, the tile did not need to go there at all: the
# Wizard has its own uploader (`mode=uploadlog` -> logging.upload_log()),
# which posts the log and shows the URL and a QR. It is our code, it does the
# one thing the tile is named after, and RunPlugin does not open a container
# at all -- so it cannot hang one.
_OLD_SEND_LOG = b'mode=navigator.log_utils'
_NEW_SEND_LOG = (b'RunPlugin("plugin://plugin.program.kodipovilwizard/'
                 b'?mode=uploadlog")')
_SEND_LOG_RE = re.compile(
    rb'(<favourite\b(?:(?!</favourite>).)*?>)'
    rb'((?:(?!</favourite>).)*?mode=navigator\.log_utils'
    rb'(?:(?!</favourite>).)*?)(</favourite>)',
    re.DOTALL,
)


def _fix_existing_send_log_action(content):
    """Repoint an existing "send log" tile at the Wizard's own uploader.
    Returns (content, changed). Touches only that one element's action; the
    tile's name and icon are left exactly as the user has them."""
    if _OLD_SEND_LOG not in content:
        return content, False
    new_content, n = _SEND_LOG_RE.subn(
        lambda m: m.group(1) + _NEW_SEND_LOG + m.group(3), content)
    if not n:
        return content, False
    _log('repointed the "send log" tile at the Wizard uploader ({0} tile(s))'
         .format(n))
    return new_content, True


def _insert_umbrella_tiles(content, fixture_text):
    """One-time, opt-in insert of the Umbrella + search-engine-switch tiles for
    an existing install (clean installs get them from the shipped fixture).
    Gated on Umbrella being installed; add-only; fire-once via the json sidecar
    so a later deletion sticks even after Kodi strips XML comments.
    Returns (content, changed)."""
    if not _umbrella_installed():
        # Not installed -> never add, and never stamp: installing Umbrella
        # later must still get the tiles.
        return content, False
    seen = _load_seen_state()
    missing = _missing_tiles(content, UMBRELLA_TILE_NAMES)
    if not missing:
        # Present -> persist "seen" so a LATER delete sticks.
        if UMBRELLA_TILES_SEEN_KEY not in seen:
            seen.add(UMBRELLA_TILES_SEEN_KEY)
            _save_seen_state(seen)
        return content, False
    if UMBRELLA_TILES_SEEN_KEY in seen:
        return content, False            # deleted on purpose -- leave it
    tiles = []
    for name in missing:
        snippet = _extract_tile(fixture_text, name)
        if snippet is None:
            return content, False        # fixture incomplete -> safe no-op
        tiles.append(snippet.encode('utf-8'))
    anchor = re.compile(
        rb'([ \t]*<favourite\s[^>]*?name="'
        + re.escape(_DEBRID_NOTICE_TILE_NAME.encode('utf-8'))
        + rb'"[^>]*>(?:(?!</favourite>).)*?</favourite>\s*\n)',
        re.DOTALL,
    ).search(content)
    if anchor is not None:
        new_content = (content[:anchor.end(1)] + b''.join(tiles)
                       + content[anchor.end(1):])
    else:
        new_content = _insert_tiles_before_close(content, tiles)
        if new_content is None:
            return content, False
    # NOT stamped here. "Seen" means the tiles reached the disk, and this file
    # has not been written yet -- stamping now would treat a failed write as a
    # completed insert and never try again. ensure_patched() stamps it after
    # the write succeeds, exactly as the MDBList pair does.
    _log('adding the Umbrella / search-engine home tiles ({0})'.format(
        len(tiles)))
    return new_content, True


# The per-skin favourites SEEDS the wizard copies over userdata/favourites.xml
# on every skin switch (update_favourites_xml_file). A tile that exists only in
# the user's file is lost the first time they switch skin, and the sidecar then
# reads that loss as a deletion and never brings it back. Adding the tiles to
# the seeds as well is the actual fix: it is where a skin switch gets its
# content from.
_FAVOURITES_SEEDS = (
    'special://home/media/builds_favourites_xml/skin.fentastic/favourites.xml',
    'special://home/media/builds_favourites_xml/skin.estuary/favourites.xml',
)


def _seed_umbrella_tiles(fixture_text):
    """Add the two Umbrella-era tiles to the per-skin favourites seeds, so a
    skin switch keeps them instead of wiping them. Add-only and idempotent;
    each seed is left alone if it already has them or cannot be read.
    Returns the number of seeds updated. Never raises."""
    if not _umbrella_installed():
        return 0
    tiles_by_name = {}
    for name in UMBRELLA_TILE_NAMES:
        snippet = _extract_tile(fixture_text, name)
        if snippet is None:
            return 0                     # fixture incomplete -> safe no-op
        tiles_by_name[name] = snippet.encode('utf-8')
    updated = 0
    for seed in _FAVOURITES_SEEDS:
        try:
            path = xbmcvfs.translatePath(seed)
        except Exception:
            continue
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'rb') as f:
                seed_content = f.read()
        except OSError:
            continue
        missing = _missing_tiles(seed_content, UMBRELLA_TILE_NAMES)
        if not missing:
            continue
        new_seed = _insert_tiles_before_close(
            seed_content, [tiles_by_name[n] for n in missing])
        if new_seed is None:
            continue                     # no </favourites> -> leave it alone
        tmp = path + '.aitmp'
        try:
            with open(tmp, 'wb') as f:
                f.write(new_seed)
            os.replace(tmp, path)
            updated += 1
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            _log('could not update favourites seed {0}: {1}'.format(seed, e),
                 level='WARNING')
    if updated:
        _log('added the Umbrella / search-engine tiles to {0} favourites '
             'seed(s), so a skin switch keeps them'.format(updated))
    return updated


def _insert_mdblist_tiles(content, fixture_text):
    """One-time, opt-in restore of the two MDBList personal tiles for an existing
    install that already has a favourites.xml (clean installs get them from the
    shipped seed). Gated on MDBList being connected; add-only; fire-once via the
    json sidecar so a later deletion sticks even after Kodi strips XML comments.
    Returns (content, changed)."""
    if not _mdblist_connected():
        return content, False            # not connected -> never add, never stamp
    seen = _load_seen_state()
    already_present = _missing_tiles(content, MDBLIST_WATCHLIST_TILE_NAMES) == ()
    # The one-time forced restore (see MDBLIST_RESEED_MARKER). Claimed BEFORE
    # the checks below so it is spent exactly once whether or not it ends up
    # inserting anything -- an install that already has the tiles must not keep
    # the credit and spend it after a genuine deletion later.
    forced = (not _has_marker(content, MDBLIST_RESEED_MARKER)
              and MDBLIST_RESEED_KEY not in seen)
    if forced:
        seen.add(MDBLIST_RESEED_KEY)
        _save_seen_state(seen)
    if already_present:
        # Tiles present -> persist "seen" so a LATER delete sticks.
        if 'mdblist_tiles' not in seen:
            seen.add('mdblist_tiles')
            _save_seen_state(seen)
        return content, False
    # Absent: if we've ever inserted them, respect the deletion and never re-add
    # -- unless this is the single forced restore, which overrides exactly once.
    if not forced and ('mdblist_tiles' in seen
                       or _has_marker(content, MDBLIST_TILES_SEEN_MARKER)):
        return content, False
    tiles = []
    tile_texts = []
    # Insert only the ACTUALLY-missing tile(s): if the user deleted just one of the
    # pair (and we never got to stamp 'seen'), never duplicate the survivor.
    for name in _missing_tiles(content, MDBLIST_WATCHLIST_TILE_NAMES):
        snippet = _extract_tile(fixture_text, name)
        if snippet is None:
            return content, False        # fixture incomplete -> safe no-op
        tiles.append(snippet.encode('utf-8'))
        tile_texts.append(snippet)
    pov_movies_pat = re.compile(
        rb'([ \t]*<favourite\s[^>]*?name="'
        + re.escape(_POV_MOVIES_TILE_NAME.encode('utf-8'))
        + rb'"[^>]*>(?:(?!</favourite>).)*?</favourite>\s*\n)',
        re.DOTALL,
    )
    m = pov_movies_pat.search(content)
    if m is not None:
        new_content = content[:m.end(1)] + b''.join(tiles) + content[m.end(1):]
    else:
        inserted = _insert_tiles_before_close(content, tiles)
        if inserted is None:
            return content, False
        new_content = inserted
    new_content, _ = _insert_marker(new_content, MDBLIST_TILES_SEEN_MARKER)
    new_content, _ = _insert_marker(new_content, MDBLIST_RESEED_MARKER)
    # NOT stamping the sidecar here, deliberately. 'mdblist_tiles' means "we
    # have inserted these once, so a later deletion is the user's and must be
    # respected" -- and only a successful write earns that. Stamping here would
    # make a failed write (disk full, permissions) permanent: the tiles would
    # never reach the file, and every future boot would skip re-inserting them
    # because the sidecar said the job was done. ensure_patched() stamps it
    # after os.replace() has actually landed.
    live = _live_add_tiles(tile_texts)
    if live:
        _log('added {0} MDBList tile(s) to the running Kodi favourites list '
             '-- no restart needed'.format(live), level='INFO')
    return new_content, True


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


def _favourite_count(content):
    return len(re.findall(rb'<favourite\b', content))


# A home screen this bare is damage, not a preference.
#
# The rule below stays "never rebuild from startup patching", because a missing
# tile on a working install really is more likely to be the user's own doing --
# that lesson was expensive and it stands. But it was applied to EVERY state,
# including one that cannot possibly be a preference: a favourites.xml with
# almost nothing in it.
#
# Fresh installs keep landing on an empty FENtastic home. The build zip ships a
# 36-tile userdata/favourites.xml, so something between the zip and the first
# boot is losing it -- and whatever that something is, we could always have
# repaired it: the canonical fixture is bundled in this add-on, and this
# function was the one thing refusing to use it. Users work around it by
# switching skin to NOX and back, which makes the wizard copy a favourites seed
# over the file, which is exactly the repair we declined to do.
#
# So: below this many favourites, restore the canonical surface once. Nobody
# curates their home down to three tiles; a build install that ends up there is
# broken. Above it, nothing changes -- deletions stay respected permanently,
# which is what the retired forced reseeds got wrong.
_EMPTY_HOME_MAX_FAVOURITES = 6


def _should_restore_full_build_tiles(content, _missing_full_tiles):
    """False for anything that could be a preference; True only for a home
    screen so bare that it can only be a broken install (see above)."""
    return _favourite_count(content) <= _EMPTY_HOME_MAX_FAVOURITES


def _insert_tiles_before_close(content, tiles):
    if not tiles:
        return content
    closing_tag = b'</favourites>'
    close_idx = content.rfind(closing_tag)
    if close_idx == -1:
        return None
    return content[:close_idx] + b''.join(tiles) + content[close_idx:]


def _install_canonical_home(fav_path, content):
    """Lay down the canonical favourites.xml for a home screen that has
    effectively nothing on it, keeping anything the user does have.

    Only ever called for a file with at most _EMPTY_HOME_MAX_FAVOURITES entries
    (or none at all), so "keeping what they have" is a handful of tiles at most:
    every favourite whose name the fixture does not already provide is appended,
    so a custom shortcut added before the repair survives it.

    Returns a status string; never raises."""
    fixture_path = _fixture_path()
    try:
        with open(fixture_path, 'r', encoding='utf-8') as f:
            fixture_text = f.read()
    except OSError as e:
        _log('cannot rescue an empty home, fixture unreadable: {0}'.format(e),
             level='WARNING')
        return 'no_fixture'
    # The fixture is the WHOLE canonical home, so it also carries the tiles
    # that are only meant for installs with Umbrella. Everywhere else that
    # gate is applied per tile; here the file goes down verbatim, which would
    # hand a device with no Umbrella a tile that opens an add-on it does not
    # have. Drop them, exactly as _insert_umbrella_tiles would have.
    if not _umbrella_installed():
        fixture_text = _drop_umbrella_tiles(fixture_text)
    new_content = fixture_text.encode('utf-8')
    keep = []
    for tile_text in _extract_fixture_tiles(content.decode('utf-8', 'replace')):
        name, _action = _tile_identity(tile_text)
        if not name:
            continue
        # Compare the whole name="..." attribute, not the bare name. A bare
        # substring test says a tile called "a" is already present because the
        # letter appears somewhere in the canonical file, and silently drops it.
        probe = ('name="%s"' % name).encode('utf-8')
        if probe not in new_content:
            keep.append(tile_text.encode('utf-8'))
    if keep:
        merged = _insert_tiles_before_close(new_content, keep)
        if merged is not None:
            new_content = merged
    tmp_path = fav_path + '.aitmp'
    try:
        d = os.path.dirname(fav_path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(tmp_path, 'wb') as f:
            f.write(new_content)
        os.replace(tmp_path, fav_path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('empty-home rescue could not write {0}: {1}'.format(fav_path, e),
             level='WARNING')
        return 'write_failed'
    _log('the home screen had {0} favourite(s) -- restored the {1} canonical '
         'build tiles{2}. A build install that lands here is broken, not '
         'customised.'.format(
             _favourite_count(content), _favourite_count(fixture_text.encode(
                 'utf-8')),
             ' (kept %d of your own)' % len(keep) if keep else ''),
         level='INFO')
    return 'restored_empty_home'


def ensure_patched():
    """Returns one of:
    'no_kodi' | 'no_favourites' | 'no_fixture' | 'fixture_unreadable'
    | 'already_complete' | 'unparseable_fixture' | 'read_failed'
    | 'write_failed' | 'restored'."""
    if xbmcvfs is None:
        return 'no_kodi'
    fav_path = _favourites_path()
    if not fav_path:
        return 'no_favourites'
    if not os.path.isfile(fav_path):
        # No favourites.xml at all -- a completely empty userdata. This used to
        # no-op ("that's the wizard's job"), which is the same refusal that left
        # fresh installs staring at an empty home. It is the wizard's job, but
        # when the wizard has not done it there is nobody else, and we are
        # holding the canonical file.
        return _install_canonical_home(fav_path, b'')
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

    # An all-but-empty home, before anything else. Splicing tiles into it is not
    # enough -- a truncated or tagless file has nowhere to splice them, which is
    # precisely the shape a fresh install shows up with.
    if _should_restore_full_build_tiles(content, None):
        return _install_canonical_home(fav_path, content)

    had_restore_marker = _has_restore_marker(content)
    had_service_marker = _has_marker(content, SERVICE_SEEN_MARKER)
    had_full_marker = _has_marker(content, FULL_BUILD_SEEN_MARKER)
    # Reseed "already done" flags: check the PERSISTENT json sidecar too, not
    # only the XML comment markers. Kodi STRIPS XML comments from favourites.xml
    # whenever the user edits favourites via the GUI -- which wiped these markers
    # and made the one-time forced restores RE-FIRE on the next update, bringing
    # back tiles the user had deliberately deleted. The json sidecar (which Kodi
    # never touches) makes each forced reseed fire exactly ONCE, ever.
    _reseed_seen = _load_seen_state()
    had_premiumize_reseed = (_has_marker(content, SERVICE_RESEED_MARKER)
                             or 'premiumize_reseed' in _reseed_seen)
    had_personal_reseed = (_has_marker(content, PERSONAL_RESEED_MARKER)
                           or 'personal_reseed' in _reseed_seen)
    had_full_reseed = (_has_marker(content, FULL_BUILD_RESEED_MARKER)
                       or 'full_build_reseed' in _reseed_seen)
    content, fixed_existing = _fix_existing_debrid_notice_action(content)
    content, fixed_torbox_status = _fix_existing_torbox_status_action(content)
    content, debrid_notice_restored = _insert_debrid_notice_tile(
        content, fixture_text)
    content, mdblist_restored = _insert_mdblist_tiles(content, fixture_text)
    content, umbrella_tiles_added = _insert_umbrella_tiles(
        content, fixture_text)
    content, send_log_fixed = _fix_existing_send_log_action(content)
    # Independent of the user's own file: the seeds are what a skin switch
    # copies over it, so they need the tiles whether or not the user's file
    # got them this time round.
    try:
        _seed_umbrella_tiles(fixture_text)
    except Exception as e:
        _log('favourites seed update failed: {0}'.format(e), level='WARNING')
    content, service_position_fixed = (
        _move_existing_service_tile_after_torbox(content))

    # Wizard installs on clean Kodi can seed a partial favourites.xml:
    # the top personal tiles exist, but genre/popular/network rows are
    # missing. Restore the whole canonical build surface once, without
    # replacing the file or deleting user custom favourites.
    missing_full_tiles = []
    if not had_full_marker or not had_full_reseed:
        candidate_full_tiles = _canonical_tiles_missing_from_content(
            content, fixture_text)
        # Forced restore of the canonical surface is RETIRED (was: fire once per
        # install to repair the old buggy reseed that wiped per-service network
        # tiles). That migration is long past for the whole fleet, and while it
        # was live it also resurrected tiles users had DELIBERATELY deleted --
        # so every quick update looked like it "reset the home screen back to
        # default". We now honour deletions permanently on every skin: the only
        # remaining canonical restore is the normally-disabled heuristic
        # (_should_restore_full_build_tiles, which returns False), so a genuinely
        # missing tile is treated as intentional user customisation, not damage.
        force_full = False
        if candidate_full_tiles and (
                force_full
                or (not had_full_marker
                    and _should_restore_full_build_tiles(
                        content, candidate_full_tiles))):
            missing_full_tiles = candidate_full_tiles
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
    # Forced restore of the Premiumize status tile and of the personal tiles is
    # RETIRED for the same reason as the full-build force above: it repaired the
    # old buggy reseed once, but also brought back tiles users had deleted, so it
    # read as "the update reset my home screen". Deletions are now respected
    # permanently on every skin. (The reseed markers/sidecar keys are still
    # stamped below so nothing regresses if this ever gets re-enabled.)
    force_premiumize = False
    force_personal = False
    if missing_personal:
        if (not fixed_existing and not fixed_torbox_status
                and not service_position_fixed and not force_premiumize
                and not force_personal and not mdblist_restored
                and not umbrella_tiles_added and not send_log_fixed
                and (not missing_service or had_service_marker)
                ):
            return 'user_removed_tiles'
        # A user may delete the tiles after receiving the broken-action
        # version. Keep the deletion respected (unless this is the one-time
        # re-seed), but still persist the action fix if the old action exists.
        if not force_personal:
            missing_personal = ()
    if missing_service and not force_premiumize:
        missing_service = ()
    missing = missing_personal + missing_service

    new_content = content
    marker_added = False
    service_marker_added = False
    full_marker_added = False
    # Always stamp the Premiumize re-seed marker once, so the forced restore
    # above can never repeat (genuine future deletions stay respected).
    reseed_marker_added = False
    if not had_premiumize_reseed:
        new_content, reseed_marker_added = _insert_marker(
            new_content, SERVICE_RESEED_MARKER)
    personal_reseed_added = False
    if not had_personal_reseed:
        new_content, personal_reseed_added = _insert_marker(
            new_content, PERSONAL_RESEED_MARKER)
    # Stamp the full-build re-seed marker once, so the forced canonical restore
    # above can never repeat (genuine future deletions stay respected).
    full_reseed_added = False
    if not had_full_reseed:
        new_content, full_reseed_added = _insert_marker(
            new_content, FULL_BUILD_RESEED_MARKER)
    # Persist the reseed flags to the json sidecar (survives Kodi's comment
    # stripping) so each forced restore fires ONCE ever -- after that, a genuine
    # deletion is respected permanently, including across every future update.
    _new_reseed = set()
    if not had_premiumize_reseed:
        _new_reseed.add('premiumize_reseed')
    if not had_personal_reseed:
        _new_reseed.add('personal_reseed')
    if not had_full_reseed:
        _new_reseed.add('full_build_reseed')
    if _new_reseed:
        try:
            _s = _load_seen_state()
            _s |= _new_reseed
            _save_seen_state(_s)
        except Exception:
            pass
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
            and not debrid_notice_restored and not mdblist_restored
            and not umbrella_tiles_added and not send_log_fixed
            and not service_position_fixed and not full_marker_added
            and not reseed_marker_added and not personal_reseed_added
            and not full_reseed_added
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

    if mdblist_restored:
        # Only now, with the file actually on disk, does "we have inserted these
        # once" become true -- and only then may a future deletion be treated as
        # the user's and left alone. See _insert_mdblist_tiles.
        try:
            _s = _load_seen_state()
            if 'mdblist_tiles' not in _s:
                _s.add('mdblist_tiles')
                _save_seen_state(_s)
        except Exception:
            pass

    if umbrella_tiles_added:
        # Same rule, same reason: only a tile that reached the disk counts as
        # inserted, and only then may a future deletion be left alone.
        try:
            _s = _load_seen_state()
            if UMBRELLA_TILES_SEEN_KEY not in _s:
                _s.add(UMBRELLA_TILES_SEEN_KEY)
                _save_seen_state(_s)
        except Exception:
            pass

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
    if debrid_notice_restored:
        _log('restored subscription notification settings tile', level='INFO')
    if mdblist_restored:
        _log('restored MDBList personal tiles (My Movies/My Series)', level='INFO')
    if umbrella_tiles_added:
        _log('added the Umbrella + search-engine home tiles', level='INFO')
    if send_log_fixed:
        _log('send-log tile now uses the Wizard uploader', level='INFO')
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
