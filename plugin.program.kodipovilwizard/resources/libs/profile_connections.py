"""Explicit account inheritance into an inactive, registered profile."""
import os
import xml.etree.ElementTree as ET

from resources.libs import profile_store

# Copy account fields, not databases, watched state or unrelated preferences.
GROUPS = (
    ('realdebrid', 'Real-Debrid', ('rd.', 'realdebrid.')),
    ('alldebrid', 'AllDebrid', ('ad.', 'alldebrid.')),
    ('premiumize', 'Premiumize', ('pm.', 'premiumize.')),
    ('torbox', 'TorBox', ('tb.', 'torbox.')),
    ('trakt', 'Trakt — חשבון ורשימות', ('trakt.', 'trakt_user')),
    ('mdblist', 'MDBList — חשבון ורשימות', ('mdblist.', 'mdblist_user')),
    ('tmdb', 'TMDB — חשבון ורשימות', ('tmdb.',)),
)
ADDONS = ('plugin.video.pov', 'plugin.video.umbrella', 'script.module.acctmgr')


def fields(master, key):
    prefixes = next(row[2] for row in GROUPS if row[0] == key)
    result = {}
    for addon in ADDONS:
        path = os.path.join(master, 'addon_data', addon, 'settings.xml')
        if not os.path.isfile(path):
            continue
        rows = [row for row in ET.parse(path).getroot().findall('setting')
                if row.get('id', '').startswith(prefixes)]
        # Non-empty credentials prove a usable account, never an enable flag.
        connected = any((row.text or '').strip() not in ('', 'false', '0', 'true')
                        and any(word in row.get('id', '').lower()
                                for word in ('token', 'auth', 'account_id', 'acct_id', 'apikey', 'session_id'))
                        for row in rows)
        if connected:
            result[addon] = rows
    return result


def available(master):
    return [(key, label) for key, label, _prefixes in GROUPS if fields(master, key)]


def copy_selected(master, target, selected):
    from resources.libs.parental_profiles import atomic_write
    dest = profile_store.profile_path(master, target)
    if target['id'] == 0:
        raise ValueError('Accounts can only be copied to a secondary profile')
    keys = {row[0] for row in GROUPS}
    if not set(selected).issubset(keys):
        raise ValueError('Unknown connection group')
    for key in selected:
        for addon, rows in fields(master, key).items():
            path = os.path.join(dest, 'addon_data', addon, 'settings.xml')
            settings = ET.parse(path).getroot() if os.path.isfile(path) else ET.Element('settings', {'version': '2'})
            for row in rows:
                ident = row.get('id')
                old = settings.find("setting[@id='{}']".format(ident))
                if old is not None:
                    settings.remove(old)
                settings.append(ET.fromstring(ET.tostring(row)))
            atomic_write(path, ET.tostring(settings, encoding='utf-8', xml_declaration=True))


def choose(master):
    import xbmcgui
    rows = available(master)
    if not rows:
        return []
    choice = xbmcgui.Dialog().multiselect(
        'אילו חיבורים להעתיק? חשבונות המעקב ישתפו את אותן רשימות',
        [label for _key, label in rows],
        preselect=[i for i, (key, _label) in enumerate(rows) if key in {v[0] for v in GROUPS[:4]}])
    return None if choice is None else [rows[i][0] for i in choice]
