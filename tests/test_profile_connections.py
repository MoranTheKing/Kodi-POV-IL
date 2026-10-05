import importlib.util
import tempfile
import types
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from test_build_profiles import LIBS, store
from test_provisioning_gate import _load_function


class AccountInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.master = Path(self.tmp.name)
        self.profile = dict(id=1, directory='profiles/Guest')
        self.dest = self.master / self.profile['directory']; self.dest.mkdir(parents=True)
        source = self.master / 'addon_data/plugin.video.pov/settings.xml'
        source.parent.mkdir(parents=True)
        source.write_text('<settings><setting id="tb.token">QA_TORBOX</setting>'
            '<setting id="torbox.token">QA_COMPAT_TORBOX</setting>'
            '<setting id="trakt.token">QA_TRAKT</setting><setting id="trakt_user">QA</setting>'
            '<setting id="mdblist.token">QA_MDBLIST</setting><setting id="tmdb.session_id">QA_TMDB</setting>'
            '<setting id="unrelated.preference">KEEP</setting></settings>')
        modules = {'resources.libs': types.SimpleNamespace(profile_store=store),
                   'resources.libs.parental_profiles': types.SimpleNamespace(atomic_write=self.atomic)}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('profile_connections_test', LIBS / 'profile_connections.py')
            self.module = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.module)
        self.modules = modules

    @staticmethod
    def atomic(path, content):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)

    def copy(self, selected):
        with patch.dict(sys.modules, self.modules):
            self.module.copy_selected(str(self.master), self.profile, selected)
        path = self.dest / 'addon_data/plugin.video.pov/settings.xml'
        return {row.get('id'): row.text for row in ET.parse(path).getroot()}

    def test_debrid_copies_current_and_legacy_torbox_fields_without_tracking_or_preferences(self):
        values = self.copy(['torbox'])
        self.assertEqual(values['tb.token'], 'QA_TORBOX')
        self.assertEqual(values['torbox.token'], 'QA_COMPAT_TORBOX')
        self.assertNotIn('trakt.token', values)
        self.assertNotIn('mdblist.token', values)
        self.assertNotIn('unrelated.preference', values)
        self.assertFalse(list(self.dest.rglob('*.db')))

    def test_only_explicitly_selected_tracking_accounts_are_inherited(self):
        values = self.copy(['trakt', 'mdblist'])
        self.assertEqual(values['trakt.token'], 'QA_TRAKT')
        self.assertEqual(values['mdblist.token'], 'QA_MDBLIST')
        self.assertNotIn('tb.token', values)
        self.assertNotIn('tmdb.session_id', values)

    def test_picker_preselects_debrid_only_and_cancel_is_distinct_from_empty_selection(self):
        calls = []
        dialog = types.SimpleNamespace(multiselect=lambda title, labels, preselect: calls.append((labels, preselect)))
        with patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Dialog=lambda: dialog)}):
            self.assertIsNone(self.module.choose(str(self.master)))
        self.assertEqual(calls[0][1], [0])
        self.assertEqual(len(calls[0][0]), 4)
        dialog.multiselect = lambda *args, **kwargs: []
        with patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Dialog=lambda: dialog)}):
            self.assertEqual(self.module.choose(str(self.master)), [])

    def test_master_and_unknown_groups_are_rejected(self):
        for profile, selected in ((dict(id=0), ['torbox']), (self.profile, ['unknown'])):
            with self.assertRaises(ValueError), patch.dict(sys.modules, self.modules):
                self.module.copy_selected(str(self.master), profile, selected)


class RetentionTests(unittest.TestCase):
    def test_only_requested_skin_and_exact_retention_dialog_are_accepted(self):
        current = ['skin.estuary']; visible = [True]; labels = ['Skin', 'Keep this skin?']; clicks = []
        kodi = types.SimpleNamespace(getSkinDir=lambda: current[0], getCondVisibility=lambda _: visible[0],
            getLocalizedString=lambda key: 'Skin' if key == 13123 else 'Keep this skin?',
            getInfoLabel=lambda key: labels[0] if key.endswith('(1)') else labels[1], executebuiltin=clicks.append)
        fn = _load_function(LIBS / 'build_skin.py', 'confirm_requested_skin', dict(xbmc=kodi))
        self.assertTrue(fn('skin.estuary'))
        current[0] = 'skin.povil.nox'; self.assertFalse(fn('skin.estuary'))
        current[0] = 'skin.estuary'; labels[1] = 'Allow unknown sources?'; self.assertFalse(fn('skin.estuary'))
        self.assertEqual(clicks, ['SendClick(10100,11)'])
