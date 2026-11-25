import xbmc, xbmcvfs
import os

#Variables
amgr = 'AM Lite ERROR'
translatePath = xbmcvfs.translatePath
addon_data = translatePath('special://profile/addon_data/')

#Realizer Paths
realx_path = addon_data + translatePath('plugin.video.realizerx')
realx_json_path = realx_path + translatePath('rdauth.json')

###################### Revoke Realizer RD ######################
def realizer_rvk():
    if os.path.exists(os.path.join(realx_json_path)):
        try:
            os.unlink(os.path.join(realx_json_path))
            xbmcvfs.copy(os.path.join(realx_json), os.path.join(realx_json_path))
        except Exception as e:
            xbmc.log(f'{amgr}: JSONIT_DB Revoke Realizer RD Failed!: {e}', xbmc.LOGINFO)
            pass
