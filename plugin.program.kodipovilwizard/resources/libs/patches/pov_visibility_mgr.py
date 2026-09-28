"""
pov_visibility_mgr.py
Engine V2 decoupled patch module -- Dynamic Visibility Manager.

Single authority for "is this external service connected?" used by:
  * POV navigator.py hook  -> filter_navigator_list(contents, list_name)
  * favourites_generator   -> is_service_active('trakt' | 'tmdb' | 'mdblist' | 'umbrella')
  * (optional) AF3 seeder  -> is_item_visible(widget_path)

Design notes
------------
* NEVER touches navigator.db. Rows are hidden in memory, per request.
* Fail-safe: any internal error returns the ORIGINAL list untouched, so a bug
  here can never blank a widget row. (The only fail-closed path is "service
  state unknown" -> personal rows hidden, public rows always kept.)
* Only PERSONAL (account-bound) POV actions are gated. Public catalogue rows
  (tmdb_movies_popular, trakt_tv_trending, tmdb_tv_networks, genres ...) are
  never touched, otherwise a fresh install would lose most of its home screen.
* Caching: Kodi runs every plugin call in a fresh interpreter, so a plain
  module dict dies with each call. State is therefore cached in TWO tiers:
    L1  module dict          (same process, 10 s)      -> zero I/O
    L2  Home-window property (Kodi session lifetime)   -> survives across
        plugin invocations; invalidated by a cheap settings.xml stat()
        fingerprint, so connecting/disconnecting an account is picked up
        automatically. xbmcaddon.Addon() is instantiated at most once per
        source add-on per rebuild, never per item.
"""
import ast
import json
import os
import re
import time
from urllib.parse import parse_qsl

try:
	import xbmc
except Exception:
	xbmc = None
try:
	import xbmcaddon
except Exception:
	xbmcaddon = None
try:
	import xbmcgui
except Exception:
	xbmcgui = None
try:
	import xbmcvfs
except Exception:
	xbmcvfs = None

_LOG_PREFIX = '[POV Wizard][VisibilityMgr]'
UMBRELLA_ID = 'plugin.video.umbrella'

# --------------------------------------------------------------------------
# Credential sources. A service is "active" when ANY listed setting id holds a
# non-empty value in the FIRST source that has one.
#   1. Account Manager Lite  (source of truth)
#   2. POV's own settings    (the exact ids POV's native My Content menu tests)
# --------------------------------------------------------------------------
STRICT_ACCTMGR = False
_SOURCES = (
	('script.module.acctmgr', {
		'trakt': ('trakt.token', 'trakt.username'),
		'tmdb': ('tmdb.session_id', 'tmdb.account_id'),
		'mdblist': ('mdblist.token', 'mdblist.apikey'),
		'real_debrid': ('realdebrid.token', 'rd.token'),
		'premiumize': ('premiumize.token', 'pm.token'),
		'alldebrid': ('alldebrid.token', 'ad.token'),
		'torbox': ('torbox.token',),
	}),
	('plugin.video.pov', {
		'trakt': ('trakt_user',),
		'tmdb': ('tmdb.account_id',),
		'mdblist': ('mdblist.token',),
		'real_debrid': ('rd.auth',),
		'premiumize': ('pm.account_id',),
		'alldebrid': ('ad.token',),
		'torbox': ('torbox.token',),
	}),
)

_WIN_PROP = 'WIZARD.VisibilityMgr.v2'
_L1_TTL = 10.0          # seconds a process trusts its own snapshot
_L2_TTL_NOFP = 60.0     # seconds L2 is trusted when no settings.xml can be stat()ed
_mem = {}

# --------------------------------------------------------------------------
# Personal-action classification. Mirrors POV's own navigator.my_content():
# only account-bound actions/modes are listed. (service, action_re, mode_re)
# --------------------------------------------------------------------------
_RULES = (
	('trakt',
	 re.compile(r'^trakt_(my_|collection|watchlist|favorites|recommendations|progress|dropped)'),
	 re.compile(r'^(navigator\.trakt_(lists|watchlists|collections|favorites|recommendations)|trakt\.trakt_account_info)$')),
	('tmdb',
	 re.compile(r'^tmdb_(my_|favorites$|watchlist$\vert{}recommendations$)'),
	 re.compile(r'^build_tmdb_list\.')),
	('mdblist',
	 re.compile(r'^mdblist_'),
	 re.compile(r'^(build_mdbl_list\.|mdblist\.|build_my_calendar_mdbl$)')),
)

# Canonical MDBList rows (routing rescued from the legacy AF3 patcher: POV's
# native `mdblist_watchlist` action, movie/tv distinguished by `mode`).
# Injected in memory into the personal folders only when MDBList is connected
# and the shipped navigator.db does not already carry the row.
_MDBLIST_ROWS = {
	'FENtastic - סרטים - איזור אישי': {
		'action': 'mdblist_watchlist', 'category_name': 'MDBList Watchlist',
		'iconImage': 'mdblist.png', 'mode': 'build_movie_list',
		'name': '[B]הסרטים שלי (MDBList)[/B]'},
	'FENtastic - סדרות - איזור אישי': {
		'action': 'mdblist_watchlist', 'category_name': 'MDBList Watchlist',
		'iconImage': 'mdblist.png', 'mode': 'build_tvshow_list',
		'name': '[B]הסדרות שלי (MDBList)[/B]'},
}


def _log(msg, level=None):
	if xbmc is None:
		return
	try:
		xbmc.log('%s %s' % (_LOG_PREFIX, msg), xbmc.LOGWARNING if level is None else level)
	except Exception:
		pass

def _trigger_favourites_refresh():
	"""Dynamically rebuilds favourites.xml and reloads the skin when a connection changes."""
	if xbmc is None:
		return
	try:
		import os
		import importlib.util

		current_skin = xbmc.getSkinDir()

		addon_path = xbmcvfs.translatePath(
			xbmcaddon.Addon('plugin.program.orderfavourites-hebrew').getAddonInfo('path')
		)
		module_file = os.path.join(addon_path, 'favourites_generator.py')

		if not os.path.isfile(module_file):
			_log('Auto-refresh: generator not found at %s' % module_file)
			return

		spec = importlib.util.spec_from_file_location('povil_favourites_generator', module_file)
		generator = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(generator)

		if generator.generate_favourites_xml(current_skin) is None:
			_log('Auto-refresh skipped: installed favourites could not be merged safely')
			return

		xbmc.executebuiltin('ReloadSkin()')
		_log('Auto-refresh: Favourites regenerated and skin reloaded for %s' % current_skin)
	except Exception as e:
		_log('Auto-refresh failed: %s' % e)

# ---------------------------------------------------------------------------
# Session cache
# ---------------------------------------------------------------------------
def _home():
	try:
		return xbmcgui.Window(10000)
	except Exception:
		return None


def _stat_token(addon_id):
	try:
		path = xbmcvfs.translatePath('special://profile/addon_data/%s/settings.xml' % addon_id)
		st = os.stat(path)
		return '%d:%d' % (st.st_mtime_ns, st.st_size)
	except Exception:
		return '-'


def _fingerprint():
	parts = [_stat_token(addon_id) for addon_id, _ in _SOURCES]
	return '' if all(p == '-' for p in parts) else '|'.join(parts)


def _read_states():
	"""One Addon() instantiation per source add-on. Never called per item."""
	states = {
		'trakt': False, 'tmdb': False, 'mdblist': False,
		'real_debrid': False, 'premiumize': False, 'alldebrid': False, 'torbox': False
	}
	if xbmcaddon is None:
		return states
	sources = _SOURCES[:1] if STRICT_ACCTMGR else _SOURCES
	for addon_id, id_map in sources:
		try:
			addon = xbmcaddon.Addon(addon_id)
		except Exception as e:
			_log('cannot open %s: %r' % (addon_id, e))
			continue
		for svc, setting_ids in id_map.items():
			if states[svc]:
				continue
			for sid in setting_ids:
				try:
					if (addon.getSetting(sid) or '').strip():
						states[svc] = True
						break
				except Exception:
					pass
	return states


def _is_fresh(cached, fp, now):
	if fp:
		return cached.get('fp') == fp
	return (now - cached.get('ts', 0)) < _L2_TTL_NOFP


def _snapshot():
	now = time.time()
	mem = _mem.get('snap')
	if mem and (now - mem['checked']) < _L1_TTL:
		return mem
	fp = _fingerprint()
	win = _home()
	snap = None
	old_svc = None

	if win is not None:
		try:
			raw = win.getProperty(_WIN_PROP)
			cached = json.loads(raw) if raw else None
			if cached:
				old_svc = cached.get('svc')
				if _is_fresh(cached, fp, now):
					snap = cached
		except Exception:
			snap = None
	if snap is None:
		new_svc = _read_states()
		snap = {'fp': fp, 'ts': now, 'svc': new_svc}
		_log('state rebuilt: %s' % (snap['svc'],), getattr(xbmc, 'LOGINFO', None))
		if win is not None:
			try:
				win.setProperty(_WIN_PROP, json.dumps(snap))
			except Exception:
				pass

		if old_svc is not None and old_svc != new_svc:
			_log('Service connection state changed! Triggering UI refresh.')
			_trigger_favourites_refresh()

	snap = dict(snap)
	snap['checked'] = now
	_mem['snap'] = snap
	return snap


def invalidate():
	"""Drop both cache tiers. Call right after an account is (dis)connected."""
	_mem.clear()
	win = _home()
	if win is not None:
		try:
			win.clearProperty(_WIN_PROP)
		except Exception:
			pass


def _umbrella_installed():
	mem = _mem.get('umbrella')
	now = time.time()
	if mem and (now - mem[0]) < _L1_TTL:
		return mem[1]
	try:
		ok = bool(xbmc.getCondVisibility('System.HasAddon(%s)' % UMBRELLA_ID))
	except Exception:
		ok = False
	_mem['umbrella'] = (now, ok)
	return ok


def is_service_active(service):
	"""True when `service` is usable.
	Empty / unknown names mean "no requirement" (parity with the old
	favourites_generator._check_condition, which returned True)."""
	svc = (service or '').strip().lower()

	# Prefix with '!' to negate (e.g., '!trakt' returns True only if Trakt is disconnected).

	if svc.startswith('!'):
		return not is_service_active(svc[1:])

	if svc == 'umbrella':
		return _umbrella_installed()
	if svc in ('trakt', 'tmdb', 'mdblist', 'real_debrid', 'premiumize', 'alldebrid', 'torbox'):
		return bool(_snapshot()['svc'].get(svc, False))
	if svc:
		_log('unknown service %r treated as active' % svc)
	return True


# ---------------------------------------------------------------------------
# Payload parsing (never eval())
# ---------------------------------------------------------------------------
def _loads(text):
	try:
		return ast.literal_eval(text)
	except Exception:
		pass
	try:
		return json.loads(text)
	except Exception:
		return None


def _fields(item):
	"""-> (action, mode) for a dict row, a dict/JSON repr string, or a POV
	plugin:// URL (also inside ActivateWindow(...)/RunPlugin(...) wrappers)."""
	if isinstance(item, dict):
		return str(item.get('action') or ''), str(item.get('mode') or '')
	if isinstance(item, str):
		s = item.strip()
		if s[:1] in ('{', '['):
			obj = _loads(s)
			return _fields(obj) if isinstance(obj, dict) else ('', '')
		if 'plugin://' in s and 'plugin.video.pov' not in s:
			return '', ''
		query = s.split('?', 1)[1] if '?' in s else s
		params = dict(parse_qsl(query, keep_blank_values=True))
		return params.get('action', ''), params.get('mode', '')
	return '', ''


def service_of(item):
	"""Which external service does this row require? None = public/local."""
	action, mode = _fields(item)
	if not action and not mode:
		return None
	for svc, action_re, mode_re in _RULES:
		if (action and action_re.match(action)) or (mode and mode_re.match(mode)):
			return svc
	return None


def is_item_visible(item):
	svc = service_of(item)
	return svc is None or is_service_active(svc)


def _coerce_list(value):
	if isinstance(value, (list, tuple)):
		return list(value)
	if isinstance(value, str):
		obj = _loads(value.strip())
		if isinstance(obj, (list, tuple)):
			return list(obj)
	return None


# ---------------------------------------------------------------------------
# Hook entry point (POV navigator.build_shortcut_folder_list)
# ---------------------------------------------------------------------------
def filter_navigator_list(list_items, list_name=None):
	"""Return `list_items` without rows whose service is not connected, plus
	the MDBList row when connected. Input is never mutated; on ANY failure the
	original object is returned unchanged."""
	try:
		items = _coerce_list(list_items)
		if items is None:
			return list_items
		states = _snapshot()['svc']
		kept = []
		for it in items:
			svc = service_of(it)
			if svc is None or states.get(svc, False):
				kept.append(it)
		removed = len(items) - len(kept)
		if removed:
			_log('%r: hid %d unauthorised row(s)' % (list_name, removed), getattr(xbmc, 'LOGDEBUG', None))
		return kept
	except Exception as e:
		_log('filter_navigator_list failed, list left untouched: %r' % (e,))
		return list_items
