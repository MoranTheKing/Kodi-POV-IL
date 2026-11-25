# -*- coding: utf-8 -*-
import xbmcvfs
from acctmgr.modules.control import addonPath, addonVersion, joinPath, translatePath
from acctmgr.windows.textviewer import TextViewerXML

supported_path = translatePath('special://home/addons/script.module.acctmgr/resources/skins/Default/media/common/')

def get_changelog():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(acctmgr_path, 'changelog.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite -  v%s - ChangeLog[/B]' % acctmgr_version
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows

def get_supported_trakt():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_trakt.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows

def get_supported_mdblist():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_mdblist.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows
	
def get_supported_debrid():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_debrid.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows

def get_supported_torbox():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_torbox.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows
	
def get_supported_easydebrid():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_easydebrid.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows
	
def get_supported_offcloud():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_offcloud.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows

def get_supported_easynews():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_easynews.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows
	
def get_supported_ext():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_ext.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows

def get_supported_maxql():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_maxql.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows

def get_supported_autoplay():
	acctmgr_path = addonPath()
	acctmgr_version = addonVersion()
	changelogfile = joinPath(supported_path, 'supported_autoplay.txt')
	r = open(changelogfile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]AM Lite - Supported Add-ons[/B]'
	windows = TextViewerXML('textviewer.xml', acctmgr_path, heading=heading, text=text)
	windows.run()
	del windows
