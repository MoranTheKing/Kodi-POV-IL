"""Connected provider tiles must not depend on optional display names."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'plugin.program.kodipovilwizard/resources/libs/patches/pov_visibility_mgr.py'


class ServiceVisibilityTests(unittest.TestCase):
    def load(self, settings):
        addon=types.SimpleNamespace(Addon=lambda ident:types.SimpleNamespace(
            getSetting=lambda key:settings.get(ident,{}).get(key,'')))
        modules={'xbmc':types.SimpleNamespace(LOGINFO=1,LOGWARNING=2,log=lambda *args:None),
                 'xbmcaddon':addon, 'xbmcgui':types.SimpleNamespace(),
                 'xbmcvfs':types.SimpleNamespace()}
        with mock.patch.dict(sys.modules,modules):
            spec=importlib.util.spec_from_file_location('qa_service_visibility',SOURCE)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_native_pov_token_without_username_is_connected(self):
        module=self.load({'plugin.video.pov':{'trakt.token':'QA_OPAQUE'}})
        self.assertTrue(module._read_states()['trakt'])

    def test_account_manager_and_native_credentials_are_both_recognized(self):
        for settings in ({'script.module.acctmgr':{'trakt.token':'QA_OPAQUE'}},
                         {'plugin.video.pov':{'trakt_user':'tester'}}):
            self.assertTrue(self.load(settings)._read_states()['trakt'])
        self.assertFalse(self.load({})._read_states()['trakt'])

    def test_refresh_does_not_reenter_a_current_favourites_writer(self):
        module=self.load({})
        module._home=lambda:types.SimpleNamespace(getProperty=lambda key:'writer')
        module.xbmc.getSkinDir=lambda: self.fail('Nested refresh reached filesystem')
        module._trigger_favourites_refresh()

    def test_profile_switch_bypasses_both_cache_tiers_even_with_same_fingerprint(self):
        for fingerprint in ('identical-mtime-and-size', ''):
            with self.subTest(fingerprint=fingerprint):
                module=self.load({})
                props={}
                window=types.SimpleNamespace(getProperty=lambda key:props.get(key,''),
                                             setProperty=lambda key,value:props.__setitem__(key,value))
                module._home=lambda:window
                module._profile_key=lambda:'master'
                module._fingerprint=lambda:fingerprint
                states=mock.Mock(side_effect=[{'mdblist':False}, {'mdblist':True}, {'mdblist':False}])
                module._read_states=states
                module._trigger_favourites_refresh=lambda:self.fail('Cross-profile refresh')
                self.assertFalse(module.is_service_active('mdblist'))
                self.assertFalse(module.is_service_active('mdblist'))
                self.assertEqual(states.call_count,1)
                module._profile_key=lambda:'guest'
                self.assertTrue(module.is_service_active('mdblist'))
                self.assertEqual(json.loads(props[module._WIN_PROP])['profile'],'guest')
                module._mem.clear()  # another plugin interpreter reads the global Home property
                module._profile_key=lambda:'master'
                self.assertFalse(module.is_service_active('mdblist'))
                self.assertEqual(states.call_count,3)

    def test_connected_mdblist_uses_merged_personal_routes_in_both_tabs(self):
        module=self.load({'plugin.video.pov':{'mdblist.token':'QA_OPAQUE'}})
        module._profile_key=lambda:'master'
        module._home=lambda:None
        module._fingerprint=lambda:''
        for name, route in module._MDBLIST_ROWS.items():
            items=[dict(mode=route['mode'],action='mdblist_watchlist',name=route['name'])]
            result=module.filter_navigator_list(items,name)
            self.assertEqual(result[0]['action'],route['action'])


if __name__=='__main__':unittest.main()
