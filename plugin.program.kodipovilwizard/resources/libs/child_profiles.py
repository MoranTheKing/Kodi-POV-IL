"""Child presentation across build skins and native creation lock defaults."""
import copy
import os
import tempfile
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui

SKINS = ('skin.povil.nox', 'skin.estuary', 'skin.fentastic', 'skin.arctic.fuse.3')
# Kodi's native settings controls are generated from negative IDs (-180).
# Positive IDs belong to dialog chrome/templates, not the editable settings.
NATIVE_SETTING_CONTROLS = range(-180, -160)


def write_xml(path, root):
    data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    if os.path.isfile(path):
        with open(path, 'rb') as source:
            if source.read() == data:
                return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.povil-child-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def seed_skin_flags(profile):
    """Inactive profile only; retain every unrelated skin preference."""
    for ident in SKINS:
        path = os.path.join(profile, 'addon_data', ident, 'settings.xml')
        root = ET.parse(path).getroot() if os.path.isfile(path) else ET.Element('settings')
        row = root.find("setting[@id='POVILChild']")
        if row is None:
            row = ET.SubElement(root, 'setting', id='POVILChild', type='bool')
        row.text = 'true'
        write_xml(path, root)


def install_home(path):
    """Retain adult Home, place its controls behind the profile-local flag."""
    root = ET.parse(path).getroot()
    controls = root.find('controls')
    if controls is None:
        if root.find("include[@content='skin_home_child']") is None:
            return False
        # NOX composes entire windows through root-level includes, unlike
        # the other skins' root controls. Retain that native structure.
        includes = ET.Element('includes')
        section = ET.SubElement(includes, 'include', name='skin_home_child')
        ET.SubElement(section, 'defaultcontrol', always='true').text = '9500'
        ET.SubElement(section, 'controls').append(child_control(path))
        return write_xml(os.path.join(os.path.dirname(path), 'Home_child.xml'), includes)
    old = controls.find("control[@id='9879']")
    if old is None:
        old = ET.Element('control', type='group', id='9879')
        ET.SubElement(old, 'visible').text = '!Skin.HasSetting(POVILChild)'
        for row in list(controls):
            controls.remove(row)
            # Supersede NOX's first child-only include with the shared layout.
            if row.tag == 'include' and row.get('content') == 'skin_home_child':
                continue
            old.append(row)
        controls.append(old)
    existing = controls.find("control[@id='9880']")
    if existing is not None:
        controls.remove(existing)
    controls.append(child_control(path))
    action = 'SetFocus(9500)'
    if not any(r.text == action for r in root.findall('onload')):
        row = ET.Element('onload', condition='Skin.HasSetting(POVILChild)')
        row.text = action
        root.insert(0, row)
    return write_xml(path, root)


def child_control(path):
    source = os.path.join(xbmcaddon.Addon('plugin.program.kodipovilwizard').getAddonInfo('path'),
                          'resources/skins/Default/1080i/ChildHome.xml')
    child = copy.deepcopy(ET.parse(source).getroot().find('controls/control'))
    for button in child.findall(".//control[@type='button']"):
        ET.SubElement(button, 'textcolor').text = 'FFFFFFFF'
        ET.SubElement(button, 'focusedcolor').text = 'FFF0D394'
    adapt_fonts(child, path)
    return child


def adapt_fonts(layout, path):
    """Resolve the shared layouts' font names against each installed skin."""
    fonts_path = os.path.join(os.path.dirname(path), 'Font.xml')
    if os.path.isfile(fonts_path):
        fonts = [(f.findtext('name'), float(f.findtext('size', '30')))
                 for f in ET.parse(fonts_path).findall('.//fontset/font')
                 if not any(term in (f.findtext('name', '') + f.findtext('filename', '')).lower()
                            for term in ('icon', 'awesome', 'codec', 'nick-titling'))]
        for row in layout.iter('font'):
            if fonts:
                wanted = {'font60': 60, 'font37': 37, 'font13': 30, 'font12': 25}[row.text]
                row.text = min(fonts, key=lambda f: (abs(f[1] - wanted), f[0] != row.text))[0]
        if not fonts and os.path.isfile(os.path.join(os.path.dirname(path), 'Includes_Font.xml')):
            # Arctic Fuse declares its fonts in parameterized includes.
            # Use only names declared by that skin, not a nonexistent font60.
            available = {f.findtext('name') for f in ET.parse(
                os.path.join(os.path.dirname(path), 'Includes_Font.xml')).findall('.//font')}
            names = {'font60': 'font_title_midi', 'font37': 'font_head_bold',
                     'font13': 'font_main', 'font12': 'font_mini'}
            for row in layout.iter('font'):
                if names.get(row.text) in available:
                    row.text = names[row.text]


def focus_home():
    # Several skins set their adult defaultcontrol after onload actions.
    # The short bootstrap invocation places child focus after that step.
    if not xbmc.getCondVisibility('Skin.HasSetting(POVILChild)'):
        return
    if xbmc.Monitor().waitForAbort(0.2):
        return
    if (xbmc.getCondVisibility('Skin.HasSetting(POVILChild)') and
            xbmc.getCondVisibility('Window.IsActive(home)')):
        xbmc.executebuiltin('SetFocus(9500)')


def sync_active():
    """Never let a different skin restore an unrestricted child's Home."""
    from resources.libs.patches import profile_age_guard
    policy = profile_age_guard.active_policy()
    wanted = policy is not None
    current = xbmc.getCondVisibility('Skin.HasSetting(POVILChild)')
    if current == wanted:
        return False
    xbmc.executebuiltin('Skin.SetBool(POVILChild)' if wanted else 'Skin.Reset(POVILChild)', True)
    return True


def preset_native_locks(state):
    """Only during an explicitly requested child-creation flow; no PIN changes.

    Set once per native lock dialog and leave it open for parental review.
    Video stays accessible to the filtered movie browser, settings/files/addon
    management and unrelated media windows get the recommended defaults.
    """
    dialog = xbmcgui.getCurrentWindowDialogId()
    if dialog == 10130 and not state.get('opened'):
        # This helper is called only from add_profile(kind=child). Kodi still
        # owns any master-code question and the parent's final Save/Cancel.
        window = xbmcgui.Window(10130)
        for ident in NATIVE_SETTING_CONTROLS:
            try:
                if window.getControl(ident).getLabel() == xbmc.getLocalizedString(20066):
                    state['opened'] = True
                    # Opening a native modal synchronously would hold this
                    # observer until the parent closes it, so it could never
                    # apply the defaults inside that dialog.
                    xbmc.executebuiltin('SendClick(10130,{})'.format(ident))
                    return True
            except RuntimeError:
                break  # native settings are generated consecutively
            except AttributeError:
                continue
        return False
    if dialog == 12000 and state.get('settings_pending'):
        if xbmc.getInfoLabel('Control.GetLabel(1)') != xbmc.getLocalizedString(20043):
            return False
        window = xbmcgui.Window(12000)
        # Native Select uses list 3 for text choices, list 6 for detailed rows.
        for ident in (3, 6):
            listing = window.getControl(ident)
            if not listing.isVisible():
                continue
            # Python ControlList.size/getListItem expose Python-owned items,
            # not Kodi's native list. Focus Kodi's All row and verify its label
            # through the native information manager before selecting it.
            xbmc.executebuiltin('SetFocus({},1,absolute)'.format(ident), True)
            if xbmc.getInfoLabel('Container({}).ListItem.Label'.format(ident)) != xbmc.getLocalizedString(593):
                return False
            xbmc.executebuiltin('Action(Select,12000)', True)
            state['settings_pending'] = False
            state['completed'] = True
            return True
        return False
    if dialog != 10131:
        state['in_locks'] = False
        return False
    if state.get('in_locks') or state.get('completed'):
        return False
    window = xbmcgui.Window(10131)
    try:
        # Kodi's shared native dialog starts at -180, with a separator -179.
        # Validate both named buttons and every radio before changing anything;
        # an unknown dialog/version is left entirely to the parent.
        if (window.getControl(-180).getLabel() != xbmc.getLocalizedString(20068) or
                window.getControl(-173).getLabel() != xbmc.getLocalizedString(20043)):
            return False
        radios = {i: window.getControl(i) for i in (-178, -177, -176, -175, -174, -172)}
        if not all(hasattr(c, 'isSelected') and hasattr(c, 'setSelected') for c in radios.values()):
            return False
        state['in_locks'] = True
        for ident in (-178, -176, -175, -174, -172):
            control = radios[ident]
            if not control.isSelected():
                control.setSelected(True)
                # Notify Kodi's settings model so the value survives Save.
                xbmc.executebuiltin('SendClick(10131,{})'.format(ident), True)
        state['settings_pending'] = True
        xbmc.executebuiltin('SendClick(10131,-173)')
    except (RuntimeError, AttributeError):
        return False
    return True
