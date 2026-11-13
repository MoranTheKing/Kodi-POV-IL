"""Block a release if current hooks do not fit the verified official POV tree."""
import ast
import hashlib
import importlib.util
import io
import json
import runpy
import subprocess
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


def _module_names(path):
    """Names a module has once imported, read from source (None: it star-imports)."""
    names = set()

    def walk(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Import):
                names.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if any(alias.name == '*' for alias in node.names):
                    raise LookupError('star import')
                names.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for field in ('body', 'orelse', 'finalbody'):
                    walk(getattr(node, field, None) or [])
                for handler in getattr(node, 'handlers', None) or []:
                    walk(handler.body)
    try:
        walk(ast.parse(path.read_text('utf-8-sig')).body)
    except LookupError:
        return None
    return names


def audit_host_names(host, patches):
    """Problems a Wizard patch module would hit by asking POV for a name POV
    does not have.

    The hooks apply by text anchors, so a POV release that keeps an anchor but
    renames or stops importing a name still "verifies" and then fails on the
    device (POV 6.11.03: modules.dialogs lost confirm_dialog, and every
    "remove from continue watching" raised KeyError).  Three shapes are read
    from source, on the tree with the hooks in; nothing is imported:
      native['x']       -- in a patch function a POV module hands globals() to;
      from m import x   -- m a POV module;
      m.x               -- m a name bound by importing a POV module.
    What it does not see: a name reached another way (getattr, .get(), a
    computed key, locals()); `native` handed on to another function or bound
    to a second name; a hook that passes globals() by keyword or imports the
    patch module under another name; patch modules not named pov_*.py.
    What it would report although the code is safe: a name the patch guards
    (hasattr, try/except, 'x' in native); a POV module name bound only by
    for / with / walrus / global; a patch function that is not a top-level
    def.  None occurs today; such a report blocks the release until the
    audit or the patch is taught the shape.
    """
    lib = Path(host) / 'resources' / 'lib'
    cache = {}

    def module_file(dotted):
        path = lib.joinpath(*dotted.split('.'))
        if path.with_suffix('.py').is_file():
            return path.with_suffix('.py')
        if (path / '__init__.py').is_file():
            return path / '__init__.py'
        return None

    def names_of(path):
        if path not in cache:
            cache[path] = _module_names(path)
        return cache[path]

    def has(dotted, name):
        path = module_file(dotted)
        if path is None or module_file(dotted + '.' + name) is not None:
            return True          # not a POV module (not ours to judge), or a submodule
        names = names_of(path)
        return names is None or name in names

    problems = []
    patch_trees = {}
    for path in sorted(Path(patches).glob('pov_*.py')):
        tree = ast.parse(path.read_text('utf-8-sig'))
        patch_trees[path.stem] = tree
        bound = {}               # local name -> the POV module it is
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    if module_file(node.module + '.' + alias.name) is not None:
                        bound[alias.asname or alias.name] = node.module + '.' + alias.name
                    elif not has(node.module, alias.name):
                        problems.append('%s:%d imports %s from %s, which has no such name'
                                        % (path.name, node.lineno, alias.name, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname and module_file(alias.name) is not None:
                        bound[alias.asname] = alias.name
        # A name the file also assigns, or takes as a parameter, may be
        # something else where it is used: left alone.
        other = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        other |= {arg.arg for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.Lambda))
                  for arg in n.args.args + n.args.kwonlyargs}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                    and isinstance(node.value, ast.Name) and node.value.id in bound
                    and node.value.id not in other and not node.attr.startswith('__')
                    and not has(bound[node.value.id], node.attr)):
                problems.append('%s:%d uses %s.%s, which %s does not define'
                                % (path.name, node.lineno, node.value.id, node.attr, bound[node.value.id]))

    callers = {}                 # (patch module, function, argument position) -> POV files
    for path in sorted(lib.rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text('utf-8-sig'))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in patch_trees):
                continue
            for position, arg in enumerate(node.args):
                if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                        and arg.func.id == 'globals' and not arg.args):
                    callers.setdefault((node.func.value.id, node.func.attr, position), []).append(path)
    for (module, function, position), paths in sorted(callers.items()):
        where = ' / '.join(path.relative_to(lib).as_posix() for path in paths)
        definition = next((node for node in patch_trees[module].body
                           if isinstance(node, ast.FunctionDef) and node.name == function), None)
        if definition is None:
            problems.append('%s calls %s.%s, which does not exist' % (where, module, function))
            continue
        if position >= len(definition.args.args):
            continue
        param = definition.args.args[position].arg
        read, written = {}, {}
        for node in ast.walk(definition):
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == param
                    and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
                seen = read if isinstance(node.ctx, ast.Load) else written
                seen[node.slice.value] = min(node.lineno, seen.get(node.slice.value, node.lineno))
        for name, line in sorted(read.items()):
            # Its own store only excuses a read that comes after it
            # (pov_directory_latency reads native['routing'], POV's, and then
            # replaces it).  A function shared by several POV modules may take
            # a name from the one that has it (remote_toggle: call_trakt,
            # call_mdblist).
            if written.get(name, line) >= line and not any(
                    names is None or name in names for names in map(names_of, paths)):
                problems.append("%s.py:%d %s() reads native['%s'], which %s does not define"
                                % (module, line, function, name, where))
    return problems


def audit_moransubs_umbrella(root, host, runner=None):
    """Problems MoranSubs' Umbrella patchers have with this official Umbrella.

    The Wizard's hooks are not all a new Umbrella needs: on 22 Oct 2026 the
    pin moved to 6.7.95, MoranSubs' Hebrew menu installer could not read its
    moved English strings, and every device got English menus. The audit runs
    the patchers repair_hosts.py runs on devices, twice, on a copy of the
    tree, in a separate interpreter (stubbed Kodi, no network)."""
    if runner is None:
        def runner(args):
            return subprocess.run(args, capture_output=True, text=True, timeout=300)
    script = root / '.github/scripts/moransubs_umbrella_audit.py'
    result = runner([sys.executable, '-I', str(script),
                     str(root / 'service.subtitles.kodipovilai'), str(host)])
    if result.returncode:
        raise ValueError('MoranSubs Umbrella audit could not run: ' + result.stderr.strip()[-400:])
    data = json.loads(result.stdout.strip().splitlines()[-1])
    good = set(data['good'])
    problems = []
    for module, function, first, second in data['steps']:
        name = '{}.{}'.format(module, function)
        if first not in good:
            problems.append('{}: {}'.format(name, first))
        elif second not in good or second in ('patched', 'repatched'):
            problems.append('{} does not settle: {} then {}'.format(name, first, second))
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
        if pin['id'] == 'plugin.video.umbrella':
            # On the pristine tree (the audit works on its own copy).
            problems = audit_moransubs_umbrella(root, host)
            if problems:
                raise ValueError('MoranSubs Umbrella patchers do not fit: ' + '; '.join(problems))
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
        if pin['id'] == 'plugin.video.pov':
            # After the hooks: what the patch modules ask this POV for by name.
            problems = audit_host_names(host, wizard / 'resources/libs/patches')
            if problems:
                raise ValueError('Wizard patches ask this POV for names it does not have: '
                                 + '; '.join(problems[:10]))
        print('Official', pin['id'], pin['version'], 'verified:', first, 'repeat:', second)


if __name__ == '__main__':
    # verify_pov_patches.py [ZIP] [PIN]: the POV host pin unless PIN is given
    args = sys.argv[1:]
    verify(Path(__file__).resolve().parents[2], Path(args[0]).read_bytes() if args and args[0] else None,
           *(args[1:2]))
