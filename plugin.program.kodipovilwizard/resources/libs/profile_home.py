"""Prepare an inactive profile's current home before Kodi reads its cache."""
import importlib.util
import os
import xml.etree.ElementTree as ET

import xbmc
import xbmcvfs

from resources.libs import profile_store
from resources.libs.patches import pov_visibility_mgr


def _module(name, path):
    spec = importlib.util.spec_from_file_location('povil_profile_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ProfileFiles:
    """Redirect only this local writer, never Kodi's global profile paths."""
    def __init__(self, target):
        self.target = target

    def translatePath(self, path):
        prefix = 'special://profile/'
        if path.startswith(prefix):
            return profile_store._inside(self.target, path[len(prefix):])
        return xbmcvfs.translatePath(path)

    def __getattr__(self, name):
        return getattr(xbmcvfs, name)


class _Connections:
    def __init__(self, target):
        self.services = {}
        for addon, groups in pov_visibility_mgr._SOURCES:
            path = os.path.join(target, 'addon_data', addon, 'settings.xml')
            values = ({row.get('id'): (row.text or '').strip()
                       for row in ET.parse(path).getroot().findall('setting')}
                      if os.path.isfile(path) else {})
            for service, keys in groups.items():
                if any(values.get(key) for key in keys):
                    self.services[service] = True

    def is_service_active(self, service):
        if service.startswith('!'):
            return not self.is_service_active(service[1:])
        if service == 'umbrella':
            return bool(xbmc.getCondVisibility('System.HasAddon(plugin.video.umbrella)'))
        return bool(self.services.get(service))


def prepare(master, profile):
    target = profile_store.profile_path(master, profile)
    active = os.path.realpath(xbmcvfs.translatePath('special://profile/'))
    if profile['id'] == 0 or target == active:
        raise ValueError('Home must be prepared before loading the profile')
    if os.path.isfile(os.path.join(target, 'kodipovil.profile_home_ready')):
        return
    addons = xbmcvfs.translatePath('special://home/addons/')
    generator = _module('favourites', os.path.join(
        addons, 'plugin.program.orderfavourites-hebrew', 'favourites_generator.py'))
    generator.FAVOURITES_PATH = os.path.join(target, 'favourites.xml')
    generator.STATE_PATH = os.path.join(target, 'addon_data',
        'plugin.program.orderfavourites-hebrew', 'favourites_state.json')
    generator._VIS_MGR = _Connections(target)
    if generator.generate_favourites_xml('skin.povil.nox', merge=True, write=True) is None:
        raise ValueError('Profile favourites could not be prepared')
    base = os.path.join(addons, 'service.subtitles.kodipovilai', 'resources', 'lib')
    tonight = _module('tonight', os.path.join(base, 'tonight', 'entrypoints.py'))
    path = os.path.join(target, 'favourites.xml')
    with open(path, encoding='utf-8') as source:
        before = source.read()
    after = tonight.insert(before)
    if before != after:
        from resources.libs.parental_profiles import atomic_write
        atomic_write(path, after.encode('utf-8'))
    recent = _module('recent', os.path.join(base, 'recent_updates_tile_patcher.py'))
    recent.xbmcvfs = _ProfileFiles(target)
    result = recent.ensure_patched()
    if result not in ('seeded', 'already_present', 'user_removed', 'already_seen'):
        raise ValueError('Profile update shortcut could not be prepared: ' + result)
