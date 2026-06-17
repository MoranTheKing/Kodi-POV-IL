# Self-healing migration of home-screen "My shows / My movies" tiles
# in userdata/favourites.xml.
#
# Two responsibilities, both surgical and idempotent:
#
# 1. MIGRATE legacy Trakt-collection tiles to TMDB-favourites tiles.
#    Matches on tile identity (visible label + action + mode) so
#    that whitespace and attribute order differences from a Kodi
#    GUI rewrite don't break the migration.
#
# 2. ENSURE the TMDB tile thumb points at the TMDB-branded icon
#    (My_Shows_TMDB.png / My_Movies_TMDB.png) -- earlier patcher
#    versions left the thumb pointing at the original Trakt-branded
#    icon, which looked misleading.
#
# 3. RESTORE Trakt-collection tiles for users who DO have a Trakt
#    account configured. Earlier patcher versions REPLACED the
#    Trakt tiles with TMDB ones, leaving users with both services
#    connected unable to access their Trakt collection from the
#    home screen. Now: if the user has Trakt connected
#    (POV setting `trakt_user` non-empty) and the Trakt tile is
#    missing, append it just after the matching TMDB tile.
#
# Defensive: if the user customized one of the tiles (different
# action / name / thumb that doesn't match our patterns) the
# patcher leaves it alone. If the user has Trakt disconnected,
# Trakt tiles are not added (clean home screen for TMDB-only).

import os
import re
import json

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


FAVOURITES_RELATIVE = 'favourites.xml'

# State for "respect user deletions": which personal tiles were present last
# run (seen) and which the user has deleted (removed -> never restore again).
# Stored as a JSON file (not a setting -> no settings.xml control noise).
_STATE_FILE = 'home_tiles_state.json'


def _state_path():
    try:
        return os.path.join(kodi_utils.addon_profile_path(), _STATE_FILE)
    except Exception:
        return ''


def _load_state():
    p = _state_path()
    if p and os.path.isfile(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                d = json.loads(f.read())
            return set(d.get('seen') or []), set(d.get('removed') or [])
        except (IOError, OSError, ValueError):
            pass
    return set(), set()


def _save_state(seen, removed):
    p = _state_path()
    if not p:
        return
    try:
        with open(p, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'seen': sorted(seen),
                                'removed': sorted(removed)}))
    except OSError:
        pass


def _present(content):
    """Return the set of restorable personal-tile keys currently in the file,
    plus the set of mediatypes whose TMDB anchor tile is present."""
    present, anchors = set(), set()
    for media in MEDIA:
        label = media['label']
        if media['tmdb_pattern'].search(content):
            anchors.add(label)
        if media['trakt_pattern'].search(content):
            present.add(label + '_trakt')
        if media['pov_pattern'].search(content):
            present.add(label + '_pov')
    return present, anchors

# Per-mediatype constants: regex to find an existing TMDB tile, an
# OLD Trakt-collection tile, and a baked Trakt-tile-line we add when
# restoring. Order kept consistent so loops can iterate by index.
MEDIA = (
    {
        'label': 'shows',
        'name_token': 'הסדרות שלי',
        'mode': 'build_tvshow_list',
        # TMDB favourite tile, current (post-v0.2.18) form. Used both
        # to find the tile and to test "has TMDB tile already".
        'tmdb_pattern': re.compile(
            r'<favourite\s[^>]*?name="\[B\]הסדרות שלי \(TMDB\)\[/B\]"[^>]*>'
            r'(?:(?!</favourite>).)*?action=tmdb_(?:favorites|my_tvshows)'
            r'(?:(?!</favourite>).)*?mode=build_tvshow_list'
            r'(?:(?!</favourite>).)*?</favourite>',
            re.DOTALL,
        ),
        # Trakt-collection tile (the legacy original, also what we
        # restore for users with Trakt connected).
        'trakt_pattern': re.compile(
            r'<favourite\s[^>]*?name="\[B\]הסדרות שלי \(Trakt\)\[/B\]"[^>]*>'
            r'(?:(?!</favourite>).)*?action=trakt_(?:collection|my_tvshows)'
            r'(?:(?!</favourite>).)*?mode=build_tvshow_list'
            r'(?:(?!</favourite>).)*?</favourite>',
            re.DOTALL,
        ),
        # Canonical TMDB tile with the new TMDB-branded thumb.
        'tmdb_canonical': (
            '<favourite name="[B]הסדרות שלי (TMDB)[/B]" '
            'thumb="special://home/media/build_icons/Twilight/Shows/'
            'My_Shows_TMDB.png">'
            'ActivateWindow(10025,"plugin://plugin.video.pov/?'
            'action=tmdb_my_tvshows&amp;iconImage=special%3a%2f%2fhome%2f'
            'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
            'media%2ftmdb.png&amp;mode=build_tvshow_list&amp;'
            'name=TV%20Show%20Favorites",return)</favourite>'
        ),
        # Canonical Trakt tile, restored after the TMDB one when the
        # user has Trakt connected.
        'trakt_canonical': (
            '<favourite name="[B]הסדרות שלי (Trakt)[/B]" '
            'thumb="special://home/media/build_icons/Twilight/Shows/'
            'My_Shows.png">'
            'ActivateWindow(10025,"plugin://plugin.video.pov/?'
            'action=trakt_my_tvshows&amp;iconImage=special%3a%2f%2fhome%2f'
            'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
            'media%2ftrakt.png&amp;mode=build_tvshow_list&amp;'
            'name=TV%20Shows",return)</favourite>'
        ),
        # POV local-favorites tile -- always present (independent of
        # TMDB / Trakt connection), since POV maintains its own
        # local favorites DB. Lets users keep a personal list
        # without depending on any external service.
        'pov_pattern': re.compile(
            r'<favourite\s[^>]*?name="\[B\]הסדרות שלי \(POV\)\[/B\]"[^>]*>'
            r'(?:(?!</favourite>).)*?action=favorites_tvshows'
            r'(?:(?!</favourite>).)*?mode=build_tvshow_list'
            r'(?:(?!</favourite>).)*?</favourite>',
            re.DOTALL,
        ),
        'pov_canonical': (
            '<favourite name="[B]הסדרות שלי (POV)[/B]" '
            'thumb="special://home/media/build_icons/Twilight/Shows/'
            'My_Shows_POV.png">'
            'ActivateWindow(10025,"plugin://plugin.video.pov/?'
            'action=favorites_tvshows&amp;iconImage=special%3a%2f%2fhome%2f'
            'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
            'media%2ffavorites.png&amp;mode=build_tvshow_list&amp;'
            'name=TV%20Show%20Favorites%20(POV)",return)</favourite>'
        ),
    },
    {
        'label': 'movies',
        'name_token': 'הסרטים שלי',
        'mode': 'build_movie_list',
        'tmdb_pattern': re.compile(
            r'<favourite\s[^>]*?name="\[B\]הסרטים שלי \(TMDB\)\[/B\]"[^>]*>'
            r'(?:(?!</favourite>).)*?action=tmdb_(?:favorites|my_movies)'
            r'(?:(?!</favourite>).)*?mode=build_movie_list'
            r'(?:(?!</favourite>).)*?</favourite>',
            re.DOTALL,
        ),
        'trakt_pattern': re.compile(
            r'<favourite\s[^>]*?name="\[B\]הסרטים שלי \(Trakt\)\[/B\]"[^>]*>'
            r'(?:(?!</favourite>).)*?action=trakt_(?:collection|my_movies)'
            r'(?:(?!</favourite>).)*?mode=build_movie_list'
            r'(?:(?!</favourite>).)*?</favourite>',
            re.DOTALL,
        ),
        'tmdb_canonical': (
            '<favourite name="[B]הסרטים שלי (TMDB)[/B]" '
            'thumb="special://home/media/build_icons/Twilight/Movies/'
            'My_Movies_TMDB.png">'
            'ActivateWindow(10025,"plugin://plugin.video.pov/?'
            'action=tmdb_my_movies&amp;iconImage=special%3a%2f%2fhome%2f'
            'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
            'media%2ftmdb.png&amp;mode=build_movie_list&amp;'
            'name=Movie%20Favorites",return)</favourite>'
        ),
        'trakt_canonical': (
            '<favourite name="[B]הסרטים שלי (Trakt)[/B]" '
            'thumb="special://home/media/build_icons/Twilight/Movies/'
            'My_Movies.png">'
            'ActivateWindow(10025,"plugin://plugin.video.pov/?'
            'action=trakt_my_movies&amp;iconImage=special%3a%2f%2fhome%2f'
            'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
            'media%2ftrakt.png&amp;mode=build_movie_list&amp;'
            'name=Movies",return)</favourite>'
        ),
        'pov_pattern': re.compile(
            r'<favourite\s[^>]*?name="\[B\]הסרטים שלי \(POV\)\[/B\]"[^>]*>'
            r'(?:(?!</favourite>).)*?action=favorites_movies'
            r'(?:(?!</favourite>).)*?mode=build_movie_list'
            r'(?:(?!</favourite>).)*?</favourite>',
            re.DOTALL,
        ),
        'pov_canonical': (
            '<favourite name="[B]הסרטים שלי (POV)[/B]" '
            'thumb="special://home/media/build_icons/Twilight/Movies/'
            'My_Movies_POV.png">'
            'ActivateWindow(10025,"plugin://plugin.video.pov/?'
            'action=favorites_movies&amp;iconImage=special%3a%2f%2fhome%2f'
            'addons%2fplugin.video.pov%2fresources%2fskins%2fDefault%2f'
            'media%2ffavorites.png&amp;mode=build_movie_list&amp;'
            'name=Movie%20Favorites%20(POV)",return)</favourite>'
        ),
    },
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('favourites_xml_patcher: ' + msg, level=level)
    except Exception:
        pass


def _favourites_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://profile/')
    except Exception:
        return ''
    p = os.path.join(base, FAVOURITES_RELATIVE)
    return p if os.path.isfile(p) else ''


def _trakt_connected():
    """Return True when POV settings indicate a Trakt account is
    configured. We read POV's settings.xml directly because POV
    isn't importable from inside our addon's process."""
    if xbmcvfs is None:
        return False
    try:
        pov_settings = xbmcvfs.translatePath(
            'special://profile/addon_data/plugin.video.pov/'
            'settings.xml')
    except Exception:
        return False
    if not os.path.isfile(pov_settings):
        return False
    try:
        with open(pov_settings, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return False
    # Look for the trakt_user setting line with a non-empty value.
    m = re.search(
        r'<setting\s+id="trakt_user"[^>]*>([^<]*)</setting>',
        content)
    if not m:
        return False
    return bool(m.group(1).strip())


def _process_one(content, media, trakt_connected, removed):
    """Apply migrate + thumb-update + restore-Trakt for one
    mediatype. Returns (new_content, dict_of_actions)."""
    label = media['label']
    actions = {}

    # 1. Migration: convert any leftover Trakt-collection tile to
    #    its canonical TMDB form.
    if media['tmdb_pattern'].search(content):
        # TMDB tile already present. Make sure thumb is canonical.
        actions[label + '_migrate'] = 'already'
    else:
        # No TMDB tile yet -- look for a Trakt-collection tile to
        # replace with the canonical TMDB form.
        new_content, n = media['trakt_pattern'].subn(
            media['tmdb_canonical'], content, count=1)
        if n:
            content = new_content
            actions[label + '_migrate'] = 'patched'
        else:
            actions[label + '_migrate'] = 'no_match'

    # 2. Thumb-update: rewrite any TMDB tile whose thumb still
    #    points at the OLD Trakt-branded icon.
    old_thumb_pat = (
        'thumb="special://home/media/build_icons/Twilight/'
        + ('Shows/My_Shows.png' if label == 'shows'
           else 'Movies/My_Movies.png') + '"'
    )
    new_thumb_pat = (
        'thumb="special://home/media/build_icons/Twilight/'
        + ('Shows/My_Shows_TMDB.png' if label == 'shows'
           else 'Movies/My_Movies_TMDB.png') + '"'
    )
    # Be careful: we only want to rewrite the thumb on the TMDB
    # tile, not on the Trakt one (which legitimately uses the
    # Trakt-branded icon). Match a tile that has tmdb_favorites
    # action AND the old thumb.
    thumb_pat = re.compile(
        r'<favourite\s[^>]*?name="\[B\]' + media['name_token']
        + r' \(TMDB\)\[/B\]"[^>]*?'
        + re.escape(old_thumb_pat)
        + r'[^>]*?>',
        re.DOTALL,
    )
    fix_count = 0
    def _swap_thumb(m):
        nonlocal fix_count
        fix_count += 1
        return m.group(0).replace(old_thumb_pat, new_thumb_pat)
    content = thumb_pat.sub(_swap_thumb, content)
    actions[label + '_thumb'] = (
        'fixed_{0}'.format(fix_count) if fix_count else 'ok')

    # 3. Restore Trakt tile if user has Trakt connected and the
    #    Trakt tile is missing -- UNLESS the user deleted it (respect that).
    if (label + '_trakt') in removed:
        actions[label + '_restore'] = 'user_removed'
    elif trakt_connected and not media['trakt_pattern'].search(content):
        m = media['tmdb_pattern'].search(content)
        if m:
            insert_at = m.end()
            # Match the indentation prefix of the TMDB tile so the
            # restored Trakt tile lines up visually in the XML.
            line_start = content.rfind('\n', 0, m.start()) + 1
            indent = content[line_start:m.start()]
            content = (
                content[:insert_at] + '\n' + indent
                + media['trakt_canonical'] + content[insert_at:]
            )
            actions[label + '_restore'] = 'added'
        else:
            actions[label + '_restore'] = 'no_anchor'
    elif trakt_connected:
        actions[label + '_restore'] = 'already'
    else:
        actions[label + '_restore'] = 'trakt_disconnected'

    # 4. Ensure the POV local-favorites tile is present -- UNLESS the user
    #    deleted it (respect that), otherwise insert after the Trakt/TMDB tile.
    if (label + '_pov') in removed:
        actions[label + '_pov'] = 'user_removed'
    elif media['pov_pattern'].search(content):
        actions[label + '_pov'] = 'already'
    else:
        anchor = (media['trakt_pattern'].search(content)
                  or media['tmdb_pattern'].search(content))
        if anchor:
            insert_at = anchor.end()
            line_start = content.rfind('\n', 0, anchor.start()) + 1
            indent = content[line_start:anchor.start()]
            content = (
                content[:insert_at] + '\n' + indent
                + media['pov_canonical'] + content[insert_at:]
            )
            actions[label + '_pov'] = 'added'
        else:
            actions[label + '_pov'] = 'no_anchor'

    return content, actions


def ensure_patched():
    """Run all three steps for both mediatypes. Writes the file
    once at the end if anything changed."""
    path = _favourites_path()
    if not path:
        _log('no favourites.xml found', level='INFO')
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    trakt_on = _trakt_connected()

    # Respect user deletions: if a personal tile that was present last run is
    # now gone WHILE its TMDB anchor tile is still here, the user deleted it
    # (not a skin-switch wipe, which also drops the anchor) -> remember that and
    # stop restoring it. Anchors-gone => treat as a wipe and don't mark removed.
    seen, removed = _load_state()
    present_now, anchors_now = _present(original)
    for key in seen:
        label = key.rsplit('_', 1)[0]
        if key not in present_now and label in anchors_now:
            removed.add(key)

    content = original
    all_actions = {}
    for media in MEDIA:
        content, actions = _process_one(content, media, trakt_on, removed)
        all_actions.update(actions)

    # Persist state: what's present after our pass, and the removed set.
    new_present, _ = _present(content)
    _save_state(new_present, removed)

    _log(
        'trakt_connected={0} | {1}'.format(
            trakt_on,
            ', '.join('{0}={1}'.format(k, v)
                      for k, v in all_actions.items())),
        level='INFO',
    )

    if content == original:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp, path)
        _log('wrote favourites.xml', level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
