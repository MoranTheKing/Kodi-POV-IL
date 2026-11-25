"""Audit the build's patches on the newest published version of each add-on
that updates itself on users' devices, and keep ONE issue per add-on open
only while something does not fit.

Usage:
    upstream_audit.py                      print one JSON line per add-on
    upstream_audit.py --issues OWNER/REPO  ... and open / comment / close issues through `gh`

Why (17 Nov 2026): the upstream check opened an issue for every new version of
Arctic Fuse 3, Idan Plus and Account Manager and asked a person to re-run the
patchers. Nothing ran them, the issues piled up (one a day), and the one
version that did break two patchers (Arctic Fuse 3 3.5.1) looked like all the
others. Now the patchers run here, on the official zip:

  * the Wizard's patch engine, for every enabled entry of patches_config.py
    that names the add-on -- applied twice (nothing missing, idempotent);
  * MoranSubs' own patchers for it (moransubs_host_audit.py).

A version on which everything fits needs nobody and opens nothing. A version
that does not fit opens one issue for that add-on (or adds a comment when the
issue is already open and a newer version is still broken); the issue is
closed here once a published version -- or a fixed patcher -- fits again.

POV and Umbrella are not here: their pins move through auto_bump_pov_pin.py,
on the same kind of proof.
"""
import ast
import importlib.util
import io
import json
import re
import runpy
import subprocess
import sys
import tempfile
import types
import urllib.request
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MAX_ZIP = 120 * 1024 * 1024
# add-on id -> the folders of the repositories that publish its zip (the
# repositories the Wizard registers on devices)
AUDITED = {
    'skin.arctic.fuse.3': (
        'https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/master/omega/zips/',
        'https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/master/repo/zips/'),
    'plugin.video.idanplus': (
        'https://raw.githubusercontent.com/fishenzon/repo/master/zips/',),
    # (Account Manager: retired upstream on 24 Nov 2026; the build ships 1.2.1a from
    # this repo, and tests/test_wizard_acctmgr_qr.py runs the patches on that tree)
    # Kodi's own repository (the mirror director sends each request to a mirror)
    'plugin.video.youtube': (
        'https://mirrors.kodi.tv/addons/omega/',),
}
TITLE = 'Upstream {0}: our patches need attention'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fetch(url, limit=MAX_ZIP):
    request = urllib.request.Request(url, headers={'User-Agent': 'kodi-povil-upstream-audit'})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('larger than %d bytes' % limit)
    return data


def official_tree(addon_id, version, target, getter=fetch):
    """Extract the official zip of that version under target; the add-on's folder."""
    filename = '{0}-{1}.zip'.format(addon_id, version)
    errors = []
    for base in AUDITED[addon_id]:
        url = '{0}{1}/{2}'.format(base, addon_id, filename)
        try:
            with zipfile.ZipFile(io.BytesIO(getter(url))) as package:
                if package.testzip() is not None:
                    raise ValueError('CRC error')
                for name in package.namelist():
                    if (not name.startswith(addon_id + '/')
                            or not (target / name).resolve().is_relative_to(target.resolve())):
                        raise ValueError('unexpected member path')
                head = package.read(addon_id + '/addon.xml').decode('utf-8', 'replace')
                tag = re.search(r'<addon\b[^>]*>', head, re.S)
                attrs = dict(re.findall(r'\b(id|version)\s*=\s*"([^"]*)"', tag.group(0) if tag else ''))
                if attrs.get('id') != addon_id or attrs.get('version') != version:
                    raise ValueError('addon.xml says %r' % attrs)
                package.extractall(target)
            return target / addon_id
        except Exception as exc:
            errors.append('{0}: {1}'.format(url, exc))
    raise OSError('; '.join(errors))


def wizard_problems(addon_id, host, root=ROOT):
    """What the Wizard's patch engine cannot do on this tree ([] when all fits
    or when no enabled entry names the add-on). The same checks as the pin
    gate (verify_pov_patches.verify): applied twice, nothing missing, the
    second pass changes nothing, every .py still parses."""
    wizard = root / 'plugin.program.kodipovilwizard'
    config = [entry for entry in
              runpy.run_path(str(wizard / 'resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
              if entry.get('addon_id') == addon_id]
    active = sum(entry.get('enabled', True) for entry in config)
    if not active:
        return []
    xbmc = types.ModuleType('xbmc')
    for index, name in enumerate(('LOGDEBUG', 'LOGINFO', 'LOGWARNING', 'LOGERROR')):
        setattr(xbmc, name, index)
    addon = types.SimpleNamespace(Addon=lambda: types.SimpleNamespace(getSetting=lambda key: ''))
    vfs = types.SimpleNamespace(translatePath=lambda path: path)
    logger = types.SimpleNamespace(log=lambda *args, **kwargs: None)
    problems = []
    unparseable_before = set(_unparseable(host))
    with patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcaddon': addon, 'xbmcvfs': vfs,
                                  'resources.libs.common': types.SimpleNamespace(logging=logger)}):
        module = _load('upstream_audit_engine', wizard / 'resources/libs/patch_engine.py')

        class Engine(module.PatchEngine):
            @staticmethod
            def _resolve_paths(addon_id, filename):
                return str(host), str(host / filename)

        first = Engine(config).run()
        second = Engine(config).run()
    for label, stats in (('first pass', first), ('second pass', second)):
        bad = {key: stats.get(key, 0) for key in
               ('failed', 'missing', 'anchor_missing', 'malformed', 'legacy_host_deferred') if stats.get(key, 0)}
        if bad:
            problems.append('Wizard patches, {0}: {1}'.format(label, bad))
        done = sum(stats.get(key, 0) for key in ('applied', 'upgraded', 'skipped_current', 'superseded'))
        if done != active and not bad:
            problems.append('Wizard patches, {0}: {1} of {2} completed'.format(label, done, active))
    if second.get('applied') or second.get('upgraded') or second.get('removed'):
        problems.append('Wizard patches are not idempotent: ' + repr(second))
    for name in sorted(set(_unparseable(host)) - unparseable_before):
        problems.append('{0} no longer parses after the Wizard patches'.format(name))
    return problems


def _unparseable(host):
    """The .py files of the tree that do not parse (a file upstream itself ships broken is not ours)."""
    for source in host.rglob('*.py'):
        try:
            ast.parse(source.read_text('utf-8-sig'), filename=str(source.relative_to(host)))
        except (SyntaxError, ValueError, OSError):
            yield source.relative_to(host).as_posix()


def moransubs_problems(addon_id, host, root=ROOT, runner=None):
    """What MoranSubs' own patchers cannot do on this tree ([] when all fit or
    when MoranSubs has none for the add-on)."""
    audit = _load('moransubs_host_audit', root / '.github/scripts/moransubs_host_audit.py')
    if addon_id not in audit.HOSTS:
        return []
    if runner is None:
        def runner(args):
            return subprocess.run(args, capture_output=True, text=True, timeout=600)
    result = runner([sys.executable, '-I', str(root / '.github/scripts/moransubs_host_audit.py'),
                     str(root / 'service.subtitles.kodipovilai'), addon_id, str(host)])
    if result.returncode:
        raise RuntimeError('MoranSubs host audit could not run: ' + (result.stderr or '').strip()[-400:])
    data = json.loads(result.stdout.strip().splitlines()[-1])
    return ['MoranSubs {0}.{1}: {2}'.format(step[0], step[1], step[4])
            for step in data['steps'] if step[4] != 'ok']


def audit(newest=None, getter=fetch, root=ROOT, runner=None):
    """[{addon, version, status: ok | broken | unavailable, problems}]"""
    if newest is None:
        checker = _load('check_upstream_addons', root / 'tools' / 'check_upstream_addons.py')
        newest = checker.upstream_versions(warn=lambda text: sys.stderr.write(text + '\n'))
    results = []
    for addon_id in AUDITED:
        version = newest.get(addon_id)
        if not version:
            results.append({'addon': addon_id, 'version': '', 'status': 'unavailable',
                            'problems': ['no published version could be read']})
            continue
        with tempfile.TemporaryDirectory(prefix='upstream-audit-') as temp:
            try:
                host = official_tree(addon_id, version, Path(temp), getter)
            except OSError as exc:
                # a repository in the middle of publishing: the next run reads it
                results.append({'addon': addon_id, 'version': version, 'status': 'unavailable',
                                'problems': [str(exc)[:500]]})
                continue
            # MoranSubs first, on the pristine tree (it works on its own copy);
            # the Wizard's engine edits this one.
            try:
                problems = (moransubs_problems(addon_id, host, root, runner)
                            + wizard_problems(addon_id, host, root))
            except Exception as exc:
                # the audit itself failed for this add-on: say so (the run ends
                # red), touch no issue of it, and still check the others
                results.append({'addon': addon_id, 'version': version, 'status': 'error',
                                'problems': ['the audit could not run: ' + repr(exc)[:400]]})
                continue
        results.append({'addon': addon_id, 'version': version,
                        'status': 'broken' if problems else 'ok', 'problems': problems})
    return results


def _gh(args, run=subprocess.run):
    result = run(['gh'] + args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('gh {0}: {1}'.format(' '.join(args[:3]), (result.stderr or '').strip()[-300:]))
    return result.stdout


def sync_issues(results, repo, gh=_gh, assignee=''):
    """One issue per add-on, open only while it is broken. Returns what was done."""
    done = []
    for row in results:
        if row['status'] in ('unavailable', 'error'):
            continue
        title = TITLE.format(row['addon'])
        found = [issue for issue in json.loads(gh([
            'issue', 'list', '--repo', repo, '--state', 'open', '--search', 'in:title "{0}"'.format(title),
            '--json', 'number,title,body,comments']) or '[]') if issue.get('title') == title]
        # delimited: "3.5.1" must not be found inside "3.5.10"
        marker = '**{0} {1}**'.format(row['addon'], row['version'])
        if row['status'] == 'broken':
            text = ('{0} is published and the build\'s patches do not fit it:\n\n{1}\n\n'
                    'Devices install this version by themselves from the developer\'s repository. '
                    'Fix the patcher(s) named above and release; this issue is closed automatically '
                    'by the upstream check once everything fits. Not covered by this check (they act '
                    'on a running Kodi): af3_home_patcher, update_nag_patcher.').format(
                        marker, '\n'.join('- ' + problem for problem in row['problems']))
            if not found:
                gh(['issue', 'create', '--repo', repo, '--title', title, '--body', text]
                   + (['--assignee', assignee] if assignee else []))
                done.append('opened: ' + marker)
            else:
                issue = found[0]
                seen = issue.get('body', '') + ''.join(c.get('body', '') for c in issue.get('comments') or [])
                if marker not in seen:
                    gh(['issue', 'comment', str(issue['number']), '--repo', repo, '--body', text])
                    done.append('commented: ' + marker)
        else:
            for issue in found:
                gh(['issue', 'close', str(issue['number']), '--repo', repo, '--comment',
                    'Every patch fits {0} (checked automatically); closing.'.format(marker)])
                done.append('closed: ' + marker)
    return done


def main(argv):
    warnings.simplefilter('ignore', SyntaxWarning)      # upstream sources, not ours
    results = audit()
    for row in results:
        print(json.dumps(row, ensure_ascii=False))
    if len(argv) > 2 and argv[1] == '--issues':
        for line in sync_issues(results, argv[2], assignee=argv[3] if len(argv) > 3 else ''):
            print(line)
    return 1 if any(row['status'] == 'error' for row in results) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
