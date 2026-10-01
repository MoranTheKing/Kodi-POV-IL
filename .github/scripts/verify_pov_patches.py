"""Block a release if current hooks do not fit the verified official POV tree."""
import ast
import hashlib
import importlib.util
import io
import json
import runpy
import sys
import tempfile
import types
import urllib.request
import zipfile
from pathlib import Path


def verify(root, archive=None):
    pin = json.loads((root / '.github/pov-host-migration.json').read_text('utf-8'))
    if archive is None:
        with urllib.request.urlopen(pin['zip'], timeout=30) as response:
            archive = response.read(pin['size'] + 1)
    if len(archive) != pin['size'] or hashlib.sha256(archive).hexdigest() != pin['sha256']:
        raise ValueError('Official POV package size/hash does not match the pin')
    wizard = root / 'plugin.program.kodipovilwizard'
    config = runpy.run_path(str(wizard / 'resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
    config = [entry for entry in config if entry.get('addon_id') == pin['id']]
    xbmc = types.ModuleType('xbmc')
    for index, name in enumerate(('LOGDEBUG', 'LOGINFO', 'LOGWARNING', 'LOGERROR')):
        setattr(xbmc, name, index)
    addon = types.SimpleNamespace(Addon=lambda:types.SimpleNamespace(getSetting=lambda key:''))
    vfs = types.SimpleNamespace(translatePath=lambda path:path)
    logger = types.SimpleNamespace(log=lambda *args, **kwargs:None)
    # The engine is exercised without importing/running an upstream plugin.
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix='pov-host-verify-') as temp, \
         patch.dict(sys.modules, {'xbmc':xbmc, 'xbmcaddon':addon, 'xbmcvfs':vfs,
                                  'resources.libs.common':types.SimpleNamespace(logging=logger)}):
        target = Path(temp)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            if package.testzip():
                raise ValueError('Official POV package failed CRC')
            for name in package.namelist():
                if not name.startswith(pin['id'] + '/') or not (target / name).resolve().is_relative_to(target):
                    raise ValueError('Unexpected package path')
            package.extractall(target)
        host = target / pin['id']
        spec = importlib.util.spec_from_file_location('verify_engine', wizard / 'resources/libs/patch_engine.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Engine(module.PatchEngine):
            @staticmethod
            def _resolve_paths(addon_id, filename):
                return str(host), str(host / filename)

        active = sum(entry.get('enabled', True) for entry in config)
        first = Engine(config).run()
        second = Engine(config).run()
        for stats in (first, second):
            if any(stats.get(key, 0) for key in ('failed', 'missing', 'anchor_missing', 'malformed', 'legacy_host_deferred')):
                raise ValueError('Host patch audit failed: ' + repr(stats))
            completed = sum(stats.get(key, 0) for key in ('applied', 'upgraded', 'skipped_current', 'superseded'))
            if completed != active:
                raise ValueError('Incomplete host patch audit: ' + repr(stats))
        if second['applied'] or second['upgraded'] or second['removed']:
            raise ValueError('Host patches are not idempotent')
        for source in host.rglob('*.py'):
            ast.parse(source.read_text('utf-8-sig'), filename=str(source.relative_to(host)))
        print('Official POV', pin['version'], 'verified:', first, 'repeat:', second)


if __name__ == '__main__':
    verify(Path(__file__).resolve().parents[2], Path(sys.argv[1]).read_bytes() if len(sys.argv) > 1 else None)
