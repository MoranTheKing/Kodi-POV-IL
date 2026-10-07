"""Profile-local age policy for directory rows and host playback boundaries.

Adult profiles pass through unchanged. Unknown classifications fail closed in
children's profiles; only master-authored title approvals can override them.
This is parental filtering within Kodi, not protection against filesystem or
remote-control access to Kodi itself.
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs

POLICY_FILE = 'povil_profiles.json'
CHILD_MARKER = 'povil.child-profile'
_cache = {}
CLASSIFICATIONS = {'G': 0, 'TV-Y': 0, 'TV-G': 0, 'TV-Y7': 7,
                   'TV-Y7-FV': 7, 'PG': 10, 'TV-PG': 10, 'PG-13': 13,
                   'TV-14': 14, 'R': 17, 'NC-17': 18, 'TV-MA': 18,
                   'U': 0, '12A': 12, '12': 12, '15': 15, '18': 18}


def required_age(value):
    """Classification strings only; never infer age from vote scores/genres."""
    if not isinstance(value, str):
        return None
    value = value.strip().upper()
    value = re.sub(r'^RATED\s+', '', value)
    value = re.sub(r'^(?:US|USA|GB|UK|IL|ISR)\s*[:\-]\s*', '', value)
    return CLASSIFICATIONS.get(value)


def title_key(meta):
    kind = meta.get('mediatype') or meta.get('media_type') or meta.get('type')
    kind = 'tv' if kind in ('tv', 'tvshow', 'season', 'episode') else kind
    ident = meta.get('tmdb_id') or meta.get('tmdb') or (meta.get('uniqueid') or {}).get('tmdb')
    if kind not in ('movie', 'tv') or not str(ident or '').isdigit() or int(ident) < 1:
        return None
    return '{}:{}'.format(kind, int(ident))


def allows(policy, meta):
    if policy is None:
        return True
    if not isinstance(policy, dict) or policy.get('blocked'):
        return False
    key = title_key(meta)
    if key and key in policy.get('approved', {}):
        return True
    # TMDB's explicit adult flag cannot be neutralized by a stray low MPAA.
    if meta.get('adult') in (True, 'true', 'True', 1):
        return False
    age = required_age(meta.get('mpaa') or meta.get('certification'))
    limit = policy.get('age')
    return (age is not None and type(limit) is int and 0 <= limit <= 17 and age <= limit)


def profile_key(master, active):
    master, active = os.path.realpath(master), os.path.realpath(active)
    if master == active:
        return None
    if os.path.commonpath([master, active]) != master:
        raise ValueError('Unsupported profile location')
    return os.path.relpath(active, master).replace('\\', '/')


def policy_for(master, active):
    """Read the current profile on every boundary, including reused invokers."""
    key = profile_key(master, active)
    if key is None:
        return None
    marker = os.path.isfile(os.path.join(active, CHILD_MARKER))
    path = os.path.join(master, POLICY_FILE)
    if not os.path.isfile(path):
        return {'blocked': True} if marker else None
    try:
        stat = os.stat(path)
        cache_key = (path, stat.st_mtime_ns, stat.st_size)
        data = _cache.get(cache_key)
        if data is None:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
            if data.get('schema') != 1 or not isinstance(data.get('children'), dict):
                raise ValueError('Invalid profile policy')
            _cache.clear()
            _cache[cache_key] = data
        policy = data['children'].get(key)
        if policy is not None and (not isinstance(policy, dict) or
                type(policy.get('age')) is not int or not 0 <= policy['age'] <= 17 or
                not isinstance(policy.get('approved'), dict)):
            return {'blocked': True}
        if policy is not None and not locks_ready(master, active, data['children']):
            return {'blocked': True}
        return policy if policy is not None else ({'blocked': True} if marker else None)
    except (OSError, ValueError, TypeError, AttributeError):
        # A broken central policy must not turn a child profile into an adult.
        return {'blocked': True}


def locks_ready(master, active, children):
    try:
        profiles = ET.parse(os.path.join(master, 'profiles.xml')).getroot().findall('profile')
        found = False
        master_found = False
        for row in profiles:
            ident = row.findtext('id')
            if ident == '0':
                master_found = True
                if int(row.findtext('lockmode', '0')) <= 0 or row.findtext('lockcode', '') in ('', '-'):
                    return False
                continue
            path = os.path.realpath(os.path.join(master, row.findtext('directory', '')))
            key = profile_key(master, path)
            if path == os.path.realpath(active):
                found = True
                if (row.findtext('locksettings') != '1' or row.findtext('lockfiles') != 'true' or
                        row.findtext('lockaddonmanager') != 'true'):
                    return False
            elif key not in children:
                if int(row.findtext('lockmode', '0')) <= 0 or row.findtext('lockcode', '') in ('', '-'):
                    return False
        return found and master_found
    except (OSError, ValueError, ET.ParseError):
        return False


def host_integrity(addons):
    required = {
        'plugin.video.pov': [('resources/lib/entry.py', 'WIZARD_POV_PROFILE_DIRECTORY_v1'),
                             ('resources/lib/entry.py', 'WIZARD_POV_PROFILE_ROUTE_v1'),
                             ('resources/lib/modules/player.py', 'WIZARD_POV_PROFILE_PLAY_v1'),
                             ('resources/lib/menus/movies.py', 'WIZARD_POV_PROFILE_MOVIE_META_v1'),
                             ('resources/lib/menus/tvshows.py', 'WIZARD_POV_PROFILE_TV_META_v1'),
                             ('resources/lib/indexers/metadata.py', 'WIZARD_POV_PROFILE_EPISODE_META_v1')],
        'plugin.video.umbrella': [('resources/lib/modules/control.py', 'WIZARD_UMBRELLA_PROFILE_DIRECTORY_v1'),
                                  ('resources/lib/modules/router.py', 'WIZARD_UMBRELLA_PROFILE_ROUTE_v1'),
                                  ('resources/lib/modules/player.py', 'WIZARD_UMBRELLA_PROFILE_PLAY_v1'),
                                  ('resources/lib/modules/control.py', 'WIZARD_UMBRELLA_PROFILE_META_v1')],
        'plugin.video.idanplus': [('default.py', 'WIZARD_IDANPLUS_CHILD_SOURCE_v1')]}
    for addon, rows in required.items():
        directory = os.path.join(addons, addon)
        if not os.path.isdir(directory):
            if addon == 'plugin.video.pov':
                return False
            continue
        for relative, marker in rows:
            try:
                with open(os.path.join(directory, relative), encoding='utf-8') as fh:
                    if marker not in fh.read():
                        return False
            except (OSError, UnicodeError):
                return False
    return True


def active_policy():
    import xbmcvfs
    try:
        policy = policy_for(xbmcvfs.translatePath('special://masterprofile/'),
                            xbmcvfs.translatePath('special://profile/'))
        if policy is None:
            import xbmc
            if xbmc.getCondVisibility('Skin.HasSetting(POVILChild)'):
                return {'blocked': True}
        return policy
    except (OSError, ValueError):
        return {'blocked': True} if os.path.isfile(os.path.join(
            xbmcvfs.translatePath('special://profile/'), CHILD_MARKER)) else None


def item_meta(item):
    tag = item.getVideoInfoTag()
    # Kodi 21 has setMpaa but no MPAA getter. Capture the host's metadata at
    # its normal item-construction boundary instead of inventing a SDK call.
    captured = json.loads(item.getProperty('POVIL.AgeMetadata') or '{}')
    return dict(captured, mediatype=tag.getMediaType() or captured.get('mediatype'),
                tmdb_id=tag.getUniqueID('tmdb') or captured.get('tmdb_id'))


def stamp_item(item, meta):
    # Capture classification without consulting Kodi's GUI for every row.
    # The directory/playback boundary still reads the current policy. Keeping
    # metadata even for an adult-built row also covers a profile change before
    # publication; this is not a cached decision to allow that row.
    meta = meta or {}
    values = {key: meta.get(key) for key in ('mpaa', 'certification', 'mediatype', 'adult')}
    values['tmdb_id'] = meta.get('tmdb_id') or meta.get('tmdb')
    item.setProperty('POVIL.AgeMetadata', json.dumps(values))


def visible(item, folder, policy, url=''):
    if policy is None:
        return True
    if policy.get('blocked'):
        return False
    try:
        meta = item_meta(item)
        # Navigation folders have no media classification. Movie/show/season
        # folders ARE content and must be filtered even when not playable.
        params = parse_qs(urlparse(url).query)
        content_identity = bool(meta.get('tmdb_id') or params.get('tmdb_id') or
                                params.get('tmdb') or params.get('imdb') or
                                meta.get('mpaa'))
        if folder and not content_identity and meta['mediatype'] not in ('movie', 'tvshow', 'season', 'episode'):
            return True
        return allows(policy, meta)
    except Exception:
        return False


def install_directory_guard():
    """Install before host aliases are captured; wrappers reread active policy."""
    import xbmcplugin
    if getattr(xbmcplugin.addDirectoryItem, '_povil_age_guard', False):
        return
    original, originals = xbmcplugin.addDirectoryItem, xbmcplugin.addDirectoryItems
    def single(handle, url, listitem, isFolder=False, totalItems=0):
        if not visible(listitem, isFolder, active_policy(), url):
            return True
        return original(handle, url, listitem, isFolder, totalItems)
    def batch(handle, items, totalItems=0):
        policy = active_policy()
        if policy is None:
            return originals(handle, items, totalItems)
        safe = [row for row in items if visible(row[1], row[2] if len(row) > 2 else False, policy, row[0])]
        return originals(handle, safe, len(safe))
    single._povil_age_guard = True
    xbmcplugin.addDirectoryItem, xbmcplugin.addDirectoryItems = single, batch


def permit_play(meta, host, url=''):
    policy = active_policy()
    if policy is None:
        return True
    if not allows(policy, meta):
        import xbmcgui
        xbmcgui.Dialog().notification('פרופיל ילדים', 'התוכן חסום לפי הגיל או שאין דירוג מזוהה.', time=4000)
        return False
    import xbmcgui
    import xbmcvfs
    # A session-scoped receipt also lets the build service reject playback
    # from unsupported add-ons. URLs and credentials are never persisted.
    import time
    import hashlib
    xbmcgui.Window(10000).setProperty('POVIL.ChildPlay', json.dumps({
        'profile': xbmcvfs.translatePath('special://profile/'),
        'host': host, 'key': title_key(meta), 'mpaa': meta.get('mpaa') or meta.get('certification', ''),
        'url_hash': hashlib.sha256(str(url).split('|')[0].encode('utf-8')).hexdigest(),
        'issued': time.time()}))
    return True


def route_allowed(params, host):
    if active_policy() is None:
        return True
    mode = params.get('mode', '') if host == 'pov' else params.get('action', '')
    # Child profiles cannot open account/settings editors or cloud/file
    # browsers through supported host routes. Content routes remain usable.
    if host == 'pov':
        deny = mode.startswith(('menu_editor.', 'premiumize.', 'offcloud.', 'torbox.',
                                'real_debrid.', 'alldebrid.', 'easynews.')) or mode in (
            'open_settings', 'myservices', 'toggle_provider', 'media_play', 'downloader')
    else:
        deny = any(term in mode.lower() for term in ('settings', 'authorize', 'debrid', 'download', 'cloud', 'account'))
    if deny:
        import xbmcgui
        xbmcgui.Dialog().notification('פרופיל ילדים', 'ניהול שירותים וקבצים זמין במשתמש הראשי.', time=3000)
        import sys, xbmcplugin
        try:
            handle = int(sys.argv[1])
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle, succeeded=False)
        except (IndexError, ValueError):
            pass
    return not deny


def unclassified_source_allowed():
    """Live broadcasts/catalogs without classifications cannot be age-filtered."""
    if active_policy() is None:
        return True
    import sys
    import xbmcgui
    import xbmcplugin
    xbmcgui.Dialog().notification('פרופיל ילדים', 'עידן פלוס ושידורים ללא דירוג גיל חסומים בפרופיל ילדים.', time=4000)
    try:
        handle = int(sys.argv[1])
        if handle >= 0:
            xbmcplugin.endOfDirectory(handle, succeeded=False)
    except (ValueError, IndexError):
        pass
    return False
