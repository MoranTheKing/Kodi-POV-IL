# Build-only UI guardrails for Kodi POV IL.
#
# The build home menu should not expose Kodi's raw "Favourites" entry as
# the user's home button. Keep the button visible, but label it like the
# rest of the Hebrew build sidemenu.

import os
import xml.etree.ElementTree as ET

from resources.lib import kodi_utils

try:
    import xbmc
    import xbmcvfs
except ImportError:
    xbmc = None
    xbmcvfs = None


FENTASTIC_SETTINGS = 'special://profile/addon_data/skin.fentastic/settings.xml'
FENTASTIC_HOME_XML = 'special://home/addons/skin.fentastic/xml/Home.xml'
FENTASTIC_HE_STRINGS = (
    'special://home/addons/skin.fentastic/language/resource.language.he_il/strings.po'
)

HE_STRINGS = {
    '#31072': ('Power Options', 'אפשרויות כיבוי'),
    '#700050': ('Open POV Settings', 'הגדרות POV'),
    '#700051': ('Open DarkSubs Settings', 'הגדרות DarkSubs'),
    '#700052': ('Clear POV Cache', 'ניקוי קאש POV'),
    '#700053': ('Clear DarkSubs Cache', 'ניקוי קאש DarkSubs'),
}


def _translate(path):
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(path)
    except Exception:
        return ''


def _clear_skin_bool(setting_id):
    if xbmc is None:
        return False
    try:
        condition = 'Skin.HasSetting({0})'.format(setting_id)
        if not xbmc.getCondVisibility(condition):
            return False
        xbmc.executebuiltin('Skin.Reset({0})'.format(setting_id))
        return True
    except Exception:
        return False


def _ensure_fentastic_setting_file():
    path = _translate(FENTASTIC_SETTINGS)
    if not path or not os.path.exists(path):
        return False
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        target = None
        for node in root.findall('setting'):
            if (node.get('id') or '').lower() == 'homemenunofavbutton':
                target = node
                break
        if target is None:
            target = ET.SubElement(root, 'setting', {
                'id': 'homemenunofavbutton',
                'type': 'bool',
            })
        if (target.text or '').strip().lower() == 'false':
            return False
        target.text = 'false'
        tree.write(path, encoding='utf-8', xml_declaration=False)
        return True
    except Exception as exc:
        kodi_utils.log('hebrew_build_ui_patcher settings.xml failed: {0}'.format(exc), level='WARNING')
        return False


def _patch_fentastic_home_label():
    path = _translate(FENTASTIC_HOME_XML)
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        candidates = (
            '<label>$LOCALIZE[10134]</label>',
            '<label>$LOCALIZE[10000]</label>',
        )
        new = '<label>מסך הבית</label>'
        old = next((candidate for candidate in candidates
                    if candidate in text), None)
        if old is None:
            return False
        text = text.replace(old, new, 1)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        return True
    except Exception as exc:
        kodi_utils.log('hebrew_build_ui_patcher Home.xml failed: {0}'.format(exc), level='WARNING')
        return False


def _patch_hebrew_skin_strings():
    path = _translate(FENTASTIC_HE_STRINGS)
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        changed = False
        for strid, pair in HE_STRINGS.items():
            msgid, msgstr = pair
            marker = 'msgctxt "{0}"'.format(strid)
            wanted = (
                '{0}\n'
                'msgid "{1}"\n'
                'msgstr "{2}"'
            ).format(marker, msgid, msgstr)
            if marker in text:
                start = text.find(marker)
                next_start = text.find('\nmsgctxt "', start + 1)
                if next_start == -1:
                    block = text[start:]
                else:
                    block = text[start:next_start]
                if 'msgstr "{0}"'.format(msgstr) not in block:
                    replacement = wanted
                    if next_start == -1:
                        text = text[:start] + replacement + '\n'
                    else:
                        text = text[:start] + replacement + text[next_start:]
                    changed = True
            else:
                if not text.endswith('\n'):
                    text += '\n'
                text += '\n{0}\n'.format(wanted)
                changed = True
        if changed:
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(text)
        return changed
    except Exception as exc:
        kodi_utils.log('hebrew_build_ui_patcher strings.po failed: {0}'.format(exc), level='WARNING')
        return False


def ensure_patched():
    changed = []
    if _clear_skin_bool('HomeMenuNoFavButton'):
        changed.append('skin_bool')
    if _ensure_fentastic_setting_file():
        changed.append('skin_settings')
    if _patch_fentastic_home_label():
        changed.append('home_label')
    if _patch_hebrew_skin_strings():
        changed.append('he_strings')
    return 'patched:' + ','.join(changed) if changed else 'already_ok'
