"""Login-window hook: resume only a sole, completely unlocked master.

Kodi does not start add-on services until a profile is selected. The login
skin calls this small script so the normal startup service can then clear the
obsolete login-screen preference through Kodi's own settings window.
"""
import json
import os
import xml.etree.ElementTree as ET

import xbmc
import xbmcvfs


def resume():
    if not xbmc.getCondVisibility('Window.IsActive(loginscreen)'):
        return False
    path = xbmcvfs.translatePath('special://masterprofile/profiles.xml')
    try:
        rows = ET.parse(path).getroot().findall('profile')
        if (len(rows) != 1 or rows[0].findtext('id') != '0' or
                rows[0].findtext('lockmode', '0') != '0' or
                rows[0].findtext('lockcode', '-') not in ('', '-')):
            return False
        # Keep native PIN enforcement even though the checked master is free.
        request = dict(jsonrpc='2.0', id=1, method='Profiles.LoadProfile',
                       params=dict(profile=rows[0].findtext('name'), prompt=True))
        response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        return 'result' in response and 'error' not in response
    except (OSError, ET.ParseError, ValueError, TypeError):
        return False


if __name__ == '__main__':
    resume()
