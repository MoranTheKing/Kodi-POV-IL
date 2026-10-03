"""Bounded, non-network repair after a host addon updates in this session."""
import importlib
import json
import sys
from resources.lib import kodi_utils

def repair():
    results = {}
    for name, function in (
            ('umbrella_mdblist_token_patcher', 'ensure_patched'),
            ('umbrella_mdblist_sync_patcher', 'ensure_patched'),
            ('umbrella_subtitle_match_patcher', 'ensure_patched'),
            ('umbrella_tmdb_apikey_patcher', 'ensure_patched'),
            ('umbrella_source_ux_patcher', 'ensure_patched'),
            ('umbrella_language_patcher', 'ensure_patched'),
            ('umbrella_hebrew_ui_patcher', 'ensure_patched'),
            ('umbrella_setup_patcher', 'ensure_source_name_published'),
            ('umbrella_setup_patcher', 'ensure_personal_list_order')):
        try:
            module = importlib.import_module('resources.lib.' + name)
            results[name + '.' + function] = getattr(module, function)()
        except Exception:
            results[name + '.' + function] = 'failed'
    kodi_utils.log('Host-update repair: {}'.format(results))
    return results

results = repair()
if len(sys.argv) > 1 and sys.argv[1].startswith('kodipovil.host_repair.'):
    import xbmcgui
    good = {'patched', 'repatched', 'already_patched', 'unchanged', 'upstream'}
    xbmcgui.Window(10000).setProperty(sys.argv[1], json.dumps({
        'ok': bool(results) and all(value in good for value in results.values())}))
