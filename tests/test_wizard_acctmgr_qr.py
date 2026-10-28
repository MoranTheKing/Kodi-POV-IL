"""Wizard 0.4.83: Account Manager's sign-in window shows a QR without PIL.

Account Manager 1.2.x draws the QR of its device sign-in (TorBox, Real-Debrid,
Trakt ...) with qrcode, whose images need PIL, and its fallback asks for a
PyPNGImage that the qrcode Kodi installs (6.1.0) does not have. On a device
without PIL the window showed only a code and a link cut short to fit (field
report, 28 Oct 2026). Two Wizard patches hand generate_qr's two give-ups to
patches/acctmgr_qr.py, which draws the PNG with the Wizard's segno.

Set ACCTMGR_TREE to a real script.module.acctmgr folder to also patch and
compile the real base_auth.py.
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

WIZ = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
ENGINE = WIZ / 'resources/libs/patch_engine.py'
CONFIG = WIZ / 'resources/libs/patches/patches_config.py'
PATCHES = WIZ / 'resources/libs/patches'
REL = 'lib/acctmgr/modules/auth/base_auth.py'
PNG = bytes([0x89]) + b'PNG'

# Account Manager 1.2.1 base_auth.py: the constants and generate_qr verbatim.
BASE_AUTH = '''import glob
import os
import threading
import time

from acctmgr.modules import control
from acctmgr.modules import log_utils

QR_TEMP_DIR = 'special://temp/'
QR_DIR_PREFIX = 'acctmgr_auth_qr_'
QR_FILE_NAME = 'qr.png'


class BaseDeviceAuth(object):
    def details(self):
        try:
            device_data = self.get_device_code()
            user_code = str(device_data['user_code'])
            verification_url = str(device_data['verification_url'])
            device_data['device_code']
        except Exception as e:
            return None
        return (device_data.get('qr_data') or verification_url, user_code, verification_url)

    def generate_qr(self, data):
        """Render data to a QR PNG in a unique directory and return its path, or None on failure."""
        try:
            import qrcode
            from qrcode.constants import ERROR_CORRECT_M
        except ImportError:
            log_utils.error('qrcode library not available - showing code/URL without QR')
            return None

        qr_root = control.translatePath(QR_TEMP_DIR)
        qr_dir = os.path.join(
            qr_root, '%s%d' % (QR_DIR_PREFIX, int(time.time() * 1000)))
        path = os.path.join(qr_dir, QR_FILE_NAME)
        try:
            if not os.path.exists(qr_dir):
                os.makedirs(qr_dir)
            qr = qrcode.QRCode(
                version=None,
                error_correction=ERROR_CORRECT_M,
                box_size=10,
                border=2)
            qr.add_data(data)
            qr.make(fit=True)
            try:
                img = qr.make_image(fill_color='black', back_color='white')
            except Exception:
                from qrcode.image.pure import PyPNGImage
                img = qr.make_image(image_factory=PyPNGImage)
            with open(path, 'wb') as f:
                img.save(f)
            return path
        except Exception as e:
            log_utils.error('QR generation failed: %s' % e)
            self._cleanup_qr_files(path)
            return None

    @staticmethod
    def _cleanup_qr_files(path=None):
        try:
            if path:
                qr_dir = os.path.dirname(path)
                try:
                    os.remove(path)
                except OSError:
                    pass
                try:
                    os.rmdir(qr_dir)
                except OSError:
                    pass
        except Exception:
            pass
'''


TORBOX_REL = 'lib/acctmgr/modules/auth/torbox.py'
# Account Manager 1.2.1 torbox.py get_device_code (tab-indented, as shipped).
TORBOX = '''from acctmgr.modules.auth.base_auth import BaseDeviceAuth


class Torbox(BaseDeviceAuth):
    def get_device_code(self):
        data = self.data
        try:
            # Torbox API specs allow verification_url or friendly_verification_url
            url = data.get('verification_url') or data.get('friendly_verification_url')
            return {
                'device_code': data['device_code'],
                'user_code': data['code'],
                'verification_url': url,
                'qr_data': url
            }
        except (KeyError, TypeError, ValueError) as e:
            return None
'''.replace('    ', chr(9))

LONG = 'https://torbox.app/oauth/device?app=AccountManager'
TORBOX_ANSWER = {'device_code': 'dev', 'code': '123456', 'verification_url': LONG,
                 'friendly_verification_url': 'https://tor.box/link',
                 'verification_url_complete': LONG + '&code=123456'}


def _load(name, path, modules=None):
    with patch.dict(sys.modules, modules or {}):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def _qrcode(image=None):
    """A stand-in qrcode package: make_image returns `image`, or raises when
    it is None (no PIL); qrcode.image.pure has no PyPNGImage (6.1.0)."""
    qrcode = types.ModuleType('qrcode')
    constants = types.ModuleType('qrcode.constants')
    constants.ERROR_CORRECT_M = 0
    pure = types.ModuleType('qrcode.image.pure')
    pure.PymagingImage = object

    class QRCode(object):
        def __init__(self, **_kw):
            pass

        def add_data(self, _data):
            pass

        def make(self, fit=True):
            pass

        def make_image(self, **_kw):
            if image is None:
                raise ImportError('No module named PIL')
            return image
    qrcode.QRCode = QRCode
    qrcode.constants = constants
    return {'qrcode': qrcode, 'qrcode.constants': constants,
            'qrcode.image': types.ModuleType('qrcode.image'), 'qrcode.image.pure': pure}


class AccountManagerQrTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.addon = root / 'script.module.acctmgr'
        self.temp = root / 'temp'
        self.temp.mkdir()
        (self.addon / REL).parent.mkdir(parents=True)
        (self.addon / REL).write_text(BASE_AUTH, encoding='utf-8')
        xbmc = types.ModuleType('xbmc')
        xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = range(4)
        xbmcaddon = types.ModuleType('xbmcaddon')
        xbmcaddon.Addon = lambda: types.SimpleNamespace(getSetting=lambda _key: '')
        xbmcvfs = types.ModuleType('xbmcvfs')
        home = 'special://home/addons/'

        def translate(value):
            if value.startswith(home + 'script.module.acctmgr'):
                return str(self.addon) + value[len(home + 'script.module.acctmgr'):]
            if value.startswith(home + 'plugin.program.kodipovilwizard/resources/libs/patches/'):
                return str(PATCHES) + '/'
            return value
        xbmcvfs.translatePath = translate
        common = types.ModuleType('resources.libs.common')
        logging = types.ModuleType('resources.libs.common.logging')
        logging.log = lambda *_a, **_k: None
        common.logging = logging
        self.modules = {'xbmc': xbmc, 'xbmcaddon': xbmcaddon, 'xbmcvfs': xbmcvfs,
                        'resources': types.ModuleType('resources'),
                        'resources.libs': types.ModuleType('resources.libs'),
                        'resources.libs.common': common,
                        'resources.libs.common.logging': logging}
        self.engine = _load('qr_engine', ENGINE, self.modules)
        config = _load('qr_config', CONFIG, self.modules).PATCH_CONFIG
        self.entries = [e for e in config if e['id'].startswith('acctmgr_qr_')]
        self.assertEqual(2, len(self.entries))
        control = types.ModuleType('acctmgr.modules.control')
        control.translatePath = lambda p: str(self.temp) + '/' if p == 'special://temp/' else p
        self.errors = []
        log_utils = types.ModuleType('acctmgr.modules.log_utils')
        log_utils.error = self.errors.append
        modules = types.ModuleType('acctmgr.modules')
        modules.control, modules.log_utils = control, log_utils
        self.am = {'acctmgr': types.ModuleType('acctmgr'), 'acctmgr.modules': modules,
                   'acctmgr.modules.control': control, 'acctmgr.modules.log_utils': log_utils}

    def patched(self):
        with patch.dict(sys.modules, self.modules):
            stats = self.engine.PatchEngine(self.entries).run()
        self.assertEqual(2, stats['applied'], stats)
        return _load('patched_base_auth', self.addon / REL, dict(self.modules, **self.am))

    def qr(self, base_auth, modules):
        with patch.dict(sys.modules, dict(self.modules, **self.am, **modules)):
            sys.modules.pop('acctmgr_qr', None)
            path = base_auth.BaseDeviceAuth().generate_qr('https://torbox.app/oauth/device?app=x&code=123456')
        sys.modules.pop('acctmgr_qr', None)
        return path

    def assertWizardQr(self, path):
        self.assertTrue(path and os.path.isfile(path), path)
        self.assertTrue(os.path.normpath(os.path.dirname(path)).startswith(
            os.path.normpath(str(self.temp / 'acctmgr_auth_qr_'))), path)
        self.assertTrue(path.endswith('qr.png'))
        with open(path, 'rb') as f:
            self.assertEqual(PNG, f.read(4))

    def test_no_qrcode_module_still_gives_a_qr(self):
        base_auth = self.patched()
        self.assertWizardQr(self.qr(base_auth, {'qrcode': None}))

    def test_qrcode_without_pil_still_gives_a_qr(self):
        base_auth = self.patched()
        path = self.qr(base_auth, _qrcode(image=None))
        self.assertWizardQr(path)
        self.assertTrue(any('QR generation failed' in e for e in self.errors))
        # Account Manager's own failed attempt was cleaned up first.
        left = [d for d in os.listdir(self.temp) if not d.endswith('w')]
        self.assertEqual([], left)

    def test_a_working_qrcode_is_left_alone(self):
        base_auth = self.patched()

        class Image(object):
            def save(self, f):
                f.write(b'from-qrcode')
        path = self.qr(base_auth, _qrcode(image=Image()))
        with open(path, 'rb') as f:
            self.assertEqual(b'from-qrcode', f.read())
        self.assertEqual([], self.errors)

    def test_the_patch_is_idempotent(self):
        self.patched()
        with patch.dict(sys.modules, self.modules):
            stats = self.engine.PatchEngine(self.entries).run()
        self.assertEqual(0, stats['applied'])
        self.assertEqual(2, stats['skipped_current'])

    # Account Manager updates itself from its developer's repository, so these
    # patches are optional: no add-on, no file or a moved anchor is a skip,
    # never one of the counts that stop a fresh install.
    FAILURES = ('failed', 'missing', 'anchor_missing', 'malformed', 'legacy_host_deferred')

    def run_engine(self, entries=None):
        with patch.dict(sys.modules, self.modules):
            return self.engine.PatchEngine(entries or self.entries).run()

    def test_without_account_manager_nothing_fails(self):
        shutil.rmtree(self.addon)
        stats = self.run_engine()
        self.assertEqual(2, stats.get('optional_absent'))
        self.assertFalse(any(stats.get(k, 0) for k in self.FAILURES), stats)

    def test_another_account_manager_layout_is_skipped(self):
        (self.addon / REL).unlink()
        stats = self.run_engine()
        self.assertEqual(2, stats.get('optional_absent'))
        self.assertFalse(any(stats.get(k, 0) for k in self.FAILURES), stats)

    def test_a_moved_anchor_is_skipped_not_failed(self):
        moved = BASE_AUTH.replace('log_utils.error(', 'log_utils.log(').replace(
            'self._cleanup_qr_files(path)', 'self._cleanup_qr_files(qr_dir)')
        (self.addon / REL).write_text(moved, encoding='utf-8')
        stats = self.run_engine()
        self.assertEqual(2, stats.get('optional_unmatched'))
        self.assertFalse(any(stats.get(k, 0) for k in self.FAILURES), stats)

    def test_a_patch_not_marked_optional_still_fails(self):
        shutil.rmtree(self.addon)
        required = [dict(e, optional=False) for e in self.entries]
        self.assertEqual(2, self.run_engine(required)['missing'])

    # The TorBox window: TorBox's short link to type, its code-filled link in the QR.
    def torbox(self, answer):
        (self.addon / TORBOX_REL).write_text(TORBOX, encoding='utf-8')
        with patch.dict(sys.modules, self.modules):
            config = _load('link_config', CONFIG, self.modules).PATCH_CONFIG
            entries = [e for e in config if e['id'].startswith('acctmgr_')]
            stats = self.engine.PatchEngine(entries).run()
        self.assertEqual(4, stats['applied'], stats)
        base_auth = _load('link_base_auth', self.addon / REL, dict(self.modules, **self.am))
        modules = dict(self.modules, **self.am, **{'acctmgr.modules.auth.base_auth': base_auth})
        torbox = _load('link_torbox', self.addon / TORBOX_REL, modules)
        auth = torbox.Torbox()
        auth.data = answer
        return auth.details(), base_auth

    def test_the_torbox_window_shows_the_short_link_and_the_qr_carries_the_code(self):
        (qr, code, shown), _base = self.torbox(dict(TORBOX_ANSWER))
        self.assertEqual('https://tor.box/link', shown)
        self.assertEqual(LONG + '&code=123456', qr)
        self.assertEqual('123456', code)

    def test_a_torbox_answer_without_the_extra_links_is_shown_as_before(self):
        answer = {k: v for k, v in TORBOX_ANSWER.items()
                  if k in ('device_code', 'code', 'verification_url')}
        (qr, _code, shown), _base = self.torbox(answer)
        self.assertEqual((LONG, LONG), (qr, shown))

    def test_other_services_are_untouched(self):
        _details, base_auth = self.torbox(dict(TORBOX_ANSWER))

        class RealDebrid(base_auth.BaseDeviceAuth):
            def get_device_code(self):
                return {'device_code': 'd', 'user_code': 'ABCD',
                        'verification_url': 'https://real-debrid.com/device'}
        self.assertEqual(('https://real-debrid.com/device', 'ABCD', 'https://real-debrid.com/device'),
                         RealDebrid().details())

    @unittest.skipUnless(os.environ.get('ACCTMGR_TREE'), 'set ACCTMGR_TREE to a real script.module.acctmgr')
    def test_the_real_torbox_and_base_auth_patch_and_compile(self):
        shutil.rmtree(self.addon)
        shutil.copytree(os.environ['ACCTMGR_TREE'], self.addon)
        with patch.dict(sys.modules, self.modules):
            config = _load('real_config', CONFIG, self.modules).PATCH_CONFIG
            entries = [e for e in config if e['id'].startswith('acctmgr_')]
            first = self.engine.PatchEngine(entries).run()
            second = self.engine.PatchEngine(entries).run()
        self.assertEqual(4, first['applied'], first)
        self.assertEqual(4, second['skipped_current'], second)
        for rel in (REL, TORBOX_REL):
            compile((self.addon / rel).read_text(encoding='utf-8'), rel, 'exec')

    @unittest.skipUnless(os.environ.get('ACCTMGR_TREE'), 'set ACCTMGR_TREE to a real script.module.acctmgr')
    def test_the_real_base_auth_patches_and_compiles(self):
        shutil.rmtree(self.addon)
        shutil.copytree(os.environ['ACCTMGR_TREE'], self.addon)
        with patch.dict(sys.modules, self.modules):
            first = self.engine.PatchEngine(self.entries).run()
            second = self.engine.PatchEngine(self.entries).run()
        self.assertEqual(2, first['applied'], first)
        self.assertEqual(2, second['skipped_current'], second)
        source = (self.addon / REL).read_text(encoding='utf-8')
        compile(source, REL, 'exec')


if __name__ == '__main__':
    unittest.main()
