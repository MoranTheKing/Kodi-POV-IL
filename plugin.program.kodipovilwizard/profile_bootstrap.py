"""Skin fallback for a newly loaded profile whose Wizard is disabled.

Keep this invocation short. Kodi starts startup.py itself after enabling the
service; the departing profile's Python invocation never owns initialization.
"""
import json
import os
import xbmc
import xbmcgui
import xbmcvfs


def _settled_adult(master, active):
    """Avoid layout imports on an already initialized adult Home onload.

    Read the active identity and central child policy afresh. Missing/broken
    child data, a child marker or a live child skin flag keep the full path.
    New profiles and Estuary's first sidebar migration also keep that path.
    """
    if (active != master and
            not os.path.isfile(os.path.join(active, 'kodipovil.profile_home_ready'))):
        return False
    if (os.path.isfile(os.path.join(active, 'povil.child-profile')) or
            xbmc.getCondVisibility('Skin.HasSetting(POVILChild)')):
        return False
    if active != master:
        try:
            if os.path.commonpath((master, active)) != master:
                return False
            path = os.path.join(master, 'povil_profiles.json')
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as source:
                    policy = json.load(source)
                children = policy.get('children')
                if policy.get('schema') != 1 or not isinstance(children, dict):
                    return False
                key = os.path.relpath(active, master).replace('\\', '/')
                if children.get(key) is not None:
                    return False
        except (OSError, ValueError, TypeError, AttributeError):
            return False
    return (xbmc.getSkinDir() != 'skin.estuary' or
            xbmc.getCondVisibility('Skin.HasSetting(POVIL.BuildSidebarReadyV2)'))


def resume():
    # A Home onload runs before Kodi's skin retention dialog. Reloading here
    # closes that dialog and silently reverts the user's requested skin.
    # The switch owner initializes this same layout after native confirmation.
    if (xbmcgui.Window(10000).getProperty('POVIL.RequestedSkin') or
            xbmcgui.getCurrentWindowDialogId() == 10100):
        return False
    master = os.path.realpath(xbmcvfs.translatePath('special://masterprofile/'))
    active = os.path.realpath(xbmcvfs.translatePath('special://profile/'))
    if not os.path.isfile(os.path.join(master, 'kodipovil.provisioned')):
        return False
    if _settled_adult(master, active):
        return False
    from resources.libs import build_skin
    if build_skin.prepare_active_skin_defaults():
        xbmc.executebuiltin('ReloadSkin()')
    from resources.libs import child_profiles
    child_profiles.focus_home()
    if active == master:
        return False
    if os.path.isfile(os.path.join(active, 'kodipovil.profile_home_ready')):
        return False  # preserve intentional disabling after setup
    addon = 'plugin.program.kodipovilwizard'
    query = dict(jsonrpc='2.0', id=1, method='Addons.GetAddonDetails',
                 params=dict(addonid=addon, properties=['enabled']))
    result = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
    if result.get('result', {}).get('addon', {}).get('enabled') is True:
        return False
    query.update(method='Addons.SetAddonEnabled', params=dict(addonid=addon, enabled=True))
    result = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
    return 'error' not in result


if __name__ == '__main__':
    try:
        resume()
    except Exception as exc:
        xbmc.log('[Profiles] startup bootstrap deferred: ' + type(exc).__name__, xbmc.LOGWARNING)
