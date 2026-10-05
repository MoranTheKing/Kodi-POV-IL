"""Build defaults for Kodi-owned profiles, without copying personal accounts.

Kodi owns profiles.xml and the in-memory profile list. This module never edits
that file: native creation/deletion/locks remain authoritative. Only missing
build files are seeded, and only beneath the registered profile directory.
"""
import hashlib
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile


BOOTSTRAP_SHA256 = '20f3f23b5571bc48be7313096e144fd01e903b346b050ca9a7a2899a92963f85'
WIZARD = 'plugin.program.kodipovilwizard'


def registered_profiles(master):
    root = ET.parse(os.path.join(master, 'profiles.xml')).getroot()
    result = []
    for element in root.findall('profile'):
        result.append(dict(id=int(element.findtext('id', '-1')),
                           name=element.findtext('name', ''),
                           directory=element.findtext('directory', ''),
                           lockmode=int(element.findtext('lockmode', '0')),
                           protected=(int(element.findtext('lockmode', '0')) > 0 and
                                      element.findtext('lockcode', '') not in ('', '-')),
                           locksettings=int(element.findtext('locksettings', '0')),
                           lockfiles=element.findtext('lockfiles') == 'true',
                           lockaddonmanager=element.findtext('lockaddonmanager') == 'true'))
    return result


def profile_path(master, profile):
    if profile['id'] == 0:
        return os.path.realpath(master)
    directory = profile['directory'].replace('\\', '/')
    if not directory or '://' in directory:
        raise ValueError('Unsupported profile directory')
    base = os.path.realpath(master)
    dest = os.path.realpath(os.path.join(base, directory))
    if os.path.commonpath([base, dest]) != base or dest == base:
        raise ValueError('Profile directory is outside userdata')
    return dest


def _inside(root, relative):
    if (not relative or '\\' in relative or ':' in relative or
            relative.startswith('/') or any(p in ('', '.', '..') for p in relative.split('/'))):
        raise ValueError('Invalid build profile path')
    base = os.path.realpath(root)
    dest = os.path.realpath(os.path.join(base, *relative.split('/')))
    if os.path.commonpath([base, dest]) != base or dest == base:
        raise ValueError('Build profile path escapes its directory')
    return dest


def write_missing(root, relative, content):
    """Create without replacing a concurrent/user file; clean partial failures."""
    path = _inside(root, relative)
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    path = _inside(root, relative)  # validate again after mkdir (symlinks)
    fd, tmp = tempfile.mkstemp(prefix='.profile-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        except OSError:
            # Android emulated storage can prohibit hardlinks. Exclusive
            # creation still never overwrites an existing account/settings.
            try:
                fh = open(path, 'xb')
            except FileExistsError:
                return False
            try:
                with fh:
                    fh.write(content)
                    fh.flush()
                    os.fsync(fh.fileno())
            except BaseException:
                os.unlink(path)
                raise
        return True
    finally:
        os.unlink(tmp)


def seed_profile(master, profile, archive):
    """Repair a secondary profile using shipped defaults, never master tokens.

    Excludes watched/history/cache DBs and per-device advancedsettings. The
    receipt is written last, only when the master build is provisioned. An
    interrupted seed can resume, preserving every existing target setting.
    """
    target = profile_path(master, profile)
    if profile['id'] == 0:
        return False
    if not os.path.isfile(os.path.join(master, 'kodipovil.provisioned')):
        raise ValueError('Complete the master build installation first')
    with open(archive, 'rb') as fh:
        if hashlib.sha256(fh.read()).hexdigest() != BOOTSTRAP_SHA256:
            raise ValueError('Profile defaults failed integrity verification')
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        version = json.loads(zf.read('config_policy.json')).get('config_version', '')
        # Keep installed device settings supplied by native "copy from master";
        # fresh native settings are also respected. Apply only build defaults.
        for name in zf.namelist():
            allowed = (name == 'favourites.xml' or name == 'sources.xml' or
                       name.startswith('keymaps/') or
                       (name.startswith('addon_data/') and name.endswith('/settings.xml')))
            if allowed:
                content = zf.read(name)
                if name == 'favourites.xml':
                    favourites = ET.fromstring(content)
                    tile = ET.Element('favourite', {
                        'name': '[B]מי צופה? — פרופילים[/B]',
                        'thumb': 'special://home/addons/plugin.program.kodipovilwizard/resources/skins/Default/media/DefaultUser.png'})
                    tile.text = 'RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=profiles)'
                    if not any('mode=profiles' in (row.text or '') for row in favourites):
                        favourites.insert(1, tile)
                    content = ET.tostring(favourites, encoding='utf-8', xml_declaration=True)
                write_missing(target, name, content)
        # Native "start fresh" does not save guisettings until first login.
        # Seed the verified build defaults before that login, so the new
        # profile starts in NOX with Hebrew/subtitles instead of bare Kodi.
        # Existing native/user settings are never replaced.
        if not os.path.isfile(_inside(target, 'guisettings.xml')):
            write_missing(target, 'kodipovil.profile_gui_defaults.xml', zf.read('guisettings.xml'))
        write_missing(target, 'guisettings.xml', zf.read('guisettings.xml'))
        ET.parse(_inside(target, 'guisettings.xml'))
    # Kodi uses the target add-on settings on next LoadProfile. Do not clone
    # the master's complete wizard settings (queues, update receipts, flags).
    defaults = dict(buildname='Kodi POV IL - FENtastic', installed='true',
                    buildversion='0.1.45', config_applied_version=str(version),
                    build_skin_switch_notifcation_dismiss='true')
    settings = ET.Element('settings', {'version': '2'})
    for key, value in defaults.items():
        ET.SubElement(settings, 'setting', {'id': key}).text = value
    write_missing(target, 'addon_data/' + WIZARD + '/settings.xml',
                  ET.tostring(settings, encoding='utf-8', xml_declaration=True))
    write_missing(target, 'kodipovil.provisioned', str(version).encode('utf-8'))
    return True


def lone_unlocked(profiles):
    """A login screen can be removed automatically only without any lock."""
    return (len(profiles) == 1 and profiles[0]['id'] == 0 and
            profiles[0]['lockmode'] == 0)
