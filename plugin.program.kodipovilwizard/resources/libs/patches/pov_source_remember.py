# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_source_remember.py

import os
import json
import xbmc
import xbmcvfs
import xbmcgui
import xbmcaddon

_MARK = '[B][COLOR FFFFD700]«« נצפה לאחרונה »»[/COLOR][/B]  ·  '
_OLD_MARKS = (
    '⭐ ', '« נצפה לאחרונה » ',
    '[B][COLOR FFFFD700]« נצפה לאחרונה »[/COLOR][/B] · ',
    '[B][COLOR FFD700]«« נצפה לאחרונה »»[/COLOR][/B]  ·  '
)


def migrate_legacy_preference():
    """Carry the old subtitle-service opt-out into the Wizard once.

    The new Wizard setting defaults to true. Without this migration a user
    who deliberately disabled source memory in the old service would have it
    silently re-enabled by the modular move.
    """
    try:
        wizard = xbmcaddon.Addon('plugin.program.kodipovilwizard')
        if wizard.getSetting('_pov_remember_migrated_v1') == 'true':
            return 'already_migrated'
        try:
            service = xbmcaddon.Addon('service.subtitles.kodipovilai')
            choice = (service.getSetting('remember_source') or '').strip().lower()
        except Exception:
            choice = ''
        if choice not in ('true', 'false'):
            # Kodi can refuse xbmcaddon.Addon(id) after the old service is
            # disabled for a safe two-boot swap. Its existing profile remains
            # on disk, so read only this setting directly before retiring it.
            try:
                import xml.etree.ElementTree as ET
                path = xbmcvfs.translatePath(
                    'special://profile/addon_data/'
                    'service.subtitles.kodipovilai/settings.xml')
                root = ET.parse(path).getroot()
                node = next((item for item in root.findall('setting')
                             if item.get('id') == 'remember_source'), None)
                choice = ((node.text or node.get('value') or '').strip().lower()
                          if node is not None else '')
            except Exception:
                choice = ''
        if choice not in ('true', 'false'):
            # Do not burn the one-time marker until an actual legacy choice
            # was read; a temporarily disabled or unavailable service can be
            # retried on the next boot.
            return 'no_legacy_choice'
        wizard.setSetting('pov_remember_source', choice)
        wizard.setSetting('_pov_remember_migrated_v1', 'true')
        return 'migrated'
    except Exception as exc:
        _log('Legacy preference migration failed: ' + str(exc), xbmc.LOGWARNING)
        return 'failed'

def _log(msg, level=xbmc.LOGINFO):
    xbmc.log('[Wizard: Source Remember] ' + msg, level)

def _enabled():
    try:
        # Falls back to old subtitle setting if wizard setting is absent
        wiz = xbmcaddon.Addon('plugin.program.kodipovilwizard')
        choice = (wiz.getSetting('pov_remember_source') or '').strip().lower()
        if choice in ('true', 'false'):
            return choice == 'true'
        sub = xbmcaddon.Addon('service.subtitles.kodipovilai')
        return (sub.getSetting('remember_source') or '').strip().lower() == 'true'
    except Exception:
        return False

def _dir():
    return xbmcvfs.translatePath(
        'special://profile/addon_data/plugin.program.kodipovilwizard/source_memory/'
    )

def _key(sources_self):
    meta = getattr(sources_self, 'meta', None) or {}
    media_id = str(getattr(sources_self, 'tmdb_id', '') or meta.get('imdb_id') or '')
    media_type = getattr(sources_self, 'media_type', '') or 'movie'
    if not media_id:
        return None
    season = getattr(sources_self, 'season', '') or 0
    episode = getattr(sources_self, 'episode', '') or 0
    return '{0}_{1}_s{2}_e{3}'.format(media_type, media_id, season, episode)

def _norm(x):
    return (x or '').strip().lower()

def _get_record(sources_self):
    key = _key(sources_self)
    if not key:
        return None
    path = os.path.join(_dir(), key + '.json')
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except Exception as e:
        _log('Error reading record: ' + str(e), xbmc.LOGWARNING)
        return None

def _match_index(results, rec):
    rhash = _norm(rec.get('hash'))
    if rhash:
        for i, it in enumerate(results):
            if _norm(it.get('hash')) == rhash:
                return i
    rq = _norm(rec.get('quality'))
    rprov = _norm(rec.get('provider'))
    if rq and rprov:
        for i, it in enumerate(results):
            if 'Uncached' in (it.get('cache_provider') or ''):
                continue
            if (_norm(it.get('quality')) == rq and
                _norm(it.get('scrape_provider') or it.get('provider')) == rprov):
                return i
    return None

_PROVIDER_NAMES = {
    'torbox': 'TorBox', 'tb': 'TorBox', 'real-debrid': 'Real-Debrid', 'realdebrid': 'Real-Debrid', 'rd': 'Real-Debrid',
    'premiumize.me': 'Premiumize', 'premiumize': 'Premiumize', 'pm': 'Premiumize',
    'alldebrid': 'AllDebrid', 'ad': 'AllDebrid', 'offcloud': 'Offcloud', 'oc': 'Offcloud',
    'easydebrid': 'EasyDebrid', 'ed': 'EasyDebrid', 'easynews': 'Easynews', 'debrid-link': 'Debrid-Link',
}


def provider_label(item):
    """The debrid service a source plays from, as its users write it; '' when the source names none."""
    try:
        raw = str(item.get('debrid') or item.get('cache_provider') or '').strip()
    except Exception:
        return ''
    if raw.lower().startswith('uncached'):
        raw = raw[len('uncached'):].strip()
    if not raw or len(raw) > 24:
        return ''
    return _PROVIDER_NAMES.get(raw.lower(), raw)


def size_label(item):
    """The size of the file a source plays, as the player's pill says it: '12.4 GB', '8 GB', '850 MB'; '' when the
    source names none. POV keeps a source's size in gigabytes -- for a pack, its share for one episode, the figure
    its own list of sources shows -- and some sources carry only the words POV wrote of it ('12.40 GB')."""
    size = 0.0
    try:
        size = float(item.get('size') or 0)
    except Exception:
        size = 0.0
    if not size > 0:
        try:
            words = str(item.get('size_label') or '').replace(',', '.').split()
            size = float(words[0]) / (1024.0 if len(words) > 1 and words[1].upper().startswith('M') else 1.0)
        except Exception:
            size = 0.0
    if not 0.001 <= size < 2000:
        return ''
    if size < 0.9995:
        return '%d MB' % int(size * 1024 + 0.5)
    text = '%.1f' % size
    return (text[:-2] if text.endswith('.0') else text) + ' GB'


def run_capture(sources_self, item, link):
    """
    Hook 1: Stashes window properties for external modules and saves the selected source.
    """
    # 1. Stash Window Properties
    try:
        win = xbmcgui.Window(10000)
        name = item.get('name', '') or item.get('URLName', '') or ''
        win.setProperty('subs.player_filename', name)
        win.setProperty('pov_picked_source_name', name)
        win.setProperty('pov_picked_source_url', link or '')
        # Where the stream comes from, for the player's details line (Onyx).
        # Tied to this source's name: another add-on's pick replaces the name
        # and the skin then shows no provider rather than a stale one.
        provider = provider_label(item)
        win.setProperty('povil_osd_provider', provider)
        win.setProperty('povil_osd_provider_for', name if provider else '')
        # ... and the file's size, a pill beside it (a viewer, Nov 2026: "the file size among the chips")
        size = size_label(item)
        win.setProperty('povil_osd_size', size)
        win.setProperty('povil_osd_size_for', name if size else '')
    except Exception as e:
        _log('Failed setting Window properties: ' + str(e), xbmc.LOGWARNING)

    # 2. Capture Source Memory
    if not _enabled():
        return
    try:
        key = _key(sources_self)
        if not key:
            return
        rec = {
            'name': item.get('name', ''),
            'hash': item.get('hash', ''),
            'quality': item.get('quality', ''),
            'provider': item.get('scrape_provider') or item.get('provider', ''),
            'debrid': item.get('debrid', ''),
            'release_title': item.get('release_title', ''),
            'size': item.get('size', 0)
        }
        d = _dir()
        if not os.path.isdir(d):
            os.makedirs(d)

        file_path = os.path.join(d, key + '.json')
        tmp = file_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False, indent=2))
        os.replace(tmp, file_path)
        _log('Captured picked source successfully: ' + key)
    except Exception as e:
        _log('Capture error: ' + str(e), xbmc.LOGERROR)

def run_reorder(sources_self, results):
    """
    Hook 2: Reorders the results list, applying markers and pinning the remembered source.
    """
    if not _enabled():
        return False
    try:
        rec = _get_record(sources_self)
        if not rec:
            return False

        idx = _match_index(results, rec)
        if idx is None:
            return False

        # For should_play(): the very release that was played (the same torrent), or only one like it
        # (same quality from the same scraper)? The second is worth the first row, not a play unasked.
        try:
            rhash = _norm(rec.get('hash'))
            sources_self._povil_same_release = bool(rhash) and _norm(results[idx].get('hash')) == rhash
        except Exception:
            pass

        item = results.pop(idx)

        # Apply the marker to display_name and fallback URLName
        try:
            fld = 'display_name' if item.get('display_name') else 'URLName'
            nm = item.get(fld) or ''
            for _m in (_MARK,) + _OLD_MARKS:
                if nm.startswith(_m):
                    nm = nm[len(_m):]
            if nm:
                item[fld] = _MARK + nm
        except Exception:
            pass

        # Protect from downstream sorting processes in POV
        item['_pin_top'] = True

        results.insert(0, item)
        _log('Remembered source moved to top, marked, and pinned.')
        return True
    except Exception as e:
        _log('Reorder error: ' + str(e), xbmc.LOGERROR)
        return False


# --------------------------------------------------------------------------
# "Play the last source at once" -- the viewer's own option, off unless chosen
# (asked for through the owner, Nov 2026: "click the poster and it plays what
# was played before", "as a choice, not on by itself", "in POV and in Umbrella").
# The source a title played is remembered above; with the option on, the next
# click on that title plays the same source instead of showing the list. The
# list is still one press away: "change source" in the player, and the add-ons'
# own "select source" entries, ask for it by name and always get it.

def play_remembered():
    try:
        wizard = xbmcaddon.Addon('plugin.program.kodipovilwizard')
        return (wizard.getSetting('pov_play_remembered') or '').strip().lower() == 'true'
    except Exception:
        return False


def should_play(sources_self):
    """POV, right after run_reorder() put the remembered source first: play it, or show the list?"""
    try:
        if not (_enabled() and play_remembered()):
            return False
        # only the very release that was played; a source that is merely like it (another cut, dub
        # or encode of the same quality from the same scraper) is first in the list, and the list shows
        if not getattr(sources_self, '_povil_same_release', False):
            return False
        # the list was asked for by name: POV sets this parameter only then
        return 'autoplay' not in (getattr(sources_self, 'params', None) or {})
    except Exception:
        return False


def _umbrella_key(ids):
    """The same file name POV's capture writes, so one memory serves both add-ons."""
    tmdb = str((ids or {}).get('tmdb') or '').strip()
    if not tmdb.isdigit() or tmdb == '0':
        return None
    season, episode = (ids or {}).get('season'), (ids or {}).get('episode')
    if str(episode).strip().isdigit() and str(season).strip().isdigit():
        return 'movie_{0}_s{1}_e{2}'.format(tmdb, int(season), int(episode))  # POV's own name for an episode's file
    return 'movie_{0}_s0_e0'.format(tmdb)


def _umbrella_cached(item):
    return isinstance(item, dict) and 'uncached' not in str(item.get('source') or '').lower()


def umbrella_capture(ids, item):
    """Umbrella's playItem(), when the picked source resolved: remember it for this title."""
    try:
        if not _enabled() or not _umbrella_cached(item):
            return False
        key = _umbrella_key(ids)
        if not key:
            return False
        rec = {'name': item.get('name', ''), 'hash': item.get('hash', ''), 'quality': item.get('quality', ''),
               'provider': item.get('provider', ''), 'debrid': item.get('debrid', ''),
               'release_title': item.get('name', ''), 'size': item.get('size', 0)}
        folder = _dir()
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, key + '.json')
        with open(path + '.tmp', 'w', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False, indent=2))
        os.replace(path + '.tmp', path)
        return True
    except Exception as e:
        _log('Umbrella capture error: ' + str(e), xbmc.LOGWARNING)
        return False


def umbrella_pick(ids, items):
    """Umbrella's play(), before its source list: [the remembered source] when the option is on and
    this scrape returned it, else None (the list is shown as usual)."""
    try:
        if not (_enabled() and play_remembered()):
            return None
        key = _umbrella_key(ids)
        if not key:
            return None
        path = os.path.join(_dir(), key + '.json')
        if not os.path.isfile(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            rec = json.loads(f.read())
        candidates = [i for i in (items or []) if _umbrella_cached(i) and not i.get('cloud_folder')]
        # only the very release that was played (the same torrent): a source that is merely like it
        # could be another cut, dub or encode, and this plays without asking
        rhash = _norm(rec.get('hash'))
        if rhash:
            for item in candidates:
                if _norm(item.get('hash')) == rhash:
                    return [item]
        return None
    except Exception as e:
        _log('Umbrella pick error: ' + str(e), xbmc.LOGWARNING)
        return None


def umbrella_published(item, url):
    """The remembered source started without Umbrella's list: say what plays, as its list path does."""
    try:
        name = (item or {}).get('name') or ''
        if name:
            win = xbmcgui.Window(10000)
            win.setProperty('subs.player_filename', name)
            win.setProperty('pov_picked_source_name', name)
            win.setProperty('pov_picked_source_url', url or '')
    except Exception:
        pass
