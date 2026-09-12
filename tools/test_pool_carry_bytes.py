"""The provisioned block must be unchanged on DISK, including on Windows."""
import importlib.util
from pathlib import Path
import re
import tempfile
import zipfile

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pool_packager_test', root / 'build_ai_subtitles_packages.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)
with tempfile.TemporaryDirectory() as temp:
    directory = Path(temp)
    stage = directory / 'stage'
    (stage / 'resources/lib').mkdir(parents=True)
    target = stage / 'resources/lib/pool.py'
    # Artificial non-production fixture; no deployed secret is accessed.
    old = (b'old_logic = True\n# __POOL_KEY_BEGIN__\n'
           b'def _pool_key():\n    import base64\n'
           b'    return base64.b64decode(b"Zml4dHVyZQ==").decode()\n'
           b'# __POOL_KEY_END__\n')
    staged = (b'new_logic = True\n# __POOL_KEY_BEGIN__\n'
              b'def _pool_key():\n    return ""\n# __POOL_KEY_END__\n')
    target.write_bytes(staged)
    previous = directory / 'previous.zip'
    with zipfile.ZipFile(previous, 'w') as z:
        z.writestr('service.subtitles.kodipovilai/resources/lib/pool.py', old)
    assert packager.carry_pool_key_block(stage, previous)
    key = re.compile(rb'__POOL_KEY_BEGIN__.*?__POOL_KEY_END__', re.S)
    saved = target.read_bytes()
    assert key.search(saved).group() == key.search(old).group()
    assert key.sub(b'BLOCK', saved) == key.sub(b'BLOCK', staged)
print('PASS: carried bytes on disk and new logic both preserved')
