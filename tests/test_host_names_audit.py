"""The release gate reads what the Wizard's POV patch modules ask POV for by
name (Wizard 0.4.97).

The hooks are applied by text anchors.  POV 6.11.03 kept every anchor, but
its modules.dialogs stopped importing confirm_dialog (it calls
ku.confirm_dialog), so pov_continue_watching.dropped_choice() -- handed that
module's globals() -- raised KeyError on native['confirm_dialog'] and every
"remove from continue watching" ended in "POV error".  The pin verifier said
"verified".  audit_host_names() is the missing check."""
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = runpy.run_path(str(ROOT / '.github/scripts/verify_pov_patches.py'))
audit = VERIFY['audit_host_names']
PATCHES = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches'


def tree(base, files):
    for name, text in files.items():
        path = Path(base) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, 'utf-8')
    return Path(base)


def run(host_files, patch_files):
    with tempfile.TemporaryDirectory() as temp:
        host = tree(Path(temp) / 'host', {'resources/lib/' + k: v for k, v in host_files.items()})
        patches = tree(Path(temp) / 'patches', patch_files)
        return audit(host, patches)


CALLER = '''from modules import kodi_utils as ku
from indexers.local_api import local_droplist
%s
def dropped_choice(params):
    import pov_thing
    return pov_thing.act(params, globals())
'''


class NativeNames(unittest.TestCase):

    def test_a_name_the_calling_module_does_not_have_is_a_problem(self):
        patch = "def act(params, native):\n    return native['confirm_dialog'](text='x')\n"
        found = run({'modules/dialogs.py': CALLER % ''}, {'pov_thing.py': patch})
        self.assertEqual(len(found), 1, found)
        self.assertIn("pov_thing.py:2 act() reads native['confirm_dialog']", found[0])
        self.assertIn('modules/dialogs.py', found[0])

    def test_every_way_a_module_gets_a_name_counts(self):
        patch = ("def act(params, native):\n    return [native[k] for k in ()] or (native['a'], native['b'], "
                 "native['c'], native['d'], native['e'], native['f'], native['ku'], native['local_droplist'])\n")
        have = ("def a(): pass\nclass b: pass\nc, (d, e) = 1, (2, 3)\ntry:\n    import f\n"
                "except ImportError:\n    f = None\n")
        self.assertEqual(run({'modules/dialogs.py': CALLER % have}, {'pov_thing.py': patch}), [])

    def test_a_name_the_patch_itself_stores_is_not_asked_of_pov(self):
        patch = "def act(params, native):\n    native['routing'] = 1\n    return native['routing']\n"
        self.assertEqual(run({'modules/dialogs.py': CALLER % ''}, {'pov_thing.py': patch}), [])

    def test_a_name_read_before_the_patch_replaces_it_is_povs_to_provide(self):
        # pov_directory_latency: original = native['routing'] ... native['routing'] = routing
        patch = ("def act(params, native):\n    original = native['routing']\n"
                 "    native['routing'] = lambda: original\n    return native['routing']\n")
        found = run({'modules/dialogs.py': CALLER % ''}, {'pov_thing.py': patch})
        self.assertEqual(len(found), 1, found)
        self.assertIn("pov_thing.py:2 act() reads native['routing']", found[0])
        self.assertEqual(run({'modules/dialogs.py': CALLER % 'def routing(): pass'}, {'pov_thing.py': patch}), [])

    def test_a_function_shared_by_two_modules_may_take_a_name_from_either(self):
        patch = ("def act(native, provider):\n    return native['call_trakt'] if provider == 'trakt' "
                 "else native['call_mdblist']\n")
        trakt = "def call_trakt(): pass\ndef f():\n    import pov_thing\n    return pov_thing.act(globals(), 'trakt')\n"
        mdbl = "def call_mdblist(): pass\ndef f():\n    import pov_thing\n    return pov_thing.act(globals(), 'mdblist')\n"
        self.assertEqual(run({'indexers/trakt_api.py': trakt, 'indexers/mdblist_api.py': mdbl},
                             {'pov_thing.py': patch}), [])
        gone = run({'indexers/trakt_api.py': trakt.replace('call_trakt', 'request_trakt'),
                    'indexers/mdblist_api.py': mdbl}, {'pov_thing.py': patch})
        self.assertEqual(len(found := gone), 1, found)
        self.assertIn("native['call_trakt']", found[0])

    def test_the_argument_position_of_globals_is_followed(self):
        patch = "def act(native, params):\n    return params['title'], native['gone']\n"
        caller = "def f(params):\n    import pov_thing\n    return pov_thing.act(globals(), params)\n"
        found = run({'modules/x.py': caller}, {'pov_thing.py': patch})
        self.assertEqual(len(found), 1, found)
        self.assertIn("native['gone']", found[0])

    def test_a_missing_patch_function_is_a_problem(self):
        caller = "def f():\n    import pov_thing\n    return pov_thing.renamed(globals())\n"
        found = run({'modules/x.py': caller}, {'pov_thing.py': 'def act(native):\n    return 1\n'})
        self.assertEqual(found, ['modules/x.py calls pov_thing.renamed, which does not exist'])

    def test_a_module_that_star_imports_is_not_judged(self):
        patch = "def act(params, native):\n    return native['anything']\n"
        self.assertEqual(run({'modules/dialogs.py': 'from modules.kodi_utils import *\n' + CALLER % ''},
                             {'pov_thing.py': patch}), [])


class ImportedNames(unittest.TestCase):
    HOST = {'modules/kodi_utils.py': 'def confirm_dialog(**kw): pass\nnotify = 1\n',
            'modules/settings.py': 'def metadata_user_info(): pass\n',
            'indexers/local_api.py': 'def local_droplist(): pass\n',
            'indexers/__init__.py': ''}

    def test_names_and_attributes_pov_has_are_fine(self):
        patch = ("def act():\n    from modules import kodi_utils, settings\n"
                 "    from indexers.local_api import local_droplist\n    import indexers.local_api as api\n"
                 "    from elsewhere import anything\n    import xbmcgui\n"
                 "    return (kodi_utils.confirm_dialog, kodi_utils.notify, settings.metadata_user_info,\n"
                 "            api.local_droplist, kodi_utils.__dict__, xbmcgui.Dialog, anything.x)\n")
        self.assertEqual(run(self.HOST, {'pov_thing.py': patch}), [])

    def test_a_name_imported_from_a_pov_module_that_lacks_it(self):
        patch = "def act():\n    from indexers.local_api import local_droplist, add_to_sync\n"
        found = run(self.HOST, {'pov_thing.py': patch})
        self.assertEqual(found, ['pov_thing.py:2 imports add_to_sync from indexers.local_api, which has no such name'])

    def test_an_attribute_a_pov_module_lacks(self):
        patch = ("def act():\n    from modules import kodi_utils\n    import indexers.local_api as api\n"
                 "    return kodi_utils.widget_refresh(), api.remove_from_sync\n")
        found = run(self.HOST, {'pov_thing.py': patch})
        self.assertEqual(sorted(found), [
            'pov_thing.py:4 uses api.remove_from_sync, which indexers.local_api does not define',
            'pov_thing.py:4 uses kodi_utils.widget_refresh, which modules.kodi_utils does not define'])

    def test_a_name_the_file_also_binds_itself_is_left_alone(self):
        patch = ("def act(settings):\n    from modules import kodi_utils, settings as s2\n"
                 "    kodi_utils = object()\n    return kodi_utils.whatever, settings.whatever\n"
                 "def other():\n    from modules import settings\n    return settings.gone\n")
        self.assertEqual(run(self.HOST, {'pov_thing.py': patch}), [])

    def test_only_pov_patch_modules_are_read(self):
        patch = "def act():\n    from modules import kodi_utils\n    return kodi_utils.gone\n"
        self.assertEqual(run(self.HOST, {'umbrella_thing.py': patch}), [])
        self.assertEqual(len(run(self.HOST, {'pov_thing.py': patch})), 1)


class TheRealPatches(unittest.TestCase):
    # modules.dialogs as POV 6.11.03 has it, around the Wizard's hook
    DIALOGS = ("import json\nfrom indexers import metadata\nfrom modules import kodi_utils as ku, settings\n"
               "ls, get_setting, set_setting = ku.local_string, ku.get_setting, ku.set_setting\n"
               "def dropped_choice(params):\n    import pov_continue_watching\n"
               "    return pov_continue_watching.dropped_choice(params, globals())\n")

    def host(self, temp):
        return tree(Path(temp) / 'host', {'resources/lib/modules/dialogs.py': self.DIALOGS})

    def test_the_shipped_patch_modules_ask_that_dialogs_module_for_nothing_it_lacks(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(audit(self.host(temp), PATCHES), [])

    def test_the_patch_as_it_was_before_the_fix_is_caught(self):
        source = (PATCHES / 'pov_continue_watching.py').read_text('utf-8')
        fixed = "confirm = native.get('confirm_dialog') or kodi_utils.confirm_dialog"
        self.assertEqual(source.count(fixed), 1)
        with tempfile.TemporaryDirectory() as temp:
            patches = tree(Path(temp) / 'patches', {
                'pov_continue_watching.py': source.replace(fixed, "confirm = native['confirm_dialog']")})
            found = audit(self.host(temp), patches)
        self.assertEqual(len(found), 1, found)
        self.assertIn("dropped_choice() reads native['confirm_dialog'], which modules/dialogs.py does not define",
                      found[0])


if __name__ == '__main__':
    unittest.main()
