import xbmc

import re
import threading

try:
    import json as simplejson
except ImportError:
    import simplejson

from resources.libs.common.config import CONFIG

DEFAULT_SKINS = ['skin.estuary', 'skin.estouchy']


def _get_old(old_key):
    try:
        old = '"{0}"'.format(old_key)
        query = '{{"jsonrpc":"2.0","method":"Settings.GetSettingValue","params":{{"setting":{0}}}, "id":1}}'.format(old)
        response = xbmc.executeJSONRPC(query)
        response = simplejson.loads(response)
        if 'result' in response:
            if 'value' in response['result']:
                return response['result']['value']
    except:
        pass
        
    return None
    
    
def _set_new(new_key, value):
    try:
        new = '"{0}"'.format(new_key)
        value = '"{0}"'.format(value)
        query = '{{"jsonrpc":"2.0","method":"Settings.SetSettingValue","params":{{"setting":{0},"value":{1}}}, "id":1}}'.format(new, value)
        xbmc.executeJSONRPC(query)
    except Exception:
        pass
        
    return None


def _swap_skins(skin):
    _set_new('lookandfeel.skin', skin)

    dialog_result = _dialog_watch()
    xbmc.sleep(500)

    return _get_old('lookandfeel.skin') == skin or dialog_result


def switch_to_skin(goto, title="Error"):
    from resources.libs.common import logging

    result = _swap_skins(goto)

    if result:
        logging.log('[COLOR {0}]{1}: Skin Swap Success![/COLOR]'.format(CONFIG.COLOR2, title))
    else:
        logging.log_notify(CONFIG.ADDONTITLE,
                           '[COLOR {0}]{1}: Skin Swap Failed![/COLOR]'.format(CONFIG.COLOR2, title))
                            
    return result


def skin_to_default(title):
    if _get_old('lookandfeel.skin') not in DEFAULT_SKINS:
        from resources.libs.common import logging
        logging.log('[COLOR {0}]{1}: KODI_RD_ISRAEL - Skip setting default Estuary skin no matter what.[/COLOR]'.format(CONFIG.COLOR2, title))
    else:
        from resources.libs.common import logging
        logging.log('[COLOR {0}]{1}: Skipping Skin Swap[/COLOR]'.format(CONFIG.COLOR2, title))
        return False


def look_and_feel_data(do='save'):
    from resources.libs.common import logging

    scan = ['lookandfeel.enablerssfeeds', 'lookandfeel.font', 'lookandfeel.rssedit', 'lookandfeel.skincolors',
            'lookandfeel.skintheme', 'lookandfeel.skinzoom', 'lookandfeel.soundskin', 'lookandfeel.startupwindow',
            'lookandfeel.stereostrength']
            
    if do == 'save':
        for item in scan:
            query = '{{"jsonrpc":"2.0", "method":"Settings.GetSettingValue","params":{{"setting":"{0}"}}, "id":1}}'.format(item)
            response = xbmc.executeJSONRPC(query)
            if 'error' not in response:
                match = re.compile('{"value":(.+?)}').findall(str(response))
                CONFIG.set_setting(item.replace('lookandfeel', 'default'), match[0])
                logging.log("%s saved to %s" % (item, match[0]))
    elif do == 'restore':
        for item in scan:
            value = CONFIG.get_setting(item.replace('lookandfeel', 'default'))
            query = '{{"jsonrpc":"2.0", "method":"Settings.SetSettingValue","params":{{"setting":"{0}","value":{1}}}, "id":1}}'.format(item, value)
            xbmc.executeJSONRPC(query)
            logging.log("{0} restored to {1}".format(item, value))


def swap_us():
    from resources.libs.common import logging
    logging.log('swap_us is unavailable in this build of the wizard')
    return False


def _dialog_watch():
    x = 0
    while not xbmc.getCondVisibility("Window.isVisible(yesnodialog)") and x < 100:
        x += 1
        xbmc.sleep(100)

    if xbmc.getCondVisibility("Window.isVisible(yesnodialog)"):
        xbmc.executebuiltin('SendClick(yesnodialog, 11)')
        return True
    else:
        return False