"""Skin fallback for a newly loaded profile whose Wizard is disabled.

Keep this invocation short. Kodi starts startup.py itself after enabling the
service; the departing profile's Python invocation never owns initialization.
"""
import json
import os
import xbmc
import xbmcvfs


def resume():
    master = os.path.realpath(xbmcvfs.translatePath('special://masterprofile/'))
    active = os.path.realpath(xbmcvfs.translatePath('special://profile/'))
    if not os.path.isfile(os.path.join(master, 'kodipovil.provisioned')):
        return False
    from resources.libs import build_skin
    if build_skin.prepare_active_skin_defaults():
        xbmc.executebuiltin('ReloadSkin()')
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
