"""The repository stays small (the owner, 17 Nov 2026: "never again hundreds of unused files and 4 GB of old
versions").

It had grown to 3.9 GB and 4,729 files: every packaged version ever published was still in dist/ and repo/zips,
and every update note had left its pointer file behind. This test runs in CI with every build and before every
push, so a superseded package, a second packaged version or a forgotten pointer file fails the build instead of
piling up. A new package is added HERE on purpose, with the reason it has to be in the repository.
"""
import importlib.util
import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = r'\d+(?:\.\d+)*'
# Every package the repository may hold, and why it is here and not only in a release.
PACKAGES = (
    # what build.txt and the platform packages still fetch by this exact path
    r'dist/Kodi-POV-IL-FENtastic-test-0\.1\.179\.zip',
    r'dist/Kodi-POV-IL-FENtastic-quickfix-0\.1\.627\.zip',      # CI takes the pool file from it by hash
    r'dist/Kodi-POV-IL-(?:AF3-deps|AF3-fonts|AF3-skin|AF3-studios|AcctMgr|Umbrella)-pack\.zip',
    r'dist/plugin\.program\.kodipovilwizard-0\.1\.49\.zip',
    r'dist/plugin\.program\.kodipovilwizard-latest\.zip',
    r'wizard/plugin\.program\.kodipovilwizard-(?:0\.1\.49|latest|RESCUE)\.zip',
    r'wizard-new/plugin\.program\.kodipovilwizard-latest\.zip',  # the Pages fallback
    r'addons/service\.subtitles\.kodipovilai/resources/staged_wizard\.zip',
    r'plugin\.program\.kodipovilwizard/resources/bootstrap/config\.zip',
    # the standalone MoranSubs channel: the repository add-on, and ONE packaged version (+ its "latest" copy)
    r'repo/repository\.kodipovilai-1\.0\.0\.zip',
    r'repo/zips/repository\.kodipovilai/repository\.kodipovilai-1\.0\.0\.zip',
    r'dist/service\.subtitles\.kodipovilai-latest\.zip',
    r'dist/service\.subtitles\.kodipovilai-' + VERSION + r'\.zip',
    r'repo/zips/service\.subtitles\.kodipovilai/service\.subtitles\.kodipovilai-' + VERSION + r'\.zip',
)
# Measured on 17 Nov 2026: 3,365 files, 420.6 MB (302 MB of it the packs above). Room for ordinary growth only.
MAX_FILES = 3700
MAX_TOTAL_MB = 450
MAX_FILE_MB = 72


def tracked():
    try:
        out = subprocess.run(['git', 'ls-files', '-z'], cwd=str(ROOT), capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [name for name in out.decode('utf-8').split('\0') if name and (ROOT / name).is_file()]


class RepositoryStaysSmallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = tracked()
        if cls.files is None:
            raise unittest.SkipTest('not a git checkout')

    def test_every_package_in_the_repository_is_one_it_needs(self):
        packages = [f for f in self.files if f.lower().endswith(('.zip', '.apk', '.ipk', '.exe', '.7z', '.rar'))]
        strangers = [f for f in packages if not any(re.fullmatch(pattern, f) for pattern in PACKAGES)]
        self.assertEqual(strangers, [], 'a package that belongs in a release, not in git: every copy stays in the '
                                        'history for good. Remove it, or name it in PACKAGES with the reason')

    def test_one_packaged_moransubs_version_and_no_older_one(self):
        """A new standalone version is published in the same commit that removes the one before it."""
        for folder, pattern in (('dist', r'dist/service\.subtitles\.kodipovilai-(%s)\.zip' % VERSION),
                                ('repo/zips', r'repo/zips/service\.subtitles\.kodipovilai/'
                                              r'service\.subtitles\.kodipovilai-(%s)\.zip' % VERSION)):
            versions = [m.group(1) for m in (re.fullmatch(pattern, f) for f in self.files) if m]
            self.assertLessEqual(len(versions), 1, '%s holds more than one packaged version: %s' % (folder, versions))
        dist = [f for f in self.files if re.fullmatch(r'dist/service\.subtitles\.kodipovilai-(%s)\.zip' % VERSION, f)]
        repo = [f for f in self.files if re.fullmatch(
            r'repo/zips/service\.subtitles\.kodipovilai/service\.subtitles\.kodipovilai-(%s)\.zip' % VERSION, f)]
        self.assertEqual([os.path.basename(f) for f in dist], [os.path.basename(f) for f in repo])

    def test_only_the_last_two_update_notes_keep_a_pointer_file(self):
        pointers = [f for f in self.files if f.startswith('wizard/assets/build_versions/')]
        self.assertLessEqual(len(pointers), 2, pointers)

    def test_the_whole_tree_stays_within_its_size(self):
        sizes = {f: (ROOT / f).stat().st_size for f in self.files}
        total = sum(sizes.values()) / 1048576.0
        self.assertLessEqual(len(self.files), MAX_FILES, 'files: was 3,365 after the clean-up')
        self.assertLessEqual(total, MAX_TOTAL_MB, 'tracked megabytes: was 420.6 after the clean-up')
        big = {f: round(size / 1048576.0, 1) for f, size in sizes.items() if size > MAX_FILE_MB * 1048576}
        self.assertEqual(big, {})

    def test_nothing_built_or_cached_is_tracked(self):
        junk = [f for f in self.files if '/__pycache__/' in '/' + f or f.endswith(('.pyc', '.pyo', '.log', '.tmp', '.bak'))
                or os.path.basename(f) in ('Thumbs.db', '.DS_Store')]
        self.assertEqual(junk, [])


class ReleasePruningTests(unittest.TestCase):
    """The rolling release drops what the new manifest superseded (.github/scripts/prune_release_assets.py)."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('prune_release_assets', ROOT / '.github/scripts/prune_release_assets.py')
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    @staticmethod
    def manifest(**versions):
        link = 'https://github.com/o/r/releases/download/addons-latest/'
        return {'addons': {name: {'zip': link + '%s-%s.zip' % (name, version)} for name, version in versions.items()},
                'config': {'zip': link + 'config-2.0.12.zip'},
                'pov_host_migration': {'mirror': link + 'official-plugin.video.pov-6.11.03.zip'}}

    def test_only_older_versions_of_what_the_manifests_name_are_removed(self):
        current = self.manifest(**{'plugin.program.kodipovilwizard': '0.5.3', 'skin.povil.onyx': '1.0.13',
                                   'plugin.program.orderfavourites-hebrew': '1.4.13', 'script.fentastic.helper': '0.6.21'})
        previous = self.manifest(**{'plugin.program.kodipovilwizard': '0.5.2', 'skin.povil.onyx': '1.0.12',
                                    'plugin.program.orderfavourites-hebrew': '1.4.13', 'script.fentastic.helper': '0.6.21'})
        assets = ['config-2.0.12.zip', 'official-plugin.video.pov-6.11.03.zip', 'official-plugin.video.pov-6.10.22.zip',
                  'plugin.program.kodipovilwizard-0.5.0.zip', 'plugin.program.kodipovilwizard-0.5.2.zip',
                  'plugin.program.kodipovilwizard-0.5.3.zip', 'plugin.program.kodipovilwizard-latest.zip',
                  'plugin.program.orderfavourites-hebrew-1.4.12.zip', 'plugin.program.orderfavourites-hebrew-1.4.13.zip',
                  'script.fentastic.helper-0.6.20a.zip', 'script.fentastic.helper-0.6.21.zip',
                  'skin.povil.onyx-1.0.11.zip', 'skin.povil.onyx-1.0.12.zip', 'skin.povil.onyx-1.0.13.zip',
                  'repository.otaku-1.0.zip', 'notes.txt']
        delete, keep, unknown = self.m.plan(assets, current, previous)
        self.assertEqual(delete, ['official-plugin.video.pov-6.10.22.zip', 'plugin.program.kodipovilwizard-0.5.0.zip',
                                  'plugin.program.orderfavourites-hebrew-1.4.12.zip', 'script.fentastic.helper-0.6.20a.zip',
                                  'skin.povil.onyx-1.0.11.zip'])
        self.assertIn('plugin.program.kodipovilwizard-0.5.2.zip', keep, 'the manifest before: devices may still be reading it')
        self.assertIn('plugin.program.kodipovilwizard-latest.zip', keep)
        self.assertEqual(unknown, ['notes.txt', 'repository.otaku-1.0.zip'], 'not named by a manifest: left for a person')

    def run_main(self, current, previous, assets, *extra):
        import contextlib
        import io
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as raw:
            paths = {}
            for name, value in (('m', current), ('p', previous)):
                paths[name] = os.path.join(raw, name + '.json')
                with open(paths[name], 'w', encoding='utf-8') as out:
                    out.write(value if isinstance(value, str) else json.dumps(value))
            paths['a'] = os.path.join(raw, 'assets.txt')
            with open(paths['a'], 'w', encoding='utf-8') as out:
                out.write('\n'.join(assets))
            text = io.StringIO()
            ran = []
            real = self.m.subprocess.run
            self.m.subprocess.run = lambda command, **kwargs: ran.append(command) or type('R', (), {'returncode': 0})()
            try:
                with contextlib.redirect_stdout(text):
                    code = self.m.main(['--manifest', paths['m'], '--previous', paths['p'], '--assets', paths['a']] + list(extra))
            finally:
                self.m.subprocess.run = real
        return code, text.getvalue(), ran

    def test_nothing_is_deleted_when_anything_looks_wrong(self):
        good = self.manifest(**{'skin.povil.onyx': '1.0.13'})
        assets = ['config-2.0.12.zip', 'official-plugin.video.pov-6.11.03.zip', 'skin.povil.onyx-1.0.13.zip',
                  'skin.povil.onyx-1.0.11.zip']
        # a manifest that cannot be read, a manifest naming a file the release lacks, an implausibly long list
        for current, previous, listed, extra in (('{broken', good, assets, ()),
                                                 (good, good, assets[:2] + assets[3:], ()),
                                                 (good, good, assets + ['skin.povil.onyx-1.0.%d.zip' % n for n in range(1, 11)],
                                                  ('--max', '5'))):
            code, said, ran = self.run_main(current, previous, listed, '--delete', *extra)
            self.assertEqual((code, ran), (0, []), said)
            self.assertIn('nothing deleted', said)
        code, said, ran = self.run_main(good, good, assets)                   # a dry run names and deletes nothing
        self.assertEqual(ran, [])
        self.assertIn('would delete: skin.povil.onyx-1.0.11.zip', said)
        code, said, ran = self.run_main(good, good, assets, '--delete')
        self.assertEqual(ran, [['gh', 'release', 'delete-asset', 'addons-latest', 'skin.povil.onyx-1.0.11.zip', '--yes']])

    def test_the_build_prunes_after_the_manifest_is_in_place_and_never_fails_on_it(self):
        workflow = (ROOT / '.github/workflows/build-and-release.yml').read_text('utf-8')
        save = workflow.index('cp manifest.json "$RUNNER_TEMP/manifest.previous.json"')
        self.assertLess(save, workflow.index('python .github/scripts/gen_manifest.py'))
        step = workflow.index('- name: Remove superseded packages from the release')
        self.assertGreater(step, workflow.index('- name: Commit manifest.json'))
        self.assertGreater(step, workflow.index('- name: Verify every manifest target exists on release'))
        self.assertIn('continue-on-error: true', workflow[step:step + 200])


if __name__ == '__main__':
    unittest.main()
