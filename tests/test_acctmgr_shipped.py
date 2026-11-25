"""Wizard 0.5.52: Account Manager comes from the build's manifest.

24 Nov 2026, 22:39 UTC: Account Manager's developer retired it ("End of Development") and removed
script.module.acctmgr and script.module.acctvwr from repository.709 and every other repository he runs.
The Wizard installed Account Manager from repository.709 as a core part of the build, so every new install
from then on stopped at 25% on it and ended "the installation did not complete -- script.module.acctmgr
(native core addon unavailable)" (field report, 25 Nov 2026, "everyone").

The build now ships the developer's last published zips (GPL-3) from this repo: the manifest installs them
with the build's own add-ons, which also completes a first install on a Wizard released before this one.
"""
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET

from test_provisioning_gate import ROOT

LIBS = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'


def _addon(folder):
    return ET.parse(str(ROOT / folder / 'addon.xml')).getroot()


class TheShippedTrees(unittest.TestCase):
    def test_the_last_published_versions_are_shipped(self):
        am, viewer = _addon('script.module.acctmgr'), _addon('script.module.acctvwr')
        self.assertEqual((am.get('id'), am.get('version')), ('script.module.acctmgr', '1.2.1a'))
        self.assertEqual((viewer.get('id'), viewer.get('version')), ('script.module.acctvwr', '1.1.6a'))
        needs = {i.get('addon'): i.get('version') for i in am.iter('import')}
        # the viewer it needs is the one shipped beside it
        self.assertEqual(needs.get('script.module.acctvwr'), viewer.get('version'))
        self.assertIn('GNU GENERAL PUBLIC LICENSE', am.findtext('.//license') or '')
        self.assertTrue((ROOT / 'script.module.acctvwr' / 'LICENSE.txt').is_file())

    def test_git_keeps_them_byte_for_byte(self):
        rules = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        for folder in ('script.module.acctmgr', 'script.module.acctvwr'):
            self.assertRegex(rules, r'(?m)^%s/\*\* -text\s*$' % re.escape(folder))

    def test_the_packager_ships_them_whole(self):
        sys.path.insert(0, str(ROOT / '.github' / 'scripts'))
        self.addCleanup(sys.path.remove, str(ROOT / '.github' / 'scripts'))
        import kodi_addons
        found = {a.id: a for a in kodi_addons.discover_addons(str(ROOT))}
        self.assertEqual(found['script.module.acctmgr'].version, '1.2.1a')
        self.assertEqual(found['script.module.acctvwr'].version, '1.1.6a')
        for folder in ('script.module.acctmgr', 'script.module.acctvwr'):
            for base, dirs, files in os.walk(str(ROOT / folder)):
                self.assertFalse(set(dirs) & kodi_addons.EXCLUDE_DIR_NAMES, base)
                self.assertFalse([f for f in files if f in kodi_addons.EXCLUDE_FILE_NAMES
                                  or f.endswith(kodi_addons.EXCLUDE_SUFFIXES)], base)


if __name__ == '__main__':
    unittest.main()
