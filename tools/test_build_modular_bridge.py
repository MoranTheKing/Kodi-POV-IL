"""The legacy quickfix bridge must fail closed before replacing its healer."""

import tempfile
import unittest
from pathlib import Path

from build_modular_bridge import build


class BridgeGateTests(unittest.TestCase):
    def test_missing_legacy_bootstrap_never_writes_zip(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / 'bridge.zip'
            with self.assertRaisesRegex(ValueError, 'bootstrap is unverified'):
                build(root / 'candidate', output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
