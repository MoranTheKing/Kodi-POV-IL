import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


PATCH_VERSION = '4'
SETTING_KEY = '_pov_torbox_usage_patch_version'
TORBOX_API_REL = (
    'addons/plugin.video.pov/resources/lib/debrids/torbox_api.py')
TORBOX_REL = 'addons/plugin.video.pov/resources/lib/debrids/torbox.py'

USER_STATS_METHOD = (
    "\n\tdef user_stats(self):\n"
    "\t\turl = 'user/stats'\n"
    "\t\treturn self._get(url, params={'general': 'true', "
    "'bandwidth': 'true', 'bandwidth_grouping': 'day'})\n"
)

HELPERS_BLOCK = r'''
_USAGE_30_KEYS = {
	'30dayusage', '30daysusage', '30daydownloaded',
	'30daysdownloaded', 'thirtydayusage', 'thirtydaysusage',
	'thirtydaydownloaded', 'thirtydaysdownloaded',
	'downloaded30days', 'downloadedlast30days',
	'totaldownloaded30days', 'usage30days', 'monthlyusage',
	'monthlydownloaded', 'bandwidth30days', 'bandwidth',
	'bandwidths', 'last30days',
}

def _normalise_key(key):
	return ''.join(c for c in str(key).lower() if c.isalnum())

def _usage_candidate(value):
	if value in (None, '', [], {}):
		return None
	if isinstance(value, dict):
		for key in ('value', 'total', 'amount', 'size', 'bytes',
					'bytes_downloaded', 'gb', 'used'):
			if key in value:
				candidate = _usage_candidate(value.get(key))
				if candidate not in (None, ''):
					return candidate
		return None
	if isinstance(value, (list, tuple)):
		total = 0.0
		found = False
		for item in value:
			candidate = _usage_candidate(item)
			if isinstance(candidate, (int, float)):
				total += float(candidate)
				found = True
		return total if found else None
	return value

def _find_usage_30(data):
	if not isinstance(data, dict):
		return None
	for key, value in data.items():
		if _normalise_key(key) in _USAGE_30_KEYS:
			candidate = _usage_candidate(value)
			if candidate not in (None, ''):
				return candidate
	for value in data.values():
		if isinstance(value, dict):
			candidate = _find_usage_30(value)
			if candidate not in (None, ''):
				return candidate
	return None

def _format_usage(value):
	if value in (None, ''):
		return ''
	if isinstance(value, str):
		return value
	try:
		value = float(value)
	except Exception:
		return str(value)
	if value > 1024 ** 3:
		return '%.1f GB' % (value / float(1024 ** 3))
	if value > 1024 ** 2:
		return '%.1f MB' % (value / float(1024 ** 2))
	if value.is_integer():
		return '%d GB' % int(value)
	return '%.2f GB' % value

'''

USAGE_LINES = (
    "\t\t\ttry: usage_30 = _find_usage_30(self.user_stats())\n"
    "\t\t\texcept Exception: usage_30 = None\n"
    "\t\t\tif usage_30 in (None, ''):\n"
    "\t\t\t\tusage_30 = _find_usage_30(account_info)\n"
    "\t\t\tusage_30 = _format_usage(usage_30)\n"
    "\t\t\tappend('[B]שימוש 30 יום[/B]: %s' % (usage_30 or 'לא זמין'))\n"
)


def _log(message, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_torbox_usage_patcher: ' + message, level=level)
    except Exception:
        pass


def _path(rel_path):
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath('special://home/' + rel_path)
    except Exception:
        return ''


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _write(path, text):
    tmp = path + '.aitmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    os.replace(tmp, path)


def _patch_api(text):
    if 'def user_stats(self):' in text:
        fixed = re.sub(
            r"return self\._get\(url,\s*params=\{[^}]*'bandwidth'[^}]*\}\)",
            "return self._get(url, params={'general': 'true', "
            "'bandwidth': 'true', 'bandwidth_grouping': 'day'})",
            text,
            count=1,
        )
        return fixed, fixed != text
    needle = "\tdef torrent_info(self, request_id):\n"
    if needle not in text:
        return text, None
    return text.replace(needle, USER_STATS_METHOD + '\n' + needle, 1), True


def _patch_torbox(text):
    changed = False
    if '_USAGE_30_KEYS' not in text:
        needle = 'extensions = supported_video_extensions()\n\n'
        if needle not in text:
            return text, None
        text = text.replace(needle, needle + HELPERS_BLOCK, 1)
        changed = True
    else:
        fixed = text.replace(
            "'monthlydownloaded', 'bandwidth30days', 'last30days',",
            "'monthlydownloaded', 'bandwidth30days', 'bandwidth',\n"
            "\t'bandwidths', 'last30days',")
        fixed = fixed.replace(
            "for key in ('value', 'total', 'amount', 'size', 'bytes', 'gb', 'used'):",
            "for key in ('value', 'total', 'amount', 'size', 'bytes',\n"
            "\t\t\t\t\t'bytes_downloaded', 'gb', 'used'):")
        if fixed != text:
            text = fixed
            changed = True
    usage_block_re = re.compile(
        r"\t\t\tusage_30 = _find_usage_30\(account_info\)\n"
        r"\t\t\tif usage_30 in \(None, ''\):\n"
        r"\t\t\t\ttry: usage_30 = _find_usage_30\(self\.user_stats\(\)\)\n"
        r"\t\t\t\texcept Exception: usage_30 = None\n"
        r"\t\t\tusage_30 = _format_usage\(usage_30\)\n"
        r"\t\t\tif usage_30:\n"
        r"\t\t\t\tappend\('\[B\].*?30.*?\[/B\]: %s' % usage_30\)\n",
        re.DOTALL,
    )
    fixed = usage_block_re.sub(USAGE_LINES, text, count=1)
    if fixed != text:
        text = fixed
        changed = True
    elif 'שימוש 30 יום' not in text:
        needle = "\t\t\tappend('[B]Downloaded[/B]: %s' % account_info['total_downloaded'])\n"
        if needle not in text:
            return text, None
        text = text.replace(needle, needle + USAGE_LINES, 1)
        changed = True
    return text, changed


def _patch_file(rel_path, patcher):
    path = _path(rel_path)
    if not path or not os.path.isfile(path):
        return 'missing'
    try:
        before = _read(path)
        after, changed = patcher(before)
        if changed is None:
            return 'unmatched'
        if not changed:
            return 'already'
        _write(path, after)
        return 'patched'
    except OSError as e:
        _log('{0}: {1}'.format(rel_path, e), level='WARNING')
        return 'io_failed'


def ensure_patched():
    if xbmcvfs is None or kodi_utils is None:
        return 'no_kodi'
    if kodi_utils.get_setting(SETTING_KEY, '') == PATCH_VERSION:
        return 'already_complete'
    api_status = _patch_file(TORBOX_API_REL, _patch_api)
    torbox_status = _patch_file(TORBOX_REL, _patch_torbox)
    if api_status in ('missing', 'unmatched') or torbox_status in ('missing', 'unmatched'):
        return 'skipped:{0},{1}'.format(api_status, torbox_status)
    if api_status in ('io_failed',) or torbox_status in ('io_failed',):
        return 'write_failed'
    kodi_utils.set_setting(SETTING_KEY, PATCH_VERSION)
    if api_status == 'patched' or torbox_status == 'patched':
        return 'patched:{0},{1}'.format(api_status, torbox_status)
    return 'already_complete'
