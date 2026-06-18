# Build-only UI guardrails for Kodi POV IL.
#
# The build home menu should not expose Kodi's raw "Favourites" entry as
# the user's home button. Keep the button visible, but label it like the
# rest of the Hebrew build sidemenu.

import os
import json
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
FENTASTIC_EN_STRINGS = (
    'special://home/addons/skin.fentastic/language/resource.language.en_gb/strings.po'
)
# Pristine, known-good copies of the skin's language files, bundled inside THIS
# add-on (so they ride along in every quick update). Used to self-heal a
# corrupt/truncated strings.po. Keyed: live skin path -> bundled pristine file.
_SKIN_REPAIR_DIR = os.path.join(os.path.dirname(__file__), '..', 'skin_repair')
SKIN_STRINGS_REPAIR = {
    FENTASTIC_HE_STRINGS: os.path.join(_SKIN_REPAIR_DIR, 'fentastic_he_il_strings.po'),
    FENTASTIC_EN_STRINGS: os.path.join(_SKIN_REPAIR_DIR, 'fentastic_en_gb_strings.po'),
}
GUISETTINGS = 'special://profile/guisettings.xml'
FENTASTIC_DEFAULT_PLAYER_SETTING = 'chooseosdplayer'

HE_STRINGS = {
    '#31072': ('Power Options', 'אפשרויות כיבוי'),
    '#700050': ('Open POV Settings', 'הגדרות POV'),
    '#700051': ('Open DarkSubs Settings', 'הגדרות DarkSubs'),
    '#700052': ('Clear POV Cache', 'ניקוי קאש POV'),
    '#700053': ('Clear DarkSubs Cache', 'ניקוי קאש DarkSubs'),
    '#700070': ('Switch FENtastic Player', 'החלפת נגן FENtastic'),
}


def _translate(path):
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(path)
    except Exception:
        return ''


def _atomic_write(path, text):
    """Write text to a file atomically: full write to a temp file in the same
    directory, fsync, then os.replace over the target. The live file is only
    ever swapped once the new content is completely on disk.

    This is the fix for the "FENtastic loads but all text is blank" reports:
    these helpers used to write the skin's strings.po / Home.xml in place with
    a plain open('w'), so if Kodi was force-closed mid-write (exactly what the
    quick-update flow does) the file was left truncated -- a truncated strings.po
    means every $LOCALIZE Hebrew label renders empty. An atomic replace can
    never leave a half-written file behind."""
    tmp = path + '.kpovtmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def _atomic_tree_write(tree, path):
    """Atomic ElementTree write (temp file + os.replace), so a force-close
    can't leave guisettings.xml / settings.xml truncated."""
    tmp = path + '.kpovtmp'
    tree.write(tmp, encoding='utf-8', xml_declaration=False)
    os.replace(tmp, path)


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
        player_target = None
        for node in root.findall('setting'):
            setting_id = (node.get('id') or '').lower()
            if setting_id == 'homemenunofavbutton':
                target = node
            elif setting_id == FENTASTIC_DEFAULT_PLAYER_SETTING:
                player_target = node
        if target is None:
            target = ET.SubElement(root, 'setting', {
                'id': 'homemenunofavbutton',
                'type': 'bool',
            })
        changed = False
        if (target.text or '').strip().lower() != 'false':
            target.text = 'false'
            changed = True
        if player_target is None:
            player_target = ET.SubElement(root, 'setting', {
                'id': FENTASTIC_DEFAULT_PLAYER_SETTING,
                'type': 'bool',
            })
            player_target.text = 'true'
            changed = True
        if changed:
            _atomic_tree_write(tree, path)
        return changed
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
        _atomic_write(path, text)
        return True
    except Exception as exc:
        kodi_utils.log('hebrew_build_ui_patcher Home.xml failed: {0}'.format(exc), level='WARNING')
        return False


def _restore_corrupt_skin_strings():
    """Self-heal the "FENtastic loads but ALL text is blank" bug.

    A truncated/empty strings.po blanks every $LOCALIZE label, so the whole
    skin renders with no text (only icons). v0.2.143 made our own writes atomic
    so WE can no longer truncate it -- but a file already corrupted (by an older
    build, an interrupted extract, a power loss, etc.) stays broken forever,
    because nothing repairs it in place. This restores a bundled pristine copy
    whenever the live file is missing/empty/suspiciously short, on every
    startup, independent of the quick-update extractor. Healthy files (incl. a
    legitimately newer/larger skin translation) are left untouched."""
    restored = []
    for live_special, pristine_path in SKIN_STRINGS_REPAIR.items():
        try:
            if not os.path.exists(pristine_path):
                continue
            pristine_size = os.path.getsize(pristine_path)
            if pristine_size <= 0:
                continue
            live_path = _translate(live_special)
            if not live_path:
                continue
            corrupt = False
            if not os.path.exists(live_path):
                # The skin file should exist; if it's gone the skin can't render
                # that language at all, so put the good copy back.
                corrupt = True
            else:
                live_size = os.path.getsize(live_path)
                # < 60% of the known-good size == truncated/blanked. A healthy
                # file (even an updated one) is never this much smaller.
                if live_size <= 0 or live_size < pristine_size * 0.6:
                    corrupt = True
            if not corrupt:
                continue
            with open(pristine_path, 'r', encoding='utf-8', errors='ignore') as f:
                good = f.read()
            if not good.strip():
                continue
            _atomic_write(live_path, good)
            restored.append(os.path.basename(os.path.dirname(live_path)))
        except Exception as exc:
            kodi_utils.log('hebrew_build_ui_patcher restore failed: {0}'.format(exc), level='WARNING')
    if restored:
        kodi_utils.log('hebrew_build_ui_patcher: restored corrupt skin strings.po for {0}'.format(
            ','.join(restored)), level='WARNING')
    return bool(restored)


def _patch_hebrew_skin_strings():
    path = _translate(FENTASTIC_HE_STRINGS)
    if not path or not os.path.exists(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
        original = text
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
                        # Keep the blank line between PO entries. text[next_start:]
                        # begins at "\nmsgctxt", and `wanted` has no trailing
                        # newline, so without this extra \n the two entries would
                        # be glued together (msgstr "..."\nmsgctxt) -- malformed PO.
                        text = text[:start] + replacement + '\n' + text[next_start:]
                    changed = True
            else:
                if not text.endswith('\n'):
                    text += '\n'
                text += '\n{0}\n'.format(wanted)
                changed = True
        if changed:
            # Never swap in a strings.po that is empty or drastically shorter
            # than what we read -- a corrupt/truncated strings.po blanks every
            # Hebrew $LOCALIZE label in the skin (the "loads but no text" bug).
            if not text.strip() or len(text) < len(original) // 2:
                kodi_utils.log(
                    'hebrew_build_ui_patcher: refusing to write suspect '
                    'strings.po (new {0} vs orig {1} bytes)'.format(
                        len(text), len(original)), level='WARNING')
                return False
            _atomic_write(path, text)
        return changed
    except Exception as exc:
        kodi_utils.log('hebrew_build_ui_patcher strings.po failed: {0}'.format(exc), level='WARNING')
        return False


def _ensure_hebrew_keyboard_layout():
    path = _translate(GUISETTINGS)
    if not path or not os.path.exists(path):
        return False
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        changed = False
        settings = {}
        for node in root.findall('setting'):
            settings[(node.get('id') or '').lower()] = node

        layouts = settings.get('locale.keyboardlayouts')
        if layouts is None:
            layouts = ET.SubElement(root, 'setting', {
                'id': 'locale.keyboardlayouts',
            })
            settings['locale.keyboardlayouts'] = layouts
            changed = True
        current = [part.strip() for part in (layouts.text or '').split('|')
                   if part.strip()]
        wanted = ['English QWERTY', 'Hebrew QWERTY']
        merged = []
        for name in wanted + current:
            if name not in merged:
                merged.append(name)
        merged_text = '|'.join(merged)
        if (layouts.text or '') != merged_text:
            layouts.text = merged_text
            changed = True

        active = settings.get('locale.activekeyboardlayout')
        if active is None:
            active = ET.SubElement(root, 'setting', {
                'id': 'locale.activekeyboardlayout',
                'default': 'true',
            })
            active.text = 'English QWERTY'
            changed = True

        if changed:
            _atomic_tree_write(tree, path)
        return changed
    except Exception as exc:
        kodi_utils.log('hebrew_build_ui_patcher keyboard failed: {0}'.format(exc), level='WARNING')
        return False


def _set_kodi_setting(setting, value):
    if xbmc is None:
        return False
    try:
        payload = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'Settings.SetSettingValue',
            'params': {'setting': setting, 'value': value},
        }
        result = xbmc.executeJSONRPC(json.dumps(payload))
        return '"OK"' in result or '"result":"OK"' in result
    except Exception as exc:
        kodi_utils.log('hebrew_build_ui_patcher JSON setting failed: {0}: {1}'.format(setting, exc), level='WARNING')
        return False


def _ensure_runtime_keyboard_layout():
    changed = False
    layouts = ['English QWERTY', 'Hebrew QWERTY']
    # Kodi accepts keyboardlayouts as a list through JSON-RPC. Keep the
    # active layout English so existing users do not unexpectedly switch;
    # the keyboard button can then cycle to Hebrew.
    if _set_kodi_setting('locale.keyboardlayouts', layouts):
        changed = True
    if _set_kodi_setting('locale.activekeyboardlayout', 'English QWERTY'):
        changed = True
    return changed


def _ensure_english_audio_preference_file():
    path = _translate(GUISETTINGS)
    if not path or not os.path.exists(path):
        return False
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        changed = False
        settings = {}
        for node in root.findall('setting'):
            settings[(node.get('id') or '').lower()] = node

        for setting_id in ('locale.audiolanguage',
                           'locale.defaultaudiolanguage'):
            node = settings.get(setting_id)
            if node is None:
                node = ET.SubElement(root, 'setting', {'id': setting_id})
                settings[setting_id] = node
            if (node.text or '').strip() != 'English':
                node.text = 'English'
                changed = True

        if changed:
            _atomic_tree_write(tree, path)
        return changed
    except Exception as exc:
        kodi_utils.log('hebrew_build_ui_patcher audio failed: {0}'.format(exc), level='WARNING')
        return False


def _ensure_runtime_english_audio_preference():
    changed = False
    for setting_id in ('locale.audiolanguage',
                       'locale.defaultaudiolanguage'):
        if _set_kodi_setting(setting_id, 'English'):
            changed = True
    return changed


def ensure_patched():
    changed = []
    # Repair a blanked/truncated skin strings.po FIRST, so the label patch below
    # works on a healthy file and the user never sees a text-less skin.
    if _restore_corrupt_skin_strings():
        changed.append('restored_skin_strings')
    if _clear_skin_bool('HomeMenuNoFavButton'):
        changed.append('skin_bool')
    if _ensure_fentastic_setting_file():
        changed.append('skin_settings')
    if _patch_fentastic_home_label():
        changed.append('home_label')
    if _patch_hebrew_skin_strings():
        changed.append('he_strings')
    if _ensure_hebrew_keyboard_layout():
        changed.append('keyboard_layouts')
    if _ensure_runtime_keyboard_layout():
        changed.append('runtime_keyboard_layouts')
    if _ensure_english_audio_preference_file():
        changed.append('english_audio_file')
    if _ensure_runtime_english_audio_preference():
        changed.append('english_audio_runtime')
    return 'patched:' + ','.join(changed) if changed else 'already_ok'
