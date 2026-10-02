"""One verified completion path for startup and a manual full installation."""
import importlib.util
import json
import os
import re
import threading
import xml.etree.ElementTree as ET

import xbmc
import xbmcgui
from resources.libs.common.config import CONFIG
from resources.libs.common import logging, tools

PENDING = 'kodipovil.modular_install_started'


def begin():
    os.makedirs(CONFIG.USERDATA, exist_ok=True)
    with open(os.path.join(CONFIG.USERDATA, PENDING), 'w', encoding='utf-8') as fh:
        fh.write('1\n')


def _rpc(method, params):
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(
        {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    if 'error' in reply or 'result' not in reply:
        raise RuntimeError('Kodi setting API failed: ' + method)
    return reply['result']


def _accept_initial_skin_confirmation():
    """The fresh-install request already selected Nox as its default.

    Accept only Kodi's exact skin-retention question after Nox has loaded;
    unrelated dialogs are never clicked. Normal manual skin changes retain
    Kodi's confirmation behavior.
    """
    if (xbmc.getSkinDir() != 'skin.povil.nox' or
            not xbmc.getCondVisibility('Window.IsVisible(yesnodialog)')):
        return False
    try:
        dialog = xbmcgui.Window(10100)
        if (xbmc.getInfoLabel('Control.GetLabel(1)') != xbmc.getLocalizedString(13123) or
                dialog.getControl(9).getText() != xbmc.getLocalizedString(13111)):
            return False
        xbmc.executebuiltin('SendClick(10100,11)')
        return True
    except (RuntimeError, AttributeError):
        return False


def apply_live_defaults():
    """Persist fresh GUI defaults through Kodi, which owns the in-memory copy.

    Set the skin last, after all assets and dependencies have been verified.
    Only the exact first-install skin-retention question is accepted. A
    reverted skin is not reported as a successfully activated build.
    """
    root = ET.parse(os.path.join(CONFIG.USERDATA, 'kodipovil.fresh_gui_defaults.xml')).getroot()
    target_skin = 'skin.povil.nox'
    monitor = xbmc.Monitor()
    for setting in root.findall('setting'):
        key = setting.get('id', '')
        if key.startswith('services.') or key == 'addons.unknownsources':
            continue
        if key == 'lookandfeel.skin':
            continue
        if setting.get('default') == 'true' or setting.text is None:
            continue
        if monitor.abortRequested():
            return False
        # Unknown/deprecated Kodi settings must not prevent a supported build.
        try:
            current = _rpc('Settings.GetSettingValue', {'setting': key})['value']
        except (RuntimeError, KeyError):
            continue
        text = setting.text
        if isinstance(current, bool):
            value = text.lower() == 'true'
        elif isinstance(current, int):
            value = int(text)
        elif isinstance(current, float):
            value = float(text)
        elif isinstance(current, list):
            values = [v.strip() for v in re.split(r'[|,]', text) if v.strip()]
            value = [int(v) if re.fullmatch(r'-?\d+', v) else v for v in values]
        else:
            value = text
        if current != value and _rpc('Settings.SetSettingValue',
                                      {'setting': key, 'value': value}) is not True:
            raise RuntimeError('Fresh setting was rejected: ' + key)
    if xbmc.getSkinDir() != target_skin:
        finished = threading.Event()
        def confirm_requested_skin():
            # SetSettingValue can wait for its GUI confirmation. Start this
            # observer before the RPC, rather than after its ten-second timeout.
            for _ in range(100):
                if finished.is_set() or monitor.abortRequested():
                    return
                if _accept_initial_skin_confirmation():
                    return
                finished.wait(0.2)
        observer = threading.Thread(target=confirm_requested_skin, daemon=True)
        observer.start()
        try:
            if _rpc('Settings.SetSettingValue', {'setting': 'lookandfeel.skin',
                                                'value': target_skin}) is not True:
                return False
        finally:
            finished.set()
            observer.join(1)
    # The skin-confirmation timeout is ten seconds. Wait beyond that before
    # certifying activation, and never certify merely from the RPC reply.
    for _ in range(16):
        if monitor.waitForAbort(1):
            return False
        _accept_initial_skin_confirmation()
    return (xbmc.getSkinDir() == target_skin and
            bool(xbmc.getCondVisibility('Window.IsActive(home)')))


def live_favourites_ready():
    """Kodi caches favourites; an XML write alone does not refresh the home."""
    expected = {node.get('name') for node in ET.parse(
        os.path.join(CONFIG.USERDATA, 'favourites.xml')).getroot().findall('favourite')}
    actual = {item.get('title') for item in (_rpc('Favourites.GetFavourites', {}).get('favourites') or [])}
    if expected and expected.issubset(actual):
        return True
    # First-time subtitle-service migrations can add home tiles after the
    # first profile refresh. Permit one further refresh, then retain the
    # pending marker on failure. This never closes Kodi or loops indefinitely.
    marker = os.path.join(CONFIG.USERDATA, 'kodipovil.fresh_profile_reload')
    try:
        with open(marker, encoding='utf-8') as fh:
            reloads = int(fh.read().strip())
    except (OSError, ValueError):
        reloads = 0
    if reloads < 2:
        with open(marker, 'w', encoding='utf-8') as fh:
            fh.write(str(reloads + 1))
        profile = xbmc.getInfoLabel('System.ProfileName')
        xbmc.executebuiltin('LoadProfile("{0}")'.format(profile.replace('"', '')))
    return False


def finalize():
    """Return success only after media, patches and the live home are ready."""
    from resources.libs.modular_updater import ModularUpdater
    from resources.libs.patch_engine import PatchEngine
    from resources.libs import db
    if not ModularUpdater.is_provisioned():
        return False
    required = ModularUpdater.CORE_PROVISION_IDS + (
        'skin.povil.nox', 'script.fentastic.helper',
        'plugin.program.orderfavourites-hebrew', 'service.subtitles.kodipovilai')
    db.addon_database(list(required), 1, True)
    xbmc.executebuiltin('UpdateLocalAddons')
    monitor = xbmc.Monitor()
    for _ in range(20):
        missing = [aid for aid in required if not xbmc.getCondVisibility(
            'System.HasAddon({0})'.format(aid))]
        if not missing:
            break
        for aid in missing:
            ModularUpdater._enable_addon(aid)
        if monitor.waitForAbort(1):
            return False
    else:
        raise RuntimeError('Fresh runtime dependencies unavailable')
    mi_file = os.path.join(CONFIG.ADDONS, 'plugin.program.orderfavourites-hebrew',
                           'resources', 'lib', 'media_installer.py')
    spec = importlib.util.spec_from_file_location('povil_install_media', mi_file)
    media = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(media)
    if not media.install_and_verify_global_media_assets():
        raise RuntimeError('Fresh media or favourites are incomplete')
    stats = PatchEngine().run()
    if any(stats.get(key, 0) for key in ('failed', 'missing', 'anchor_missing',
                                       'malformed', 'legacy_host_deferred')):
        raise RuntimeError('Fresh source patches are incomplete')
    db.fix_metas()
    if not apply_live_defaults():
        logging.log('[FreshInstall] home not confirmed; retaining completion marker',
                    level=xbmc.LOGWARNING)
        return False
    # Refresh favourites for the activated skin, without extra provider calls.
    if not media.install_and_verify_global_media_assets():
        raise RuntimeError('Fresh skin favourites are incomplete')
    if not live_favourites_ready():
        return False
    version = CONFIG.BUILDVERSION_DEFAULT
    values = {'buildname': CONFIG.BUILDNAME_DEFAULT, 'installed': 'true',
              'buildversion': version, 'latestversion': version,
              'nextbuildcheck': tools.get_date(days=CONFIG.UPDATECHECK, formatted=True),
              'extract': '100', 'errors': '0',
              'fresh_build_auto_install_done': version}
    for key, value in values.items():
        CONFIG.set_setting(key, value)
    CONFIG.BUILDNAME = CONFIG.BUILDNAME_DEFAULT
    CONFIG.BUILDVERSION = CONFIG.BUILDLATEST = version
    CONFIG.INSTALLED = 'true'
    pending = os.path.join(CONFIG.USERDATA, PENDING)
    if os.path.isfile(pending):
        os.remove(pending)
    for name in ('kodipovil.fresh_profile_reload', 'kodipovil.fresh_gui_defaults.xml'):
        path = os.path.join(CONFIG.USERDATA, name)
        if os.path.isfile(path):
            os.remove(path)
    logging.log('[FreshInstall] verified media, patches and active home', level=xbmc.LOGINFO)
    return True
