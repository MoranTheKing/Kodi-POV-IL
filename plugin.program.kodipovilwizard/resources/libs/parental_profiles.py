"""Master-only setup and explicit per-title exceptions for children's profiles."""
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui

from resources.libs import profile_store
from resources.libs.patches import profile_age_guard as guard


def read(master):
    path = os.path.join(master, guard.POLICY_FILE)
    if not os.path.isfile(path):
        return {'schema': 1, 'children': {}}
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    if data.get('schema') != 1 or not isinstance(data.get('children'), dict):
        raise ValueError('Invalid profile policy')
    return data


def atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.povil-profile-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def prerequisites(master, target, children):
    profiles = profile_store.registered_profiles(master)
    key = guard.profile_key(master, profile_store.profile_path(master, target))
    # Every unrestricted profile, including master, needs a native code.
    if any(not p['protected'] for p in profiles if p['id'] == 0 or
           (p['id'] != target['id'] and guard.profile_key(master, profile_store.profile_path(master, p)) not in children)):
        return False
    return target['locksettings'] == 1 and target['lockfiles'] and target['lockaddonmanager']


def set_child(master, target, age):
    if type(age) is not int or not 0 <= age <= 17 or target['id'] == 0:
        raise ValueError('Invalid child age/profile')
    data = read(master)
    if not prerequisites(master, target, data['children']):
        raise ValueError('Native profile locks are incomplete')
    path = profile_store.profile_path(master, target)
    key = guard.profile_key(master, path)
    # Write fail-closed marker first; an interrupted setup cannot silently
    # restore unrestricted access. All changes target an inactive profile.
    profile_store.write_missing(path, guard.CHILD_MARKER, b'1')
    gui = ET.parse(os.path.join(path, 'guisettings.xml'))
    skin = gui.getroot().find("setting[@id='lookandfeel.skin']")
    if skin is None:
        skin = ET.SubElement(gui.getroot(), 'setting', {'id': 'lookandfeel.skin'})
    skin.text = 'skin.povil.nox'
    skin.attrib.pop('default', None)
    atomic_write(os.path.join(path, 'guisettings.xml'), ET.tostring(gui.getroot(), encoding='utf-8', xml_declaration=True))
    atomic_write(os.path.join(path, 'kodipovil.profile_gui_defaults.xml'),
                 ET.tostring(gui.getroot(), encoding='utf-8', xml_declaration=True))
    skin_path = os.path.join(path, 'addon_data', 'skin.povil.nox', 'settings.xml')
    skin_settings = ET.parse(skin_path).getroot() if os.path.isfile(skin_path) else ET.Element('settings')
    flag = skin_settings.find("setting[@id='POVILChild']")
    if flag is None:
        flag = ET.SubElement(skin_settings, 'setting', {'id': 'POVILChild', 'type': 'bool'})
    flag.text = 'true'
    atomic_write(skin_path, ET.tostring(skin_settings, encoding='utf-8', xml_declaration=True))
    previous = data['children'].get(key, {})
    data['children'][key] = dict(age=age, approved=previous.get('approved', {}))
    atomic_write(os.path.join(master, guard.POLICY_FILE), json.dumps(data, ensure_ascii=False).encode('utf-8'))


def copy_debrid(master, target):
    """Only after the parent elects to share these connections, no watch lists."""
    from resources.libs.profile_connections import copy_selected
    copy_selected(master, target, ['realdebrid', 'alldebrid', 'premiumize', 'torbox'])


def approve(master, profile, kind, ident, label):
    if kind not in ('movie', 'tv') or not str(ident).isdigit() or int(ident) < 1:
        raise ValueError('Invalid title identity')
    key = guard.profile_key(master, profile_store.profile_path(master, profile))
    data = read(master)
    policy = data['children'][key]
    policy['approved']['{}:{}'.format(kind, int(ident))] = str(label)[:250]
    atomic_write(os.path.join(master, guard.POLICY_FILE), json.dumps(data, ensure_ascii=False).encode('utf-8'))


def search_titles(kind, query):
    """Use POV's configured metadata client, without inventing a token setting."""
    import sys
    host = xbmcaddon.Addon('plugin.video.pov').getAddonInfo('path')
    library = os.path.join(host, 'resources', 'lib')
    if library not in sys.path:
        sys.path.insert(0, library)
    from indexers.tmdb_api import get_tmdb
    result = get_tmdb('/3/search/' + kind + '?' + urlencode({
        'query': query, 'language': 'he-IL', 'include_adult': 'false', 'page': 1}))
    if not isinstance(result, dict) or not isinstance(result.get('results'), list):
        raise ValueError('Title search failed')
    return [row for row in result['results'][:20]
            if isinstance(row, dict) and str(row.get('id', '')).isdigit() and int(row['id']) > 0]


def _approve_search(master, profile):
    kind_choice = xbmcgui.Dialog().select('אישור תוכן לפרופיל הילדים', ['סרט', 'סדרה'])
    if kind_choice < 0:
        return
    kind = ('movie', 'tv')[kind_choice]
    query = xbmcgui.Dialog().input('שם הסרט או הסדרה')
    if not query.strip():
        return
    try:
        rows = search_titles(kind, query)
    except Exception:
        xbmcgui.Dialog().ok('אישור תוכן', 'חיפוש המידע לא הצליח. אפשר לנסות שוב מאוחר יותר.')
        return
    labels = ['{} ({})'.format(r.get('title') or r.get('name'), (r.get('release_date') or r.get('first_air_date') or '')[:4]) for r in rows]
    if not rows:
        xbmcgui.Dialog().ok('אישור תוכן', 'לא נמצאו תוצאות.')
        return
    chosen = xbmcgui.Dialog().select('בחר את התוכן המדויק', labels)
    if chosen >= 0 and xbmcgui.Dialog().yesno('אישור הורה',
            'לאשר את {} לפרופיל {} גם אם אין דירוג מתאים?\nאישור סדרה חל גם על הפרקים שלה.'.format(labels[chosen], profile['name'])):
        approve(master, profile, kind, rows[chosen]['id'], labels[chosen])


def setup(profile=None):
    from resources.libs import build_profiles as profiles
    if not profiles._require_master():
        return
    master = profiles._master_path()
    if profile is None:
        targets = [p for p in profile_store.registered_profiles(master) if p['id'] != 0]
        if not targets:
            xbmcgui.Dialog().ok('בקרת הורים', 'הוסף קודם פרופיל חדש, ואז בחר כאן את גיל הילד.')
            return
        choice = xbmcgui.Dialog().select('איזה פרופיל לנהל?', [p['name'] for p in targets])
        if choice < 0:
            return
        profile = targets[choice]
    path = profile_store.profile_path(master, profile)
    key = guard.profile_key(master, path)
    data = read(master)
    actions = ['הגדרת גיל ומסך ילדים', 'אישור סרט או סדרה', 'ביטול אישור תוכן', 'שיתוף חיבורי Debrid מהראשי']
    action = xbmcgui.Dialog().select('בקרת הורים — ' + profile['name'], actions)
    if action < 0:
        return
    if action == 0:
        from resources.libs.patch_engine import PatchEngine
        import xbmcvfs
        PatchEngine().run()
        if not guard.host_integrity(xbmcvfs.translatePath('special://home/addons/')):
            xbmcgui.Dialog().ok('בקרת הורים', 'סינון התוכן אינו מוכן בגרסת ההרחבות המותקנת. השלם עדכון מהיר ונסה שוב.')
            return
        if not prerequisites(master, profile, data['children']):
            xbmcgui.Dialog().ok('הגנה על פרופיל ילדים',
                'בהגדרות הפרופילים של Kodi הגדר קוד למשתמש הראשי ולכל פרופיל רגיל.\n'
                'בפרופיל הילד נעל את כל ההגדרות, מנהל ההרחבות ומנהל הקבצים.\n'
                'לאחר השמירה חזור לבקרת ההורים כדי לבחור גיל. הקוד נשאר אצלך בלבד.')
            profiles._native_settings()
            return
        # Kodi's remote control can switch profiles independently of its
        # native PIN prompts. Explain and require local-only use for children.
        if profiles._rpc('Settings.GetSettingValue', {'setting': 'services.webserver'}).get('value'):
            xbmcgui.Dialog().ok('בקרת הורים', 'כבה בהגדרות Kodi את השליטה דרך HTTP לפני הפעלת פרופיל ילדים. שליטה מרחוק יכולה לעקוף את בחירת הפרופיל.')
            return
        age = xbmcgui.Dialog().select('גיל הילד — תוכן ללא דירוג דורש אישור הורה', [str(i) for i in range(18)],
                                      preselect=data['children'].get(key, {}).get('age', 7))
        if age < 0:
            return
        profiles._seed(profile)
        set_child(master, profile, age)
        xbmcgui.Dialog().ok('פרופיל הילדים מוכן', 'מסך הילדים והגבלת הגיל יופעלו בכניסה הבאה לפרופיל.\nPG ו־TV-PG נחשבים לגיל 10 בסינון הזה.')
    elif key not in data['children']:
        xbmcgui.Dialog().ok('בקרת הורים', 'הגדר קודם גיל לפרופיל הזה.')
    elif action == 1:
        _approve_search(master, profile)
    elif action == 2:
        approved = data['children'][key].get('approved', {})
        keys = list(approved)
        choice = xbmcgui.Dialog().select('בחר אישור לביטול', [approved[k] for k in keys])
        if choice >= 0:
            del approved[keys[choice]]
            atomic_write(os.path.join(master, guard.POLICY_FILE), json.dumps(data, ensure_ascii=False).encode('utf-8'))
    elif action == 3 and xbmcgui.Dialog().yesno('חיבורי Debrid',
            'להעתיק לפרופיל הזה את חיבורי Debrid של המשתמש הראשי? רשימות צפייה וחשבונות אחרים לא יועתקו.'):
        copy_debrid(master, profile)
        xbmcgui.Dialog().ok('חיבורי השירותים', 'החיבורים הועתקו. הם ייטענו בכניסה הבאה לפרופיל.')
