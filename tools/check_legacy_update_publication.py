"""Reject a public update note that legacy automatic updaters cannot fetch."""

from pathlib import Path
import re
import sys
from urllib.parse import urlparse


def verify(root, require_artifact=True):
    root = Path(root)
    assets = root / 'wizard/assets'
    note = (assets / 'notification_files/quick_update.txt').read_text(
        encoding='utf-8')
    match = re.match(r'^([0-9]{1,20})\|\|\|', note)
    if not match:
        raise ValueError('invalid quick-update note ID')
    note_id = match.group(1)
    snapshot = assets / 'build_versions' / (note_id + '.txt')
    if not snapshot.is_file():
        raise ValueError('legacy automatic-update manifest is missing: ' + str(snapshot))
    text = snapshot.read_text(encoding='utf-8')
    gui = re.search(r'^gui="([^"]+)"$', text, re.M)
    if not gui:
        raise ValueError('legacy update manifest has no quickfix URL')
    url = urlparse(gui.group(1))
    prefix = '/MoranTheKing/Kodi-POV-IL/raw/main/dist/'
    if url.scheme != 'https' or url.netloc != 'github.com' or not url.path.startswith(prefix):
        raise ValueError('legacy quickfix URL does not point to the public artifact channel')
    filename = url.path[len(prefix):]
    if '/' in filename or not re.fullmatch(r'Kodi-POV-IL-FENtastic-quickfix-[0-9.]+\.zip', filename):
        raise ValueError('invalid legacy quickfix artifact name')
    if require_artifact and not (root / 'dist' / filename).is_file():
        raise ValueError('legacy quickfix artifact is absent: ' + filename)
    return note_id, filename


if __name__ == '__main__':
    note, artifact = verify(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
    print('Legacy automatic update #{0}: {1}'.format(note, artifact))
