"""Provision YouTube only when Apple's embedded native dependency fits."""
import json
import os
import re
import xbmc
import xbmcgui
import xbmcvfs


def version(value):
    return tuple(int(part) for part in re.findall(r'\d+', value or '')[:3])


def on_webos():
    """An LG TV: webOS gives every app its APPID (Kodi 21 has no platform condition for it), installs it under
    /usr/palm/applications, and names itself."""
    if os.environ.get('APPID') and xbmc.getCondVisibility('System.Platform.Linux + !System.Platform.Android'):
        return True
    try:
        if '/usr/palm/applications/' in xbmcvfs.translatePath('special://xbmc/'):
            return True
    except Exception:
        pass
    return 'webos' in (xbmc.getInfoLabel('System.OSVersionInfo') or '').lower()


def eligible(ids):
    ids = list(ids)
    if 'plugin.video.youtube' not in ids:
        return ids
    apple = any(xbmc.getCondVisibility('System.Platform.' + name)
                for name in ('TVOS', 'IOS', 'ATV2'))
    # An LG TV cannot fetch a binary add-on from Kodi's repository either: on a Kodi built without
    # inputstream.adaptive the first install stopped at Kodi's box "The dependency on inputstream.adaptive
    # version 19.0.0 could not be satisfied" (the owner's LG, Nov 2026, a Kodi 21.2 build) and went no further.
    webos = not apple and on_webos()
    embedded = apple or webos
    try:
        request = dict(jsonrpc='2.0', id=1, method='Addons.GetAddonDetails',
                       params=dict(addonid='inputstream.adaptive', properties=['version', 'enabled']))
        details = json.loads(xbmc.executeJSONRPC(json.dumps(request))).get('result', {}).get('addon', {})
        compatible = version(details.get('version')) >= (19, 0, 0)
        if compatible and details.get('enabled') is False:
            request.update(method='Addons.SetAddonEnabled', params=dict(addonid='inputstream.adaptive', enabled=True))
            xbmc.executeJSONRPC(json.dumps(request))
    except (ValueError, TypeError):
        details, compatible = {}, False
    if not embedded:
        return ids  # Kodi's native installer resolves OS/ABI-specific binaries.
    path = xbmcvfs.translatePath('special://profile/addon_data/plugin.program.kodipovilwizard/youtube_native_dependency.json')
    if compatible:
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        return ids
    # tvOS cannot download or replace binary add-ons. Never keep launching
    # InstallAddon for an unsatisfiable dependency or weaken its version floor.
    state = dict(kodi=xbmc.getInfoLabel('System.BuildVersion'),
                 adaptive=details.get('version', 'missing'))
    try:
        with open(path, encoding='utf-8') as handle:
            previous = json.load(handle)
    except (OSError, ValueError):
        previous = None
    if previous != state:
        # Also deduplicate if a read-only profile cannot save the receipt.
        home = xbmcgui.Window(10000)
        fingerprint = json.dumps(state, sort_keys=True)
        if home.getProperty('POVIL.YouTubeDependencyNotice') != fingerprint:
            home.setProperty('POVIL.YouTubeDependencyNotice', fingerprint)
            if webos:
                xbmcgui.Dialog().notification('YouTube',
                    'בקודי הזה אין InputStream Adaptive: YouTube והטריילרים לא הותקנו.', time=8000)
            else:
                xbmcgui.Dialog().notification('YouTube באפל TV',
                    'נדרש עדכון קודי עם InputStream Adaptive ‏19 ומעלה.', time=8000)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(state, handle)
        except OSError:
            pass
    xbmc.log('[POV IL] YouTube deferred: %s' % ('this Kodi of the LG TV has no usable InputStream Adaptive' if webos
                                               else 'embedded InputStream Adaptive is incompatible; update Apple Kodi'),
             xbmc.LOGWARNING)
    return [ident for ident in ids if ident != 'plugin.video.youtube']
