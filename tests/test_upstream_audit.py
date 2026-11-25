"""The upstream check runs the build's patches on a new version and opens an
issue only when something does not fit (17 Nov 2026)."""

import importlib.util
import json
import re
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load('upstream_audit_under_test', '.github/scripts/upstream_audit.py')
host = load('moransubs_host_audit_under_test', '.github/scripts/moransubs_host_audit.py')
LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'
TITLE = audit.TITLE.format('skin.arctic.fuse.3')


class Gh(object):
    """Stands in for the `gh` command: the open issues and what was done."""

    def __init__(self, open_issues=()):
        self.open = list(open_issues)
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ['issue', 'list']:
            return json.dumps(self.open)
        return ''

    def did(self, verb):
        return [call for call in self.calls if call[1] == verb]


def row(status, version='3.5.4'):
    problems = ['MoranSubs af3_search_pov_patcher.ensure_patched: first run: no_file']
    return {'addon': 'skin.arctic.fuse.3', 'version': version, 'status': status,
            'problems': problems if status == 'broken' else []}


def open_issue(body='**skin.arctic.fuse.3 3.5.4** is published', title=TITLE, number=7):
    return {'number': number, 'title': title, 'body': body, 'comments': []}


class IssueTests(unittest.TestCase):
    def test_a_version_on_which_everything_fits_opens_nothing(self):
        gh = Gh()
        self.assertEqual(audit.sync_issues([row('ok')], 'o/r', gh=gh), [])
        self.assertEqual([call[1] for call in gh.calls], ['list'])

    def test_a_broken_version_opens_one_issue_that_names_the_patcher(self):
        gh = Gh()
        done = audit.sync_issues([row('broken')], 'o/r', gh=gh, assignee='owner')
        self.assertEqual(done, ['opened: **skin.arctic.fuse.3 3.5.4**'])
        created = gh.did('create')[0]
        self.assertIn(TITLE, created)
        self.assertIn('af3_search_pov_patcher', created[created.index('--body') + 1])
        self.assertEqual(created[-2:], ['--assignee', 'owner'])

    def test_the_same_broken_version_is_not_reported_twice(self):
        gh = Gh([open_issue()])
        self.assertEqual(audit.sync_issues([row('broken')], 'o/r', gh=gh), [])
        self.assertEqual(gh.did('create') + gh.did('comment'), [])

    def test_a_newer_version_that_is_still_broken_adds_a_comment_not_an_issue(self):
        gh = Gh([open_issue()])
        done = audit.sync_issues([row('broken', '3.5.5')], 'o/r', gh=gh)
        self.assertEqual(done, ['commented: **skin.arctic.fuse.3 3.5.5**'])
        self.assertEqual(gh.did('create'), [])
        self.assertEqual(gh.did('comment')[0][2], '7')

    def test_the_issue_is_closed_when_everything_fits_again(self):
        gh = Gh([open_issue()])
        self.assertEqual(audit.sync_issues([row('ok', '3.5.5')], 'o/r', gh=gh),
                         ['closed: **skin.arctic.fuse.3 3.5.5**'])
        self.assertEqual(gh.did('close')[0][2], '7')

    def test_a_repository_that_cannot_be_read_changes_nothing(self):
        gh = Gh([open_issue()])
        self.assertEqual(audit.sync_issues([row('unavailable')], 'o/r', gh=gh), [])
        self.assertEqual(gh.calls, [])

    def test_a_version_is_not_mistaken_for_a_longer_one(self):
        gh = Gh([open_issue(body='**skin.arctic.fuse.3 3.5.10** is published')])
        done = audit.sync_issues([row('broken', '3.5.1')], 'o/r', gh=gh)
        self.assertEqual(done, ['commented: **skin.arctic.fuse.3 3.5.1**'])

    def test_an_audit_that_could_not_run_touches_no_issue(self):
        gh = Gh([open_issue()])
        self.assertEqual(audit.sync_issues([dict(row('ok'), status='error')], 'o/r', gh=gh), [])
        self.assertEqual(gh.calls, [])

    def test_one_add_on_failing_to_audit_does_not_hide_the_others(self):
        import io
        import zipfile

        def getter(url):
            addon = url.rstrip('/').split('/')[-2]
            version = url.rsplit('-', 1)[-1][:-4]
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as package:
                package.writestr(addon + '/addon.xml', '<addon id="%s" version="%s"/>' % (addon, version))
            return data.getvalue()

        def runner(args):
            raise RuntimeError('boom')          # MoranSubs' audit cannot start

        newest = dict((addon, '1.0') for addon in audit.AUDITED)
        results = dict((r['addon'], r['status'])
                       for r in audit.audit(newest=newest, getter=getter, runner=runner))
        self.assertEqual(results['skin.arctic.fuse.3'], 'error')
        self.assertEqual(results['plugin.video.idanplus'], 'error')
        # YouTube has no MoranSubs patcher: the Wizard's entries run and miss their anchors
        self.assertEqual(results['plugin.video.youtube'], 'broken')

    def test_an_issue_of_another_title_is_left_alone(self):
        gh = Gh([open_issue(title=TITLE + ' (old)', number=9)])
        audit.sync_issues([row('ok')], 'o/r', gh=gh)
        self.assertEqual(gh.did('close'), [])


class VerdictTests(unittest.TestCase):
    def test_patched_then_settled_is_ok(self):
        self.assertEqual(host.verdict('patched', 'already_patched'), 'ok')
        self.assertEqual(host.verdict('heal=missing harden=patched', 'heal=missing harden=already'), 'ok')

    def test_a_moved_anchor_or_a_missing_file_is_not_ok(self):
        for first in ('unmatched', 'no_file', 'no_af3', 'read_failed', 'error: KeyError',
                      '1105=unmatched, search=patched'):
            self.assertNotEqual(host.verdict(first, first), 'ok', first)

    def test_a_patcher_that_patches_again_is_not_ok(self):
        self.assertNotEqual(host.verdict('patched', 'patched'), 'ok')
        self.assertNotEqual(host.verdict('heal=ok harden=patched', 'heal=ok harden=patched'), 'ok')


class ContractTests(unittest.TestCase):
    def test_every_patcher_of_an_audited_host_is_run_or_named_as_left_out(self):
        # af3_home_patcher rebuilds the menu through the running skin: it cannot run without Kodi
        left_out = {'af3_home_patcher'}
        steps = [(module, function) for group in host.HOSTS.values() for module, function in group]
        listed = {module for module, _function in steps}
        on_disk = {path.stem for path in LIB.glob('*.py')
                   if re.match(r'(af3|idanplus)_.*_patcher$', path.stem)}
        self.assertEqual(on_disk - listed - left_out, set(),
                         'a new host patcher must join moransubs_host_audit.HOSTS')
        for module, function in steps:
            source = (LIB / (module + '.py')).read_text('utf-8')
            self.assertRegex(source, r'(?m)^def %s\(' % function, module)

    def test_the_wizard_patches_of_every_host_are_pinned_or_audited(self):
        config = runpy.run_path(str(
            ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
        hosts = {entry.get('addon_id') for entry in config}
        pinned = {'plugin.video.pov', 'plugin.video.umbrella'}        # their pins move on the same proof
        # shipped from this repo, its patches run on that tree (test_wizard_acctmgr_qr)
        shipped = {'script.module.acctmgr'}
        self.assertTrue((ROOT / 'script.module.acctmgr' / 'addon.xml').is_file())
        self.assertEqual(hosts - pinned - shipped - set(audit.AUDITED), set(),
                         'a host the Wizard patches is neither pinned nor audited')

    def test_the_workflow_runs_the_audit_and_opens_no_informational_issue(self):
        text = (ROOT / '.github/workflows/check-upstream-pov.yml').read_text('utf-8')
        self.assertIn('python3 .github/scripts/upstream_audit.py --issues "$REPO_SLUG"', text)
        self.assertNotIn('verified pin moved automatically', text)
        self.assertNotIn('Upstream add-on update:', text)
        self.assertIn('moransubs_host_audit.py service.subtitles.kodipovilai', text)
        self.assertIn('NOT moved', text)          # the issues a person is needed for stay


if __name__ == '__main__':
    unittest.main()
