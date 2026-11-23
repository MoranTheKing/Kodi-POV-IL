"""The Wizard's Kodi version check (kodi_update.py, Wizard 0.5.48): a newer Kodi of the same major version only,
told once at start-up, and steps that work for this install (a viewer on Google Play's Kodi 21.2 pressed "update
the Kodi version" and nothing could update)."""
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
spec = importlib.util.spec_from_file_location('kodi_update', WIZARD / 'resources' / 'libs' / 'kodi_update.py')
ku = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ku)

RELEASES = [
    {'tag_name': '22.0-Piers', 'prerelease': False, 'draft': False},
    {'tag_name': '22.0b2-Piers', 'prerelease': True, 'draft': False},
    {'tag_name': '21.3-Omega', 'prerelease': False, 'draft': False},
    {'tag_name': '21.4rc1-Omega', 'prerelease': True, 'draft': False},
    {'tag_name': '21.2-Omega', 'prerelease': False, 'draft': False},
    {'tag_name': '20.5-Nexus', 'prerelease': False, 'draft': False},
    {'tag_name': '21.9-Omega', 'prerelease': False, 'draft': True},
    'not a release',
]


class SameMajor(unittest.TestCase):
    def test_the_newest_final_release_of_the_same_major_version(self):
        self.assertEqual(ku.latest_same_major(RELEASES, (21, 2)), (21, 3))
        self.assertEqual(ku.latest_same_major(RELEASES, (21, 3)), (21, 3))

    def test_a_new_major_version_is_never_offered(self):
        # Kodi 22 is a new major version the build is not made for: a 21.x device is never sent there
        self.assertNotEqual(ku.latest_same_major(RELEASES, (21, 3)), (22, 0))
        self.assertEqual(ku.latest_same_major(RELEASES, (20, 2)), (20, 5))

    def test_nothing_read_means_nothing_known(self):
        self.assertIsNone(ku.latest_same_major(None, (21, 2)))
        self.assertIsNone(ku.latest_same_major([], (21, 2)))
        self.assertIsNone(ku.latest_same_major(RELEASES, None))

    def test_kodis_build_version_label(self):
        self.assertEqual(ku.parse_version('21.2 (21.2.0) Git:20250120-ab12'), (21, 2))
        self.assertEqual(ku.parse_version('21.3-Omega'), (21, 3))
        self.assertIsNone(ku.parse_version('Omega'))


class Once(unittest.TestCase):
    def test_start_up_tells_a_version_once(self):
        self.assertTrue(ku.should_show({}, (21, 3), 0, manual=False))
        self.assertFalse(ku.should_show({'shown': '21.3'}, (21, 3), 0, manual=False))
        self.assertTrue(ku.should_show({'shown': '21.3'}, (21, 4), 0, manual=False))
        self.assertTrue(ku.should_show({'shown': '21.3'}, (21, 3), 0, manual=True))

    def test_start_up_asks_github_at_most_once_a_day(self):
        self.assertTrue(ku.should_check({}, 1000, manual=False))
        self.assertFalse(ku.should_check({'checked': 1000}, 1000 + ku.DAY - 1, manual=False))
        self.assertTrue(ku.should_check({'checked': 1000}, 1000 + ku.DAY, manual=False))
        self.assertTrue(ku.should_check({'checked': 1000}, 1001, manual=True))
        self.assertTrue(ku.should_check({'checked': 'x'}, 1001, manual=False))

    def test_no_answer_from_github_is_retried_in_hours_not_on_every_start(self):
        self.assertFalse(ku.should_check({'failed': 1000}, 1000 + ku.RETRY - 1, manual=False))
        self.assertTrue(ku.should_check({'failed': 1000}, 1000 + ku.RETRY, manual=False))
        self.assertTrue(ku.should_check({'failed': 1000}, 1001, manual=True))


class Kind(unittest.TestCase):
    def test_our_app_and_our_installer(self):
        self.assertEqual(ku.install_kind('android', '/data/user/0/org.xbmc.povi/cache/apk/assets/',
                                         '/storage/emulated/0/Android/data/org.xbmc.povi/files/.kodi/'), 'ours')
        self.assertEqual(ku.install_kind('android', '/data/user/0/org.xbmc.kodi/cache/apk/assets/',
                                         '/storage/emulated/0/Android/data/org.xbmc.kodi/files/.kodi/'), 'official')
        self.assertEqual(ku.install_kind('windows', 'C:\\Program Files\\Kodi POV IL\\',
                                         'C:\\Program Files\\Kodi POV IL\\portable_data\\'), 'ours')
        self.assertEqual(ku.install_kind('windows', 'C:\\Program Files\\Kodi\\',
                                         'C:\\Users\\x\\AppData\\Roaming\\Kodi\\'), 'official')
        self.assertEqual(ku.install_kind('windows', 'C:\\Users\\x\\KodiPOVIL-QA\\',
                                         'C:\\Users\\x\\KodiPOVIL-QA\\portable_data\\'), 'ours')
        # an official Kodi run portable (-p) is not ours: the menu item must not send it to our installer
        self.assertEqual(ku.install_kind('windows', 'D:\\Kodi\\', 'D:\\Kodi\\portable_data\\'), 'official')


class Text(unittest.TestCase):
    def lines(self, text):
        return [l for l in text.split('\n') if l]

    def test_android_official_says_what_works(self):
        t = ku.message('android', 'official', (21, 2), (21, 3), 64)
        self.assertIn('21.3', t)
        self.assertIn('21.2', t)
        self.assertIn('kodi.tv/download', t)
        self.assertIn('ARMV8A (64 ביט)', t)
        self.assertIn('מעל הקיים', t)
        self.assertIn('לא מסירים', t)                # uninstalling erases the settings
        self.assertIn('לא יכול להתקין', t)           # the Wizard does not pretend to update
        self.assertIn('ARMV7A (32 ביט)', ku.message('android', 'official', (21, 2), (21, 3), 32))
        self.assertNotIn('החנות הרשמית', t)

    def test_windows_official(self):
        t = ku.message('windows', 'official', (21, 2), (21, 3), 64)
        self.assertIn('kodi.tv/download', t)
        self.assertIn('Windows', t)

    def test_ours_points_at_our_downloads(self):
        for plat in ('android', 'windows'):
            t = ku.message(plat, 'ours', (21, 3), None, 64)
            self.assertIn('Kodi POV IL', t)
            self.assertIn(ku.DOWNLOADS_PAGE, t)
            self.assertIn('21.3', t)

    def test_every_line_reads_right_to_left(self):
        # Kodi takes a line's direction from its first strong letter: each line opens with a Hebrew word (a line
        # that is only an address stays as it is)
        texts = [ku.message(p, k, (21, 2), (21, 3), 64) for p in ('android', 'windows') for k in ('official', 'ours')]
        texts.append(ku.up_to_date_message((21, 3)))
        for t in texts:
            for line in self.lines(t):
                bare = re.sub(r'\[/?[A-Z]+[^\]]*\]', '', line)
                if bare == ku.DOWNLOADS_PAGE:
                    continue
                first = re.search(r'[A-Za-z\u0590-\u05FF]', bare).group(0)
                self.assertTrue('\u0590' <= first <= '\u05FF', line)


class Glue(unittest.TestCase):
    src = (WIZARD / 'resources' / 'libs' / 'wizard.py').read_text(encoding='utf-8')

    def test_the_wizard_uses_the_releases_list_not_the_newest_release(self):
        self.assertNotIn('releases/latest', self.src)
        self.assertIn('xbmc/xbmc/releases?per_page=30', self.src)
        self.assertIn('ku.latest_same_major(releases, current)', self.src)
        self.assertIn("state['shown'] = ku.vstr(latest)", self.src)
        self.assertNotIn('החנות הרשמית', self.src)
        # the steps are shown in the Wizard's text window, not in a dialog that cuts them off
        self.assertIn('show(ku.message(platform_name, kind, current, latest, bits))', self.src)
        self.assertNotIn('dialog.ok(title, ku.message(', self.src)
        # nothing in it may stop the start-up: the imports are inside the function's try, the call inside one too
        body = self.src[self.src.index('def kodi_version_update_check('):]
        self.assertLess(body.index('    try:'), body.index('import json'))
        self.assertIn("state['failed'] = now", self.src)
        startup = (WIZARD / 'startup.py').read_text(encoding='utf-8')
        call = startup.index('    kodi_version_update_check()')
        self.assertIn('try:', startup[call - 200:call])

    def test_the_menu_item_checks_rather_than_promises(self):
        menu = (WIZARD / 'resources' / 'libs' / 'gui' / 'main_menu.py').read_text(encoding='utf-8')
        self.assertIn("'בדיקת גרסת קודי'", menu)
        self.assertNotIn('עדכון גרסת קודי', menu)


if __name__ == '__main__':
    unittest.main()
