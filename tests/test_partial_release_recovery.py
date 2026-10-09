"""A later push must finish versions that an interrupted release did not publish."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('partial_release', ROOT/'.github/scripts/list_changed.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class PartialReleaseRecoveryTests(unittest.TestCase):
    def pending(self, entries):
        addons = [SimpleNamespace(id='wizard', version='2'), SimpleNamespace(id='service', version='3'),
                  SimpleNamespace(id='skin', version='4')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'manifest.json'
            path.write_text(json.dumps({'addons': entries}), 'utf8')
            return module.unpublished_addons(addons, path)

    def test_partial_release_rebuilds_all_unpublished_source_versions(self):
        entries = {name: {'version': version, 'size': 10, 'sha256': 'a'*64}
                   for name, version in [('wizard', '1'), ('service', '2'), ('skin', '4')]}
        self.assertEqual(self.pending(entries), {'wizard', 'service'})

    def test_completed_versions_are_not_republished_on_unrelated_pushes(self):
        entries = {name: {'version': version, 'size': 10, 'sha256': 'a'*64}
                   for name, version in [('wizard', '2'), ('service', '3'), ('skin', '4')]}
        self.assertEqual(self.pending(entries), set())

    def test_new_or_incomplete_manifest_entries_cannot_be_carried_as_verified(self):
        entries = {'wizard': {'version': '2', 'size': 10, 'sha256': 'a'*64},
                   'service': {'version': '3', 'size': None, 'sha256': None}}
        self.assertEqual(self.pending(entries), {'service', 'skin'})

    def test_unreadable_manifest_uses_a_complete_build(self):
        self.assertEqual(module.unpublished_addons([SimpleNamespace(id='wizard', version='2')],
                                                   ROOT/'nonexistent-private-manifest.json'), {'wizard'})


if __name__ == '__main__':
    unittest.main()
