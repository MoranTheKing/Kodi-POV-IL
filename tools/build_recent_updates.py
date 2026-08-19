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

AND FROM THE ARCHIVE ITSELF, WHICH IS THE POINT OF THIS PARAGRAPH. "Regenerate
and it is right again" was true only where the whole history is present. On a
SHALLOW CLONE it is false and quietly so: this ran in a checkout with 56
commits, found six touching quick_update.txt, and reported "7 note(s) of 7
available" -- a success line for an archive that had just dropped notes 591
through 594, which users could see on their home screen at that moment. The
tool could not tell "there are only seven notes in the world" from "I can only
see seven".

So the file it is about to overwrite is now a SOURCE as well as the output. It
is the published truth, it is in the working tree, and it needs no network.
Git history still wins where it exists -- it is the older, more authoritative
record -- but nothing that was already published can be lost by regenerating,
on any clone, ever. The floor check below is the tripwire for the same class of
mistake arriving some other way.

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


def _split_archive(text: str) -> list[str]:
    """The existing archive back into the note bodies it was built from."""
    starts = [m.start() for m in re.finditer(r'(?m)^\d+\|\|\|', text)]
    return [text[a:b].strip('\n')
            for a, b in zip(starts, starts[1:] + [len(text)])]


def collect() -> list[tuple[int, str]]:
    """Every distinct note id ever published, newest first."""
    commits = _git('log', '--format=%H', '--', NOTE).decode().split()
    seen: set[int] = set()
    notes: list[tuple[int, str]] = []
    # The working copy first: at release time the new note is written before
    # this runs, so reading only committed history would publish an archive
    # that is missing the very update announcing it.
    #
    # LAZILY, and stopping at KEEP. `git log` is newest-first and note ids only
    # increase, so the first KEEP distinct ids it yields ARE the newest KEEP.
    # Reading all of them eagerly meant one `git show` per commit -- 631 of
    # them, each a separate lazy blob fetch on a blobless clone -- and took
    # nearly four minutes to compute ten records.
    def _candidates():
        yield (ROOT / NOTE).read_bytes()
        for c in commits:
            yield _git('show', c + ':' + NOTE)

    for raw in _candidates():
        body = raw.decode('utf-8', 'replace').replace('\r\n', '\n').strip('\n')
        head = HEAD_RE.match(body)
        if not head:
            continue
        note_id = int(head.group(1))
        if note_id in seen:
            continue
        seen.add(note_id)
        notes.append((note_id, body))
        if len(notes) >= KEEP:
            break
    # ...then whatever the archive already holds that history could not reach.
    # Last, so a note recovered from git always wins over the archive's copy of
    # it: git is the older record and the archive is derived from it.
    if len(notes) < KEEP and OUT.exists():
        prior = OUT.read_text(encoding='utf-8').replace('\r\n', '\n')
        for body in _split_archive(prior):
            note_id = int(HEAD_RE.match(body).group(1))
            if note_id in seen:
                continue
            seen.add(note_id)
            notes.append((note_id, body))
    notes.sort(key=lambda item: -item[0])
    return notes


def main() -> int:
    before = []
    if OUT.exists():
        before = [int(m.group(1)) for m in re.finditer(
            r'(?m)^(\d+)\|\|\|',
            OUT.read_text(encoding='utf-8').replace('\r\n', '\n'))]
    notes = collect()
    kept = notes[:KEEP]
    text = '\n'.join(body for _, body in kept) + '\n'

    # EVERY CHECK BELOW RUNS BEFORE THE WRITE.
    #
    # They used to run after it, which meant each one reported a problem it had
    # already caused: the bad archive was on disk, and the exception only told
    # you so. A test asking "does the file on disk survive a refused build"
    # caught it. Nothing here needs the file to exist -- the round-trip check
    # parses the STRING -- so there is no reason to write first and no excuse
    # for having done it.

    # Prove the text parses back into exactly what went in --
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

    # A NOTE MAY ONLY LEAVE BY BEING PUSHED OFF THE BOTTOM.
    #
    # The first version of this check said "never fewer ids than before", and
    # it was wrong the moment it ran for real: adding 601 pushes 591 out of a
    # ten-item window, which is the window doing its job. The property that
    # actually matters is that every id which left is OLDER than everything
    # kept. An id missing from the middle is a hole -- something became
    # unreachable -- and that is the shallow-clone failure this guards.
    if expected:
        holes = sorted((i for i in set(before) - set(expected)
                        if i > min(expected)), reverse=True)
        if holes:
            raise SystemExit(
                'regenerating would DROP published note(s) from INSIDE the '
                'window: %s\nthey are newer than the oldest note kept (%d), '
                'so they were not pushed out -- they became unreachable. Work '
                'out why before overwriting the archive.'
                % (', '.join(str(i) for i in holes), min(expected)))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding='utf-8')

    print('recent_updates.txt: %d note(s) of %d available -> %s'
          % (len(kept), len(notes), ', '.join(str(i) for i in expected)))
    recovered = sorted(set(expected) - set(before), reverse=True)
    if recovered:
        print('  new since the last archive: %s'
              % ', '.join(str(i) for i in recovered))
    print('  %d bytes' % len(text.encode('utf-8')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
