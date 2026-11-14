"""The profile picker's warm-up reads the files the chosen profile will load, and nothing more."""
import importlib.util
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'


def _load():
    spec = importlib.util.spec_from_file_location('login_warm_under_test', WIZARD / 'login_warm.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path, data=b'x'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
    return path


class Tree(unittest.TestCase):
    def setUp(self):
        self.lw = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.system = Path(self.tmp.name) / 'system'
        self.master = self.home / 'userdata'
        addons = self.home / 'addons'
        _write(self.master / 'guisettings.xml', '<settings><setting id="lookandfeel.skin">skin.povil.old</setting></settings>')
        _write(self.master / 'profiles.xml',
               '<profiles><profile><id>0</id><directory pathversion="1">special://masterprofile/</directory></profile>'
               '<profile><id>1</id><directory pathversion="1">profiles/Kid/</directory></profile></profiles>')
        _write(self.master / 'profiles' / 'Kid' / 'guisettings.xml',
               '<settings><setting id="lookandfeel.skin" default="true">skin.estuary</setting></settings>')
        _write(addons / 'skin.povil.old' / 'xml' / 'Home.xml', b'h' * 10)
        _write(addons / 'skin.povil.old' / 'xml' / 'notes.txt', b'no')
        _write(addons / 'skin.povil.old' / 'media' / 'Textures.xbt', b't' * 50)
        _write(addons / 'skin.povil.old' / 'language' / 'resource.language.he_il' / 'strings.po', b'l' * 8)
        _write(addons / 'skin.povil.old' / 'language' / 'resource.language.fr_fr' / 'strings.po', b'f' * 8)
        _write(self.system / 'addons' / 'skin.estuary' / 'addon.xml',
               '<addon id="skin.estuary"><extension point="xbmc.gui.skin">'
               '<res width="1920" height="1080" aspect="16:9" default="true" folder="layout" /></extension></addon>')
        _write(self.system / 'addons' / 'skin.estuary' / 'layout' / 'Home.xml', b'e' * 7)
        _write(self.system / 'addons' / 'skin.estuary' / 'xml' / 'Old.xml', b'no')
        _write(self.system / 'addons' / 'skin.estuary' / 'media' / 'Textures.xbt', b'no' * 50)
        _write(self.system / 'addons' / 'skin.estuary' / 'language' / 'resource.language.he_il' / 'strings.po', b'no')
        _write(addons / 'service.a' / 'addon.xml',
               '<addon id="service.a"><requires><import addon="script.module.dep"/><import addon="xbmc.python"/>'
               '</requires><extension point="xbmc.service" library="service.py"/></addon>')
        _write(addons / 'service.a' / 'service.py', b'p' * 5)
        _write(addons / 'service.a' / 'lib' / 'deep.py', b'p' * 6)
        _write(addons / 'service.a' / 'lib' / '__pycache__' / 'deep.cpython-38.pyc', b'c' * 9)
        _write(addons / 'script.module.dep' / 'addon.xml', '<addon id="script.module.dep"/>')
        _write(addons / 'script.module.dep' / 'lib' / 'dep.py', b'd' * 40)
        _write(addons / 'script.module.dep' / 'lib' / '__pycache__' / 'dep.cpython-38.pyc', b'd' * 4)
        _write(addons / 'script.module.dep' / 'lib' / '__pycache__' / 'dep.cpython-311.pyc', b'no')
        _write(addons / 'script.module.dep' / 'lib' / '__pycache__' / 'dep.cpython-38.opt-1.pyc', b'o' * 3)
        _write(addons / 'plugin.other' / 'addon.xml', '<addon id="plugin.other"><extension point="xbmc.python.pluginsource"/></addon>')
        _write(addons / 'plugin.other' / 'main.py', b'o' * 3)
        _write(self.master / 'Database' / 'Addons33.db', b'd' * 20)

    def plan(self):
        return self.lw.plan(str(self.home), str(self.system), str(self.master), 'skin.povil.old', '.cpython-38.pyc')

    def test_only_what_the_profile_is_sure_to_open_in_the_order_it_asks(self):
        self.assertEqual(self.lw.skins(str(self.master), 'skin.povil.old'), ['skin.povil.old', 'skin.estuary'])
        self.assertEqual(self.lw.services(str(self.home / 'addons')), ['service.a', 'script.module.dep'])
        rows = self.plan()
        names = [(stage, os.path.relpath(path, self.tmp.name).replace('\\', '/')) for stage, path, _most in rows]
        self.assertEqual(names, [
            ('skin', 'home/addons/skin.povil.old/xml/Home.xml'),
            ('skin', 'home/addons/skin.povil.old/language/resource.language.he_il/strings.po'),
            ('skin', 'system/addons/skin.estuary/layout/Home.xml'),
            ('database', 'home/userdata/Database/Addons33.db'),
            ('python', 'home/addons/service.a/lib/__pycache__/deep.cpython-38.pyc'),
            ('python', 'home/addons/script.module.dep/lib/__pycache__/dep.cpython-38.pyc'),
            ('textures', 'home/addons/skin.povil.old/media/Textures.xbt'),
        ])

    def test_the_compiled_name_is_the_interpreters_own(self):
        import importlib.util
        import sys
        suffix = self.lw.compiled_suffix()
        self.assertTrue(suffix.startswith('.' + sys.implementation.cache_tag) and suffix.endswith('.pyc'))
        self.assertTrue(importlib.util.cache_from_source('pkg/m.py').endswith('m' + suffix))
        rows = self.lw.plan(str(self.home), str(self.system), str(self.master), 'skin.povil.old', '.cpython-38.opt-1.pyc')
        self.assertEqual([os.path.basename(p) for stage, p, _ in rows if stage == 'python'], ['dep.cpython-38.opt-1.pyc'])

    def test_reads_everything_once_and_changes_nothing(self):
        before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in Path(self.tmp.name).rglob('*') if p.is_file()}
        files, total, ended = self.lw.warm(self.plan(), lambda: True)
        self.assertEqual((files, total, ended), (7, 10 + 8 + 7 + 20 + 9 + 4 + 50, 'done'))
        after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in Path(self.tmp.name).rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_stops_when_the_picker_closes(self):
        self.assertEqual(self.lw.warm(self.plan(), lambda: False), (0, 0, 'picker closed'))
        asked = []

        def open_for_two():
            asked.append(1)
            return len(asked) <= 1
        rows = self.plan() * 10
        files, _total, ended = self.lw.warm(rows, open_for_two)
        self.assertEqual(ended, 'picker closed')
        self.assertEqual(files, 16)

    def test_budgets_end_the_reading(self):
        ticks = iter(range(0, 10000, 10))
        files, _total, ended = self.lw.warm(self.plan(), lambda: True, clock=lambda: float(next(ticks)))
        self.assertEqual(ended, 'budget')
        self.assertLess(files, 7)
        self.lw.BUDGET_BYTES = 12
        self.assertEqual(self.lw.warm(self.plan(), lambda: True)[2], 'budget')

    def test_a_file_that_cannot_be_read_is_passed_over(self):
        rows = [('skin', str(self.home / 'missing.xml'), 10)] + self.plan()
        self.assertEqual(self.lw.warm(rows, lambda: True)[0], 7)

    def test_big_files_are_read_up_to_their_cap(self):
        big = _write(self.home / 'big.xbt', b'b' * 3000)
        self.lw.CHUNK = 1024
        self.assertEqual(self.lw.warm([('textures', str(big), 2048)], lambda: True), (1, 2048, 'done'))


class Hook(unittest.TestCase):
    def test_the_design_starts_the_warm_up_and_the_script_only_reads(self):
        design = ET.parse(WIZARD / 'resources' / 'skins' / 'Default' / '1080i' / 'ProfileLogin.xml').getroot()
        self.assertEqual([a.text for a in design.findall('onload')],
                         ['RunScript(special://home/addons/plugin.program.kodipovilwizard/login_warm.py)'])
        source = (WIZARD / 'login_warm.py').read_text(encoding='utf-8')
        for word in ("'w'", "'wb'", "'a'", 'os.remove', 'os.replace', 'setSetting', 'executebuiltin', 'executeJSONRPC',
                     'import requests', 'urlopen', 'threading', 'getaddrinfo', 'socket'):
            self.assertNotIn(word, source)


if __name__ == '__main__':
    unittest.main()
