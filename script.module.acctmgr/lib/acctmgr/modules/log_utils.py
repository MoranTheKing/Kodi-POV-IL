# -*- coding: utf-8 -*-
import xbmc, xbmcvfs
import unicodedata
import requests
import traceback
import inspect
import sys
import os
from sys import platform
from datetime import datetime
from subprocess import check_call, Popen, PIPE

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4
LOGNONE = 5  # not used

debug_list = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'FATAL']
DEBUGPREFIX = '[COLOR red][ AM Lite %s ][/COLOR]'
translatePath = xbmcvfs.translatePath
LOGPATH = translatePath('special://logpath/')

# Helpers
def copy2clip(txt):
	try:
		if platform == "win32":
			cmd = "echo " + txt.replace('&', '^&').strip() + "|clip"
			check_call(cmd, shell=True)
		elif platform == "darwin":
			check_call("echo " + txt.strip() + "|pbcopy", shell=True)
		elif platform == "linux":
			p = Popen(["xsel", "-pi"], stdin=PIPE)
			p.communicate(input=txt)
	except:
		error('Clipboard copy failed')

def normalize(msg):
	try:
		msg = ''.join(c for c in unicodedata.normalize('NFKD', msg) if unicodedata.category(c) != 'Mn')
		return str(msg)
	except:
		error()
		return msg
# Logging	
def log(msg, caller=None, level=LOGINFO):
	from acctmgr.modules.control import setting as getSetting, lang, joinPath, existsPath
	try:
		if getSetting('debug.enabled') != 'true':
			return
		debug_location = getSetting('debug.location')

		if isinstance(msg, int):
			msg = lang(msg)

		if not msg.isprintable():
			msg = '%s (NORMALIZED by log_utils.log())' % normalize(msg)
		if isinstance(msg, bytes):
			msg = '%s (ENCODED by log_utils.log())' % msg.decode('utf-8', errors='replace')

		if caller is not None and level != LOGERROR:
			func = inspect.currentframe().f_back.f_code
			line_number = inspect.currentframe().f_back.f_lineno
			caller = "%s.%s()" % (caller, func.co_name)
			msg = 'From func name: %s Line # :%s\n                       msg : %s' % (caller, line_number, msg)
		elif caller is not None and level == LOGERROR:
			msg = 'From func name: %s.%s() Line # :%s\n                       msg : %s' % (caller[0], caller[1], caller[2], msg)

		if debug_location == '1':
			log_file = joinPath(LOGPATH, 'acctmgr.log')
			if not existsPath(log_file):
				f = xbmcvfs.File(log_file, 'w')
				f.close()

			reverse_log = getSetting('debug.reversed') == 'true'
			line = '[%s %s] %s: %s' % (
				datetime.now().date(),
				str(datetime.now().time())[:8],
				DEBUGPREFIX % debug_list[level],
				msg
			)

			if not reverse_log:
				with open(log_file, 'a', encoding='utf-8') as f:
					f.write(line.rstrip('\r\n') + '\n')
			else:
				with open(log_file, 'r+', encoding='utf-8') as f:
					old = f.read()
					f.seek(0, 0)
					f.write(line.rstrip('\r\n') + '\n' + old)
		else:
			xbmc.log('%s: %s' % (DEBUGPREFIX % debug_list[level], msg), level)
	except Exception as e:
		traceback.print_exc()
		xbmc.log('[ script.module.acctmgr ] log_utils.log() Logging Failure: %s' % e, LOGERROR)

def error(message=None, exception=True):
	try:
		caller = None

		if exception:
			_type, value, tb = sys.exc_info()
			if tb is not None and _type is not None:
				filename = tb.tb_frame.f_code.co_filename
				name = tb.tb_frame.f_code.co_name
				linenumber = tb.tb_lineno
				errortype = _type.__name__
				errormessage = value if value is not None else 'No exception message'

				if message:
					message += ' -> '
				else:
					message = ''

				message += str(errortype) + ' -> ' + str(errormessage)
				caller = [filename, name, linenumber]
			else:
				if not message:
					message = 'log_utils.error() called with no active exception'
		else:
			caller = None
			
		# Fallback log (always works)
		xbmc.log('[ AM Lite ERROR ] %s' % message, xbmc.LOGERROR)

		log(msg=message, caller=caller, level=LOGERROR)
	except Exception as e:
		xbmc.log('[ script.module.acctmgr ] log_utils.error() Logging Failure: %s' % e, xbmc.LOGERROR)

# Clear Log File
def clear_logFile():
    from acctmgr.modules.control import yesnoDialog, lang, joinPath, existsPath, notification, setting

    try:
        # Check which log is selected
        if setting('debug.location') != '1':  # Not AM Lite log
            return notification(message='Cannot clear Kodi log file. Select AM Lite log file to clear.')

        # Ask user to confirm
        if not yesnoDialog('Are you sure?', 'AM Lite', ''):
            return 'canceled'

        log_file = joinPath(LOGPATH, 'acctmgr.log')
        if not existsPath(log_file):
            f = xbmcvfs.File(log_file, 'w')
            f.close()
            return True

        with open(log_file, 'r+') as f:
            f.truncate(0)
        return True

    except Exception as e:
        xbmc.log(f'[ script.module.acctmgr ] log_utils.clear_logFile() Failure: {e}', xbmc.LOGERROR)
        return False

# View Log File
def view_LogFile():
    try:
        from acctmgr.modules.control import addonPath, joinPath, existsPath, notification, setting
        from acctmgr.windows.textviewer import TextViewerXML

        location = setting('debug.location')
        if location == '0':  # Kodi log
            log_file = LOGPATH + 'kodi.log'  # <- do not use joinPath
        else:  # AM Lite log
            log_file = joinPath(LOGPATH, 'acctmgr.log')

        if not existsPath(log_file):
            return notification(message=f'No Log File Found: {log_file}')

        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

        heading = f'[B]Account Manager Lite - {os.path.basename(log_file)}[/B]'
        win = TextViewerXML('textviewer.xml', addonPath(), heading=heading, text=text)
        win.run()

    except Exception as e:
        notification(message=f'Failed to view log: {e}')


# Upload log file based on debug.location setting
def upload_LogFile():
    try:
        import requests
        from acctmgr.modules.control import joinPath, existsPath, notification, addonVersion, selectDialog, lang, setting

        # Determine which log to upload
        location = setting('debug.location')  # '0' = Kodi log, '1' = AM Lite log
        log_file_name = 'kodi.log' if location == '0' else 'acctmgr.log'

        log_file = joinPath(LOGPATH, log_file_name)
        if not existsPath(log_file):
            return notification(message=f'No Log File Found: {log_file_name}')

        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

        url = 'https://paste.kodi.tv/'
        UserAgent = f'acctmgr {addonVersion()}'
        response = requests.post(url + 'documents', data=text.encode('utf-8', errors='ignore'),
                                 headers={'User-Agent': UserAgent})
        data = response.json()

        if 'key' in data:
            result = url + data['key']
            log(f'AM Lite log file uploaded to: {result}')
            listing = [('[COLOR gold]url:[/COLOR]  %s' % result, result)]
            select = selectDialog([i[0] for i in listing], lang(32349))
            if select == 0:
                copy2clip(result)
        else:
            notification(message='Log upload failed')

    except Exception as e:
        notification(message=f'Failed to upload log: {e}')
