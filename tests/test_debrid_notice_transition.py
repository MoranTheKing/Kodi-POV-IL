"""One owner emits debrid notices during the old-to-new service handoff."""

import ast
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches'
        / 'pov_custom_debrid_toasts.py')


class DebridNoticeTransitionTests(unittest.TestCase):
    def test_old_service_prevents_second_notice_worker(self):
        tree = ast.parse(HOOK.read_text(encoding='utf-8'))
        names = {'_legacy_service_owns_notice', 'run'}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in names]
        self.assertEqual({node.name for node in functions}, names)
        opened = []
        addon = types.SimpleNamespace(getAddonInfo=lambda _key: '0.2.566')
        namespace = {
            'xbmcaddon': types.SimpleNamespace(Addon=lambda _aid: addon),
            'xbmcgui': types.SimpleNamespace(Window=lambda _id: opened.append(_id)),
            'xbmc': types.SimpleNamespace(LOGERROR=4, log=lambda *_a: None),
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(HOOK), 'exec'),
             namespace)
        namespace['run']({})
        self.assertEqual(opened, [])
        addon.getAddonInfo = lambda _key: '0.3.15'
        self.assertFalse(namespace['_legacy_service_owns_notice']())


if __name__ == '__main__':
    unittest.main()
