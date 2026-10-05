"""An old subtitle service yields only to a verified next-boot request."""

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


SOURCE = (Path(__file__).resolve().parents[1] /
          'service.subtitles.kodipovilai/resources/lib/modular_service_handoff.py')
spec = importlib.util.spec_from_file_location('modular_service_handoff', SOURCE)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class ServiceHandoffTests(unittest.TestCase):
    def test_yields_after_new_boot_only_when_staged_version_matches(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            userdata = root / 'userdata'
            userdata.mkdir()
            stage = root / '.kodipovil-ms-new'
            stage.mkdir()
            (stage / 'addon.xml').write_text(
                '<addon id="service.subtitles.kodipovilai" version="0.3.15" />',
                encoding='utf-8')
            request = userdata / handoff.REQUEST
            plan = {'schema': 1, 'addon_id': handoff.ADDON_ID,
                    'token': 'a' * 32, 'version': '0.3.15',
                    'created': 1000, 'expires': 2000, 'creator_pid': 11}
            request.write_text(json.dumps(plan), encoding='utf-8')
            vfs = types.SimpleNamespace(translatePath=lambda uri: str(
                userdata if uri == 'special://profile/' else root))
            with mock.patch.dict(sys.modules, {'xbmcvfs': vfs}), \
                    mock.patch.object(handoff.time, 'time', return_value=1500), \
                    mock.patch.object(handoff.os, 'getpid', return_value=11):
                self.assertFalse(handoff.maybe_yield())
            with mock.patch.dict(sys.modules, {'xbmcvfs': vfs}), \
                    mock.patch.object(handoff.time, 'time', return_value=1500), \
                    mock.patch.object(handoff.os, 'getpid', return_value=12):
                self.assertTrue(handoff.maybe_yield())
            ack = json.loads((userdata / handoff.ACK).read_text(encoding='utf-8'))
            self.assertEqual(ack['token'], plan['token'])
            (stage / 'addon.xml').write_text(
                '<addon id="service.subtitles.kodipovilai" version="0.3.14" />',
                encoding='utf-8')
            with mock.patch.dict(sys.modules, {'xbmcvfs': vfs}), \
                    mock.patch.object(handoff.time, 'time', return_value=1500), \
                    mock.patch.object(handoff.os, 'getpid', return_value=12):
                self.assertFalse(handoff.maybe_yield())


if __name__ == '__main__':
    unittest.main()
