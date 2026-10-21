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


SESSION_MODULES = ('session', 'modules.session')
_CLIENTS = ('session', 'http')


def _session_digest(root):
    """SESSION_SHA256 of the Wizard's shared-HTTP proxy, read without importing it."""
    source = (root / 'plugin.program.kodipovilwizard/resources/libs/patches/pov_http_session.py').read_text('utf-8')
    for node in ast.parse(source).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                getattr(node.targets[0], 'id', '') == 'SESSION_SHA256'):
            return node.value.value
    raise ValueError('pov_http_session.py has no SESSION_SHA256')


def audit_session_callers(host, digest):
    """Problems POV's own files would hit through the Wizard's shared-HTTP proxy.

    The proxy (pov_http_session) stands in for POV's session module when that
    file matches the verified digest. The digest pins the module, not how the
    rest of POV uses it, and the proxy imitates only these shapes:
      session / http        -- only as `X.attr` (any attribute, call or store);
      HTTPAdapter(...)      -- only as an argument of `session.mount(...)`;
      Retry(...)            -- only inside HTTPAdapter(...), directly or through
                               a module-level name used nowhere else.
    Anything else (passing the client object around, `with session:`,
    isinstance on HTTPAdapter/Retry, importing the module object itself in
    any spelling -- `import modules.session`, `from modules import session`,
    `from . import session` -- or `import *` from it) would break on devices
    instead of falling back to stock POV, so it stops the pin. Relative
    imports are resolved against the importing file's folder.
    Not covered (accepted): importlib.import_module('modules.session') and a
    client re-exported through another module (`from indexers.x import session`).
    Returns [] when no session file matches the digest: the proxy stays off."""
    files = [path for path in host.rglob('session.py')
             if hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() == digest]
    if not files:
        return []
    problems = []
    for path in sorted(host.rglob('*.py')):
        if path in files:
            continue
        rel = path.relative_to(host).as_posix()
        try:
            tree = ast.parse(path.read_text('utf-8-sig'))
        except SyntaxError:
            continue   # the syntax check below reports it
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        names = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in SESSION_MODULES:
                        problems.append('%s:%d imports the module %s' % (rel, node.lineno, alias.name))
                continue
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                target = base.joinpath(*node.module.split('.')) if node.module else base
                from_session = target.with_suffix('.py') in files
                submodules = [alias for alias in node.names
                              if target.joinpath(alias.name + '.py') in files]
            else:
                from_session = node.module in SESSION_MODULES
                submodules = [alias for alias in node.names
                              if '%s.%s' % (node.module, alias.name) in SESSION_MODULES]
            for alias in submodules:
                problems.append('%s:%d imports the module %s' % (rel, node.lineno, alias.name))
            if from_session:
                for alias in node.names:
                    if alias.name == '*':
                        problems.append('%s:%d imports * from the session module' % (rel, node.lineno))
                    elif alias.name in _CLIENTS + ('HTTPAdapter', 'Retry'):
                        names[alias.asname or alias.name] = alias.name
        if not names:
            continue

        def adapter_call(node):
            return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
                    names.get(node.func.id) == 'HTTPAdapter')

        def adapter_argument(node):
            parent = parents.get(node)
            if isinstance(parent, ast.keyword):
                parent = parents.get(parent)
            return adapter_call(parent) and node is not parent.func

        retry_names = set()
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and
                    isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call) and
                    isinstance(node.value.func, ast.Name) and names.get(node.value.func.id) == 'Retry'):
                retry_names.add(node.targets[0].id)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Name):
                continue
            parent = parents.get(node)
            role = names.get(node.id)
            if role is None and node.id in retry_names:
                if isinstance(node.ctx, ast.Load) and not adapter_argument(node):
                    problems.append('%s:%d uses a Retry(...) value outside HTTPAdapter(...)' % (rel, node.lineno))
                continue
            if role is None or not isinstance(node.ctx, ast.Load):
                continue
            if role in _CLIENTS:
                if not (isinstance(parent, ast.Attribute) and parent.value is node):
                    problems.append('%s:%d uses %s other than as %s.<attribute>' % (rel, node.lineno, role, role))
            elif not (isinstance(parent, ast.Call) and parent.func is node):
                problems.append('%s:%d uses %s other than by calling it' % (rel, node.lineno, role))
            elif role == 'HTTPAdapter':
                outer = parents.get(parent)
                if isinstance(outer, ast.keyword):
                    outer = parents.get(outer)
                if not (isinstance(outer, ast.Call) and isinstance(outer.func, ast.Attribute) and
                        outer.func.attr == 'mount' and isinstance(outer.func.value, ast.Name) and
                        names.get(outer.func.value.id) in _CLIENTS):
                    problems.append('%s:%d builds HTTPAdapter(...) outside session.mount(...)' % (rel, node.lineno))
            elif role == 'Retry':
                owner = parents.get(parent)
                assigned = (isinstance(owner, ast.Assign) and owner in tree.body and
                            len(owner.targets) == 1 and isinstance(owner.targets[0], ast.Name))
                if not (assigned or adapter_argument(parent)):
                    problems.append('%s:%d builds Retry(...) outside HTTPAdapter(...)' % (rel, node.lineno))
    return problems


def verify(root, archive=None, pin_path='.github/pov-host-migration.json'):
    """Every enabled Wizard patch for the pinned add-on applies, idempotently.

    pin_path names the pin file: the POV host pin by default, or
    .github/umbrella-pin.json for Umbrella."""
    pin = json.loads((root / pin_path).read_text('utf-8'))
    if archive is None:
        with urllib.request.urlopen(pin['zip'], timeout=30) as response:
            archive = response.read(pin['size'] + 1)
    if len(archive) != pin['size'] or hashlib.sha256(archive).hexdigest() != pin['sha256']:
        raise ValueError('Official %s package size/hash does not match the pin' % pin['id'])
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
                raise ValueError('Official %s package failed CRC' % pin['id'])
            for name in package.namelist():
                if not name.startswith(pin['id'] + '/') or not (target / name).resolve().is_relative_to(target):
                    raise ValueError('Unexpected package path')
            package.extractall(target)
        host = target / pin['id']
        if pin['id'] == 'plugin.video.pov':
            # Before the hooks: this judges POV's own files.
            problems = audit_session_callers(host, _session_digest(root))
            if problems:
                raise ValueError('Shared-HTTP proxy cannot serve this POV: ' + '; '.join(problems[:10]))
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
        print('Official', pin['id'], pin['version'], 'verified:', first, 'repeat:', second)


if __name__ == '__main__':
    # verify_pov_patches.py [ZIP] [PIN]: the POV host pin unless PIN is given
    args = sys.argv[1:]
    verify(Path(__file__).resolve().parents[2], Path(args[0]).read_bytes() if args and args[0] else None,
           *(args[1:2]))
