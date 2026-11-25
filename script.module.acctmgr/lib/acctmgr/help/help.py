# -*- coding: utf-8 -*-
from acctmgr.modules.control import addonPath, addonVersion, joinPath
from acctmgr.windows.textviewer import TextViewerXML

def get(file):
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	helpFile = joinPath(acctmgr_path, 'lib', 'acctmgr', 'help', file + '.txt')
	r = open(helpFile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite -  v%s - %s[/B]' % (acctmgr_version, file)
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows

def get_login():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	helpFile = joinPath(acctmgr_path, 'lib', 'acctmgr', 'help', 'login.txt')
	r = open(helpFile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite -  v%s - Torbox & OffCloud Auth Help[/B]' % (acctmgr_version)
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows
	
def get_restore():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	helpFile = joinPath(acctmgr_path, 'lib', 'acctmgr', 'help', 'restore.txt')
	r = open(helpFile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite -  v%s - Restore to Default[/B]' % (acctmgr_version)
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows
