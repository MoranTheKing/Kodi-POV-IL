"""Run MoranSubs' Umbrella patchers on a copy of an official Umbrella tree.

Usage: moransubs_umbrella_audit.py MORANSUBS_DIR UMBRELLA_TREE

Why (22 Oct 2026): the release automation moved the Umbrella pin to 6.7.95
after checking only the Wizard's hooks. 6.7.95 had moved its English strings,
MoranSubs' Hebrew menu installer skipped, and every device got English menus.
The pin now also needs MoranSubs' patchers to fit.

The patchers and the statuses that count as good are read from MoranSubs'
own repair_hosts.py -- the list devices run after an Umbrella update -- so
this can never check a different contract than the one that ships. Each runs
twice on a temporary copy (the second run must not patch again). Kodi's
modules are stubbed; network access is refused, so a patcher that would
reach out fails here instead of calling a real service from CI.

Prints one JSON line: {"good": [...], "steps": [[module, function, first,
second], ...]}. Exit 1 when the runner itself cannot work.
"""
import ast
import importlib
import json
import shutil
import socket
import sys
import tempfile
import traceback
import types
from pathlib import Path


def repair_contract(moransubs):
    """[(module, function)] and the good statuses from repair_hosts.py."""
    tree = ast.parse((moransubs / 'repair_hosts.py').read_text('utf-8'))
    loops, good = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple):
            names = [item.elts[0].value for item in node.iter.elts
                     if isinstance(item, ast.Tuple) and item.elts
                     and isinstance(item.elts[0], ast.Constant) and isinstance(item.elts[0].value, str)]
            if not any(name.startswith('umbrella_') for name in names):
                continue
            # Every entry must read cleanly: a skipped one would be a patcher
            # devices run and this audit silently does not.
            pairs = [tuple(elt.value for elt in item.elts) for item in node.iter.elts
                     if isinstance(item, ast.Tuple) and len(item.elts) == 2
                     and all(isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                             for elt in item.elts)]
            if len(pairs) != len(node.iter.elts):
                raise ValueError('repair_hosts.py: an Umbrella patcher entry is not a plain '
                                 '(module, function) pair')
            loops.append(pairs)
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                getattr(node.targets[0], 'id', '') == 'good' and isinstance(node.value, ast.Set)):
            good = {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)}
    if len(loops) != 1 or not good:
        raise ValueError('repair_hosts.py: expected one Umbrella patcher list and the good '
                         'statuses, found {} list(s)'.format(len(loops)))
    return loops[0], good


def _deny(*args, **kwargs):
    raise OSError('network access refused in the MoranSubs Umbrella audit')


def stub_kodi(home, profile):
    def translate(path):
        path = str(path)
        for prefix, base in (('special://home/', home), ('special://profile/', profile),
                             ('special://masterprofile/', profile), ('special://userdata/', profile)):
            if path.startswith(prefix):
                return str(base / path[len(prefix):])
        return path

    class Addon:
        def __init__(self, *args, **kwargs):
            pass

        def getSetting(self, key):
            return ''

        def setSetting(self, key, value):
            pass

        def getAddonInfo(self, key):
            return translate('special://home/addons/plugin.video.umbrella/') if key == 'path' else ''

    monitor = types.SimpleNamespace(abortRequested=lambda: False, waitForAbort=lambda seconds=0: False)
    sys.modules['xbmc'] = types.SimpleNamespace(
        LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3, log=lambda *a, **k: None,
        getCondVisibility=lambda condition: False, getInfoLabel=lambda label: '',
        executebuiltin=lambda action: None, getSkinDir=lambda: 'skin.estuary',
        sleep=lambda ms: None, translatePath=translate, Monitor=lambda: monitor)
    sys.modules['xbmcvfs'] = types.SimpleNamespace(translatePath=translate,
                                                   exists=lambda path: Path(translate(path)).exists())
    sys.modules['xbmcaddon'] = types.SimpleNamespace(Addon=Addon)
    sys.modules['xbmcgui'] = types.SimpleNamespace(Window=lambda window_id: types.SimpleNamespace(
        getProperty=lambda key: '', setProperty=lambda key, value: None, clearProperty=lambda key: None))


def main(moransubs, umbrella):
    steps, good = repair_contract(moransubs)
    socket.socket.connect = _deny
    socket.create_connection = _deny
    socket.getaddrinfo = _deny
    work = Path(tempfile.mkdtemp(prefix='moransubs-umbrella-audit-'))
    try:
        home, profile = work / 'home', work / 'profile'
        shutil.copytree(umbrella, home / 'addons' / 'plugin.video.umbrella')
        profile.mkdir()
        stub_kodi(home, profile)
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
            results.append([module_name, function] + outcome)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({'good': sorted(good), 'steps': results}))


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
