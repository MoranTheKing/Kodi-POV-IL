"""Put the build's Kodi settings back when Kodi has lost them.

Field report (28 Oct 2026, Android, Kodi 21.3): Kodi came up in English, with
Estuary and a 12-hour clock -- Kodi's own defaults -- on a build installed in
Hebrew with NOX. Switching back to NOX by hand still left English labels,
because the language and region had reset too, and with them the build's
subtitle settings (MoranSubs as the default subtitle service, Hebrew subtitle
language). The session in which guisettings.xml reset left no log behind.

restore() reads the build's guisettings.xml from the Wizard's own copy of the
config pack (resources/bootstrap/config.zip -- the seed a fresh install
applies), drops the ids the pack's policy keeps per device (services,
display resolution ...) and the audio output (a receiver may need its own),
applies the rest through Kodi's Settings API (fresh_install.apply_live_settings)
and has Kodi save them at once: in Kodi 21 the API changes memory only, and an
Android device may kill Kodi before it exits. The skin is offered afterwards,
never switched without asking.

offer_after_reset() runs at start-up: when Kodi's language is back at Kodi's
default and its region is no longer the build's, on a build whose seed is not
English, it asks once. A "no" is remembered until the language changes again.
"""
import json
import os
import zipfile
import xml.etree.ElementTree as ET

import xbmc
import xbmcgui

from resources.libs.common.config import CONFIG
from resources.libs.common import logging

KODI_DEFAULT_LANGUAGE = 'resource.language.en_gb'
DISMISSED = 'gui_reset_dismissed'
TITLE = 'שחזור הגדרות קודי של הבילד'


def _rpc(method, params):
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(
        {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    return reply.get('result')


def _setting(key):
    try:
        return (_rpc('Settings.GetSettingValue', {'setting': key}) or {}).get('value')
    except Exception:
        return None


def build_defaults():
    """The build's guisettings <settings> root with the per-device ids removed,
    or None when the Wizard's config pack cannot be read."""
    path = os.path.join(CONFIG.ADDON_PATH, 'resources', 'bootstrap', 'config.zip')
    try:
        with zipfile.ZipFile(path) as pack:
            policy = json.loads(pack.read('config_policy.json').decode('utf-8'))
            root = ET.fromstring(pack.read('guisettings.xml'))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as err:
        logging.log('[GUI Repair] build settings unavailable: {0}'.format(err), level=xbmc.LOGWARNING)
        return None
    spec = next((s for s in policy.get('files', []) if s.get('src') == 'guisettings.xml'), {})
    excluded = set(spec.get('exclude_ids', []))
    for node in list(root):
        # The audio output stays the device's: Fixed for an AV receiver, say.
        if node.get('id') in excluded or node.get('id', '').startswith('audiooutput.'):
            root.remove(node)
    # The language last: changing it reloads Kodi's GUI, and settings read
    # while that runs were skipped (QA Kodi: "2 changed" of 6).
    for node in root.findall("setting[@id='locale.language']"):
        root.remove(node)
        root.append(node)
    return root


def looks_reset(defaults=None):
    """Kodi's language is back at Kodi's default AND its region is no longer
    the build's: what a reset guisettings.xml looks like. A user who picked
    English on purpose and kept the build's region is not asked."""
    defaults = build_defaults() if defaults is None else defaults
    if defaults is None:
        return False
    build_language = defaults.findtext("setting[@id='locale.language']")
    build_country = defaults.findtext("setting[@id='locale.country']")
    if not build_language or build_language == KODI_DEFAULT_LANGUAGE or not build_country:
        return False
    return (_setting('locale.language') == KODI_DEFAULT_LANGUAGE and
            _setting('locale.country') != build_country)


def _offer_skin(defaults):
    """After the settings: offer the skin the build uses, or the one this
    profile last used when that is one of the build's (Estuary excluded: it is
    also what a reset leaves behind, and the memory may have recorded it)."""
    from resources.libs import build_skin
    target = defaults.findtext("setting[@id='lookandfeel.skin']") or 'skin.povil.nox'
    try:
        from resources.libs import host_patch_watch
        remembered = host_patch_watch.read_skin_memory()[0]
        if remembered in build_skin.SKINS and remembered != 'skin.estuary':
            target = remembered
    except Exception:
        pass
    if (xbmc.getSkinDir() == target or target not in build_skin.SKINS or
            not xbmc.getCondVisibility('System.HasAddon({0})'.format(target))):
        return
    names = {'skin.povil.nox': 'NOX', 'skin.fentastic': 'FENtastic',
             'skin.estuary': 'Estuary', 'skin.arctic.fuse.3': 'Arctic Fuse 3',
             'skin.povil.onyx': 'Onyx'}
    if xbmcgui.Dialog().yesno(TITLE, 'לחזור גם לסקין {0}?'.format(names.get(target, target)),
                              nolabel='לא', yeslabel='כן'):
        if not build_skin.activate(target):
            logging.log('[GUI Repair] skin {0} not activated'.format(target), level=xbmc.LOGWARNING)


def restore(ask=True):
    """Apply the build's Kodi settings. Returns True when they were applied."""
    defaults = build_defaults()
    if defaults is None:
        xbmcgui.Dialog().ok(TITLE, 'לא נמצאו הגדרות הבילד בוויזארד. נסו לעדכן את הוויזארד ולנסות שוב.')
        return False
    if ask and not xbmcgui.Dialog().yesno(
            TITLE,
            'ההגדרות של קודי יחזרו להגדרות הבילד: שפה ואזור, כתוביות, ניגון ועדכוני הרחבות.'
            '[CR]שינויים שעשיתם בעצמכם בהגדרות האלה יוחלפו.',
            nolabel='ביטול', yeslabel='שחזור'):
        return False
    from resources.libs import build_skin, fresh_install
    result = fresh_install.apply_live_settings(defaults)
    if result is None:
        return False
    changed, rejected = result
    saved = build_skin.persist_live_settings()
    logging.log('[GUI Repair] build settings applied: {0} changed, rejected: {1}, saved: {2}'.format(
        changed, ', '.join(rejected) or 'none', saved), level=xbmc.LOGINFO)
    CONFIG.set_setting(DISMISSED, '')
    _offer_skin(defaults)
    # A skin switch saves too: check again before warning.
    saved = saved or build_skin.persist_live_settings()
    if saved:
        xbmcgui.Dialog().notification(TITLE, 'הגדרות הבילד שוחזרו', xbmcgui.NOTIFICATION_INFO, 4000)
    else:
        # In memory only: an Android kill would lose them again.
        xbmcgui.Dialog().ok(TITLE, 'הגדרות הבילד שוחזרו, אבל קודי עוד לא שמר אותן.'
                                   '[CR]כדי שיישמרו, צאו מקודי דרך תפריט הכיבוי שלו.')
    return True


def offer_after_reset():
    """Start-up check (never during playback): ask once when Kodi's settings
    look reset to Kodi's defaults."""
    try:
        if not CONFIG.get_setting('buildname') or xbmc.Player().isPlayingVideo():
            return False
        defaults = build_defaults()
        if defaults is None:
            return False
        if not looks_reset(defaults):
            if _setting('locale.language') != KODI_DEFAULT_LANGUAGE and CONFIG.get_setting(DISMISSED):
                CONFIG.set_setting(DISMISSED, '')
            return False
        if CONFIG.get_setting(DISMISSED) == 'true':
            return False
        if xbmcgui.Dialog().yesno(
                TITLE,
                'נראה שההגדרות של קודי חזרו לברירת המחדל (אנגלית, שעון 12 שעות).'
                '[CR]לשחזר את הגדרות הבילד: שפה ואזור, כתוביות, ניגון ועדכוני הרחבות?',
                nolabel='לא', yeslabel='שחזור'):
            return restore(ask=False)
        CONFIG.set_setting(DISMISSED, 'true')
    except Exception as err:
        logging.log('[GUI Repair] start-up check failed: {0}'.format(err), level=xbmc.LOGWARNING)
    return False
