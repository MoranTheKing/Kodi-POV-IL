#!/usr/bin/env python3
"""Regenerate wizard/assets/notification_files/recent_updates.txt.

The last ten update notes, newest first, in the same shape as
quick_update.txt so one parser reads both:

    <id>|||<title>
    <body, one or more lines>
    <id>|||<title>
    ...

WHERE THE TEXT COMES FROM. Not from a hand-kept list -- from git. Every note
that was ever published is a committed version of quick_update.txt, so the
archive is the actual text users were shown, not a retelling of it. That also
means it cannot drift: regenerate and it is right again.

TEN, HARD. The file is fetched on a home screen, so its size is a running cost
paid by every user on every look. Ten is the cap the whole feature was asked
for, and it is enforced here rather than trusted to the reader -- a reader that
trims is one bad release away from shipping ninety.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTE = 'wizard/assets/notification_files/quick_update.txt'
OUT = ROOT / 'wizard/assets/notification_files/recent_updates.txt'
KEEP = 10
HEAD_RE = re.compile(r'^(\d+)\|\|\|')


def _git(*args: str) -> bytes:
    return subprocess.run(('git',) + args, cwd=ROOT,
                          capture_output=True, check=True).stdout


def collect() -> list[tuple[int, str]]:
    """Every distinct note id ever published, newest first."""
    commits = _git('log', '--format=%H', '--', NOTE).decode().split()
    seen: set[int] = set()
    notes: list[tuple[int, str]] = []
    # The working copy first: at release time the new note is written before
    # this runs, so reading only committed history would publish an archive
    # that is missing the very update announcing it.
    candidates = [(ROOT / NOTE).read_bytes()]
    candidates += [_git('show', c + ':' + NOTE) for c in commits]
    for raw in candidates:
        body = raw.decode('utf-8', 'replace').replace('\r\n', '\n').strip('\n')
        head = HEAD_RE.match(body)
        if not head:
            continue
        note_id = int(head.group(1))
        if note_id in seen:
            continue
        seen.add(note_id)
        notes.append((note_id, body))
    notes.sort(key=lambda item: -item[0])
    return notes


def main() -> int:
    notes = collect()
    kept = notes[:KEEP]
    text = '\n'.join(body for _, body in kept) + '\n'
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding='utf-8')

    # Prove the file we just wrote parses back into exactly what went in --
    # a body containing a line that happens to start with digits and three
    # pipes would split into a record that was never a note.
    parsed = [int(m.group(1)) for m in
              re.finditer(r'(?m)^(\d+)\|\|\|', text)]
    expected = [note_id for note_id, _ in kept]
    if parsed != expected:
        raise SystemExit(
            'recent_updates.txt does not round-trip: parsed %r, expected %r'
            % (parsed, expected))
    if len(kept) > KEEP:
        raise SystemExit('more than %d notes written' % KEEP)

    print('recent_updates.txt: %d note(s) of %d available -> %s'
          % (len(kept), len(notes), ', '.join(str(i) for i in expected)))
    print('  %d bytes' % len(text.encode('utf-8')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
