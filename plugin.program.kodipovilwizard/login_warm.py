"""Use the time the profile picker is on screen.

Kodi starts no add-on (not even a start="startup" service) and loads no home
screen before a profile is chosen, so the first seconds after the choice read
everything from storage at once: the skin's windows, the databases, the Python
of every service. This script is launched by the picker's own onload and reads
those same files once, in that order, so the device already holds them in
memory when the profile loads. It only reads: nothing is written, imported,
started or decided here, and it stops the moment the picker closes, so it
never competes with the real loading.

The list is kept to what the profile is sure to open: on a slow box every
needless file costs storage time and memory the real loading must win back.
"""
import os
import re
import time

BUDGET_S = 25.0
BUDGET_BYTES = 128 * 1024 * 1024
CHUNK = 1024 * 1024
DB_MAX = 32 * 1024 * 1024
TEXTURES_MAX = 96 * 1024 * 1024
PY_FILES_MAX = 4000
LANGUAGES = ('resource.language.en_gb', 'resource.language.he_il')
_SKIN = re.compile(r'<setting id="lookandfeel\.skin"[^>]*>([A-Za-z0-9._-]+)</setting>')
_IMPORT = re.compile(r'<import\s+addon="([A-Za-z0-9._-]+)"')
_RES = re.compile(r'<res\s[^>]*\bfolder="([A-Za-z0-9._-]+)"')


def _read_text(path, limit=262144):
    try:
        with open(path, 'rb') as source:
            return source.read(limit).decode('utf-8', 'replace')
    except OSError:
        return ''


def _files(folder, suffixes, deep=False):
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(folder, name)
        if name.lower().endswith(suffixes) and os.path.isfile(path):
            found.append(path)
        elif deep and os.path.isdir(path) and not name.startswith('.'):
            found.extend(_files(path, suffixes, True))
    return found


def skins(master, default):
    """The picker's own skin first, then the skin every other profile uses."""
    names = [default] if default else []
    text = _read_text(os.path.join(master, 'profiles.xml'))
    folders = [master] + [os.path.join(master, d.replace('\\', '/').strip('/'))
                          for d in re.findall(r'<directory[^>]*>([^<]+)</directory>', text)
                          if d.strip() and 'special://masterprofile' not in d]
    for folder in folders:
        found = _SKIN.search(_read_text(os.path.join(folder, 'guisettings.xml'), 1048576))
        if found and found.group(1) not in names:
            names.append(found.group(1))
    return names


def _windows(root):
    """The skin's window files, from the folders its own addon.xml names."""
    folders = _RES.findall(_read_text(os.path.join(root, 'addon.xml'))) or ['xml', '1080i', '720p', '16x9']
    out = []
    for folder in dict.fromkeys(folders):
        out.extend(_files(os.path.join(root, folder), ('.xml',)))
    return out


def compiled_suffix():
    """How this interpreter names a compiled module (Kodi runs optimised:
    'name.cpython-38.opt-1.pyc'), asked of the interpreter itself."""
    import importlib.util
    return os.path.basename(importlib.util.cache_from_source('m.py'))[1:]


def _compiled(root, suffix):
    """Only what was imported before: a module leaves its compiled file behind,
    and that file is what the interpreter opens. Sources without one are not
    opened here -- each open costs milliseconds on a streamer's storage."""
    return _files(root, (suffix,), True)


def services(addons):
    """Add-ons Kodi starts at login, each followed by the modules it imports."""
    order = []
    try:
        names = sorted(os.listdir(addons))
    except OSError:
        return order
    manifests = {name: _read_text(os.path.join(addons, name, 'addon.xml')) for name in names}
    for name in names:
        if 'xbmc.service' in manifests[name] and name not in order:
            order.append(name)
    for name in list(order):
        for needed in _IMPORT.findall(manifests[name]):
            if needed in manifests and manifests[needed] and needed not in order:
                order.append(needed)
    return order


def plan(home, system, master, default_skin, suffix):
    """(stage, path, most bytes to read) in the order the profile will ask."""
    addons = os.path.join(home, 'addons')
    out, late = [], []
    for index, skin in enumerate(skins(master, default_skin)):
        root = next((r for r in (os.path.join(addons, skin), os.path.join(system, 'addons', skin))
                     if os.path.isdir(r)), None)
        if root is None:
            continue
        out.extend(('skin', p, CHUNK) for p in _windows(root))
        if index:
            continue  # one profile is chosen: another profile's skin gets its windows only
        out.extend(('skin', p, 8 * CHUNK) for p in _files(os.path.join(root, 'fonts'), ('.ttf', '.otf')))
        for language in LANGUAGES:
            out.extend(('skin', p, CHUNK) for p in _files(os.path.join(root, 'language', language), ('.po',)))
        late.extend(('textures', p, TEXTURES_MAX) for p in _files(os.path.join(root, 'media'), ('.xbt',)))
    out.extend(('database', p, DB_MAX) for p in _files(os.path.join(master, 'Database'), ('.db',)))
    count = 0
    for name in services(addons):
        for path in _compiled(os.path.join(addons, name), suffix):
            if count >= PY_FILES_MAX:
                break
            out.append(('python', path, 4 * CHUNK))
            count += 1
    return out + late


def warm(items, keep_going, clock=time.monotonic):
    """Read each file once and drop it. Returns (files, bytes, why it ended)."""
    started, files, total = clock(), 0, 0
    for index, (_stage, path, most) in enumerate(items):
        if total >= BUDGET_BYTES or clock() - started >= BUDGET_S:
            return files, total, 'budget'
        if index % 16 == 0 and not keep_going():
            return files, total, 'picker closed'
        try:
            with open(path, 'rb') as source:
                left = most
                while left > 0:
                    piece = source.read(min(CHUNK, left))
                    if not piece:
                        break
                    left -= len(piece)
                    total += len(piece)
                    if len(piece) == CHUNK and left > 0 and not keep_going():
                        return files + 1, total, 'picker closed'
        except OSError:
            continue
        files += 1
    return files, total, 'done'


def main():
    import xbmc
    import xbmcgui
    import xbmcvfs
    window = xbmcgui.Window(10000)
    if window.getProperty('POVIL.LoginWarm'):
        return
    window.setProperty('POVIL.LoginWarm', '1')
    monitor = xbmc.Monitor()
    # The picker paints first; its own textures must not wait behind this.
    if monitor.waitForAbort(0.7):
        return

    def keep_going():
        return (not monitor.abortRequested() and
                xbmc.getCondVisibility('Window.IsVisible(loginscreen)'))

    if not keep_going():
        return
    started = time.monotonic()
    # No thread is started here: Kodi waits for every thread of a script
    # before it ends the interpreter, so nothing here may outlive the reading.
    items = plan(xbmcvfs.translatePath('special://home/'), xbmcvfs.translatePath('special://xbmc/'),
                 xbmcvfs.translatePath('special://masterprofile/'), xbmc.getSkinDir(),
                 compiled_suffix())
    files, total, ended = warm(items, keep_going)
    xbmc.log('[POV IL login warm] {} of {} file(s), {:.1f} MB read in {:.1f}s while the profile picker was open ({})'
             .format(files, len(items), total / 1048576.0, time.monotonic() - started, ended), xbmc.LOGINFO)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:  # never let a warm-up show an error dialog
        try:
            import xbmc
            xbmc.log('[POV IL login warm] skipped: {}'.format(type(error).__name__), xbmc.LOGWARNING)
        except Exception:
            pass
