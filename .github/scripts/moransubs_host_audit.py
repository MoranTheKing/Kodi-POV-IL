"""Run MoranSubs' patchers for one host add-on on a copy of its official tree.

Usage: moransubs_host_audit.py MORANSUBS_DIR ADDON_ID TREE

Why (17 Nov 2026): Arctic Fuse 3, Idan Plus and POV update themselves on users'
devices, and MoranSubs edits files inside them at start-up. Until now a new
upstream version only opened an issue that asked a person to re-run the
patchers; nothing ran them. This runs them: each patcher twice on a temporary
copy of the official tree (the second run must not patch again), with Kodi's
modules stubbed and network access refused.

Umbrella keeps its own audit (moransubs_umbrella_audit.py): its contract is
read from repair_hosts.py, the list devices run after an Umbrella update.

A status is judged the way a release would be, not the way a device is: on a
device "unmatched" means "do not retry"; here it means an anchor moved and a
person has to look. Prints one JSON line:

    {"addon": ..., "version": ..., "ok": true/false,
     "steps": [[module, function, first, second, "ok" | reason], ...]}

Exit 0 whenever the audit itself ran (read "ok"); exit 1 when it could not.
"""
import importlib
import json
import re
import shutil
import socket
import sys
import tempfile
import traceback
import types
from pathlib import Path

# The patchers devices run for each host (service.py's start-up pass and
# repair_af3.py). af3_home_patcher is not here: it rebuilds the home menu
# through the running skin and cannot run without Kodi.
HOSTS = {
    'skin.arctic.fuse.3': (
        ('af3_dialog_subtitles_patcher', 'ensure_patched'),
        ('af3_osd_tap_close_patcher', 'ensure_patched'),
        ('af3_search_pov_patcher', 'ensure_patched'),
        ('af3_discover_pov_patcher', 'ensure_patched'),
    ),
    'plugin.video.idanplus': (
        ('idanplus_youtube_id_patcher', 'ensure_patched'),
        ('idanplus_vod_patcher', 'ensure_patched'),
        ('idanplus_channels_patcher', 'ensure_patched'),
    ),
    'plugin.video.pov': (
        ('pov_hebrew_genres_patcher', 'ensure_patched'),
        ('pov_hebrew_ui_patcher', 'ensure_patched'),
        ('pov_scraper_settings_patcher', 'ensure_patched'),
    ),
}
# Not listed, on purpose: pov_widget_crash_guard, pov_language_invoker_guard and
# update_nag_patcher act on what the running Kodi reports (a setting, the
# reuse-invoker state, installed versions); with a stubbed Kodi they can only
# answer "nothing to do", which would look like a check and be none.
#
# The first run did its work or found it already done upstream.
DONE = {'patched', 'repatched', 'patched_rebuilt', 'already_patched', 'already',
        'unchanged', 'upstream', 'healed', 'ok',
        'missing'}      # missing: no per-profile data file to heal (a new profile)
# The second run found nothing left to do.
SETTLED = DONE - {'patched', 'repatched', 'patched_rebuilt', 'healed'}


def _parts(status):
    """A patcher of several steps reports "name=status name=status"."""
    found = re.findall(r'[\w.]+=([\w]+)', status)
    return found or [status]


def verdict(first, second):
    if not all(part in DONE for part in _parts(first)):
        return 'first run: ' + first
    if not all(part in SETTLED for part in _parts(second)):
        return 'second run patched again or failed: ' + second
    return 'ok'


def _deny(*args, **kwargs):
    raise OSError('network access refused in the MoranSubs host audit')


def stub_kodi(home, profile, addon_id):
    def translate(path):
        path = str(path)
        for prefix, base in (('special://home/', home), ('special://profile/', profile),
                             ('special://masterprofile/', profile), ('special://userdata/', profile),
                             ('special://skin/', home / 'addons' / 'skin.arctic.fuse.3')):
            if path.startswith(prefix):
                return str(base / path[len(prefix):])
        return path

    settings = {}

    class Addon:
        def __init__(self, id=None, *args, **kwargs):
            self.id = id or 'service.subtitles.kodipovilai'

        def getSetting(self, key):
            return settings.get((self.id, key), '')

        def setSetting(self, key, value):
            settings[(self.id, key)] = str(value)

        def getAddonInfo(self, key):
            if key == 'path':
                return translate('special://home/addons/{0}/'.format(self.id))
            if key == 'profile':
                return translate('special://profile/addon_data/{0}/'.format(self.id))
            return self.id if key == 'id' else ''

        def getLocalizedString(self, number):
            return ''

    installed = {addon_id, 'plugin.video.pov'}
    monitor = types.SimpleNamespace(abortRequested=lambda: False, waitForAbort=lambda seconds=0: False)

    def cond(condition):
        match = re.match(r'System\.(?:HasAddon|AddonIsEnabled)\(([^)]+)\)', condition or '')
        return bool(match and match.group(1) in installed)

    sys.modules['xbmc'] = types.SimpleNamespace(
        LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3, log=lambda *a, **k: None,
        getCondVisibility=cond, getInfoLabel=lambda label: '',
        executebuiltin=lambda *a, **k: None, executeJSONRPC=lambda request: '{"result": {}}',
        getSkinDir=lambda: addon_id if addon_id.startswith('skin.') else 'skin.estuary',
        sleep=lambda ms: None, translatePath=translate, Monitor=lambda: monitor,
        Player=lambda: types.SimpleNamespace(isPlaying=lambda: False))
    class File:
        def __init__(self, path, mode='r'):
            self.path, self.mode = Path(translate(path)), mode
            if 'w' in mode:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_bytes(b'')

        def read(self):
            return self.path.read_text('utf-8', 'replace')

        def readBytes(self):
            return bytearray(self.path.read_bytes())

        def write(self, data):
            with open(self.path, 'ab') as handle:
                handle.write(data.encode('utf-8') if isinstance(data, str) else bytes(data))
            return True

        def size(self):
            return self.path.stat().st_size

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _delete(path):
        target = Path(translate(path))
        if target.is_file():
            target.unlink()
            return True
        return False

    def _rename(source, target):
        Path(translate(source)).replace(Path(translate(target)))
        return True

    def _copy(source, target):
        shutil.copyfile(translate(source), translate(target))
        return True

    sys.modules['xbmcvfs'] = types.SimpleNamespace(
        File=File, delete=_delete, rename=_rename, copy=_copy,
        translatePath=translate, exists=lambda path: Path(translate(path)).exists(),
        mkdirs=lambda path: Path(translate(path)).mkdir(parents=True, exist_ok=True) or True,
        listdir=lambda path: ([p.name for p in Path(translate(path)).iterdir() if p.is_dir()],
                              [p.name for p in Path(translate(path)).iterdir() if p.is_file()]))
    sys.modules['xbmcaddon'] = types.SimpleNamespace(Addon=Addon)
    sys.modules['xbmcgui'] = types.SimpleNamespace(
        Window=lambda window_id: types.SimpleNamespace(
            getProperty=lambda key: '', setProperty=lambda key, value: None, clearProperty=lambda key: None),
        Dialog=lambda: types.SimpleNamespace(notification=lambda *a, **k: None, ok=lambda *a, **k: True))


def addon_version(tree):
    try:
        text = (Path(tree) / 'addon.xml').read_text('utf-8', 'replace')
        return re.search(r'<addon\b[^>]*\bversion="([^"]+)"', text, re.S).group(1)
    except (OSError, AttributeError):
        return ''


def main(moransubs, addon_id, tree):
    steps = HOSTS[addon_id]
    socket.socket.connect = _deny
    socket.create_connection = _deny
    socket.getaddrinfo = _deny
    work = Path(tempfile.mkdtemp(prefix='moransubs-host-audit-'))
    try:
        home, profile = work / 'home', work / 'profile'
        shutil.copytree(tree, home / 'addons' / addon_id)
        (profile / 'addon_data' / addon_id).mkdir(parents=True)
        stub_kodi(home, profile, addon_id)
        sys.path.insert(0, str(moransubs))
        results = []
        for module_name, function in steps:
            outcome = []
            for _ in range(2):
                try:
                    module = importlib.import_module('resources.lib.' + module_name)
                    outcome.append(str(getattr(module, function)()))
                except Exception as exc:
                    outcome.append('error: ' + traceback.format_exception_only(type(exc), exc)[-1].strip())
            results.append([module_name, function] + outcome + [verdict(*outcome)])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({'addon': addon_id, 'version': addon_version(tree),
                      'ok': all(step[4] == 'ok' for step in results), 'steps': results}))


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[2] not in HOSTS:
        sys.stderr.write(__doc__)
        sys.exit(1)
    main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
