# -*- coding: utf-8 -*-
import os
import shutil

import xbmc
import xbmcgui
import xbmcvfs

from acctmgr.modules import control


# TMDB HELPER PLAYER DEFINITIONS
PLAYER_FILES = (
	('Fen Light', 'plugin.video.fenlight', 'fenlight.json'),
	('The Gears', 'plugin.video.gears', 'gears.json'),
	('Red Light', 'plugin.video.redlight', 'redlight.json'),
	('Umbrella', 'plugin.video.umbrella', 'umbrella.json'),
	('POV', 'plugin.video.pov', 'pov.json'),
	('Seren', 'plugin.video.seren', 'seren.json'),
	('Prism', 'plugin.video.prism', 'prism.json'),
	('Luc_Kodi', 'plugin.video.luc_kodi', 'luc_kodi.json'),
	('Genocide', 'plugin.video.genocide', 'genocide.json'),
	('Shadow', 'plugin.video.shadow', 'shadow.json'),
	('Ghost', 'plugin.video.ghost', 'ghost.json'),
	('Homelander', 'plugin.video.homelander', 'homelander.json'),
	('Nightwing', 'plugin.video.nightwing', 'nightwing.json'),
	('Jokers Absolution', 'plugin.video.absolution', 'absolution.json'),
	('The Crew', 'plugin.video.thecrew', 'thecrew.json'),
	('Scrubs V2', 'plugin.video.scrubsv2', 'scrubsv2.json'),
	('Gratis Red', 'plugin.video.gratisred', 'gratisred.json'),
	('IMDb Trailers', 'plugin.video.imdb.trailers', 'imdbtrailers.json'),
	('Magneto (AIO Streams)', 'script.module.magneto', 'magneto.json'),
)


class TMDbPlayerDialog(xbmcgui.WindowXMLDialog):
	LIST_ID = 100
	DONE_ID = 101
	CANCEL_ID = 102
	HEADER_ID = 103

	def __init__(self, *args, **kwargs):
		self.heading = kwargs.pop('heading', 'AM Lite - Choose TMDb Helper Players')
		self.all_label = kwargs.pop('all_label', '')
		self.action_label = kwargs.pop('action_label', 'Done')
		self.players = kwargs.pop('players', [])
		self.selected = set()
		self.confirmed = False
		super().__init__(*args, **kwargs)

	def onInit(self):
		self.getControl(self.HEADER_ID).setLabel(self.heading)
		self.getControl(self.DONE_ID).setLabel(self.action_label)
		list_control = self.getControl(self.LIST_ID)
		list_control.reset()

		items = [xbmcgui.ListItem(label=self.all_label)]
		items.extend(xbmcgui.ListItem(label=player['label']) for player in self.players)

		for item in items:
			item.setProperty('selected', 'false')

		list_control.addItems(items)
		self.setFocusId(self.LIST_ID)

	def onClick(self, control_id):
		if control_id == self.LIST_ID:
			position = self.getControl(self.LIST_ID).getSelectedPosition()
			if position < 0:
				return

			list_control = self.getControl(self.LIST_ID)

			if position == 0:
				if 0 in self.selected:
					self.selected.clear()
					selected = 'false'
				else:
					self.selected = set(range(len(self.players) + 1))
					selected = 'true'

				for index in range(len(self.players) + 1):
					list_control.getListItem(index).setProperty('selected', selected)
				return

			if position in self.selected:
				self.selected.remove(position)
				list_control.getListItem(position).setProperty('selected', 'false')
				self.selected.discard(0)
				list_control.getListItem(0).setProperty('selected', 'false')
			else:
				self.selected.add(position)
				list_control.getListItem(position).setProperty('selected', 'true')

				if len(self.selected) == len(self.players):
					self.selected.add(0)
					list_control.getListItem(0).setProperty('selected', 'true')

		elif control_id == self.DONE_ID:
			self.confirmed = True
			self.close()

		elif control_id == self.CANCEL_ID:
			self.close()

	def onAction(self, action):
		if action.getId() in (9, 10, 92, 216, 247, 257):
			self.close()

	def get_selection(self):
		if not self.confirmed:
			return None

		all_selected = 0 in self.selected
		if all_selected:
			return list(self.players), True

		selected_players = [self.players[index - 1] for index in sorted(self.selected) if index > 0]
		return selected_players, False


def _players_destination():
	players_path = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.themoviedb.helper/players/')
	reconfigured_path = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.themoviedb.helper/reconfigured_players/')

	if xbmcvfs.exists(players_path):
		return players_path

	return reconfigured_path


def _show_player_dialog(players, heading, all_label, action_label):
	dialog = TMDbPlayerDialog(
		'acctmgr_tmdbh_players.xml',
		control.addonPath(),
		'Default',
		'1080i',
		heading=heading,
		all_label=all_label,
		action_label=action_label,
		players=players,
	)

	try:
		dialog.doModal()
		return dialog.get_selection()
	finally:
		del dialog


def install_tmdbh_players():
	amgr_icon = os.path.join(control.iconsPath(), 'acctmgr.png')
	src = xbmcvfs.translatePath('special://home/addons/script.module.acctmgr/resources/players/')
	dst = _players_destination()

	if not xbmcvfs.exists(dst):
		xbmcvfs.mkdirs(dst)

	players = []

	for label, addon_id, file_name in PLAYER_FILES:
		if not xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id):
			continue

		src_file = os.path.join(src, file_name)
		dst_file = os.path.join(dst, file_name)

		if xbmcvfs.exists(dst_file):
			continue

		if not xbmcvfs.exists(src_file):
			xbmc.log('AM Lite: Missing TMDb Helper player file %s' % file_name, xbmc.LOGWARNING)
			continue

		players.append({'label': label, 'file_name': file_name, 'src': src_file, 'dst': dst_file})

	if not players:
		control.notification('AM Lite', 'No available players to install!', icon=amgr_icon)
		return False

	selection = _show_player_dialog(
		players,
		'AM Lite - Choose TMDb Helper Players to Install',
		'Select All Players',
		'Install',
	)

	if selection is None:
		return False

	selected_players, all_selected = selection

	copied = 0

	for player in selected_players:
		try:
			if xbmcvfs.copy(player['src'], player['dst']):
				copied += 1
			else:
				shutil.copy2(player['src'], player['dst'])
				copied += 1
		except Exception as e:
			xbmc.log('AM Lite: Failed copying TMDb Helper player %s - %s' % (player['file_name'], e), xbmc.LOGERROR)

	control.notification('AM Lite', 'Installed %s player(s)' % copied, icon=amgr_icon)
	return copied > 0


def delete_tmdbh_players():
	amgr_icon = os.path.join(control.iconsPath(), 'acctmgr.png')
	dst = _players_destination()
	players = []

	for label, addon_id, file_name in PLAYER_FILES:
		dst_file = os.path.join(dst, file_name)

		if not xbmcvfs.exists(dst_file):
			continue

		players.append({'label': label, 'file_name': file_name, 'dst': dst_file})

	if not players:
		control.notification('AM Lite', 'No available players to uninstall!', icon=amgr_icon)
		return False

	selection = _show_player_dialog(
		players,
		'AM Lite - Choose TMDb Helper Players to Uninstall',
		'Select All Players',
		'Uninstall',
	)

	if selection is None:
		return False

	selected_players, all_selected = selection

	if all_selected:
		if not xbmcgui.Dialog().yesno('AM Lite', 'Uninstall all TMDb Helper players?'):
			return False
	else:
		if not xbmcgui.Dialog().yesno('AM Lite', 'Uninstall %s selected player(s)?' % len(selected_players)):
			return False

	deleted = 0

	for player in selected_players:
		try:
			if xbmcvfs.delete(player['dst']):
				deleted += 1
		except Exception as e:
			xbmc.log('AM Lite: Failed deleting TMDb Helper player %s - %s' % (player['file_name'], e), xbmc.LOGERROR)

	control.notification('AM Lite', 'Uninstalled %s player(s)' % deleted, icon=amgr_icon)
	return deleted > 0
