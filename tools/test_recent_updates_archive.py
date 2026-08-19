"""Regenerating the ten-updates archive must never lose a note.

recent_updates.txt is rebuilt from git -- every note ever published is a
committed version of quick_update.txt -- and the tool's own docstring used to
say that meant it could not drift: "regenerate and it is right again."

That was true only where the whole history is present. On a SHALLOW CLONE it
was false, and quietly so. Building release 601 in a checkout with 56 commits
found six touching quick_update.txt, wrote SEVEN notes, and printed
"7 note(s) of 7 available" -- a success line for an archive that had just
dropped 591 through 594, which users could see on their home screen at that
moment. The tool could not tell "there are only seven notes in the world" from
"I can only see seven".

Two changes came out of that, and this file pins both:

  * the archive it is about to overwrite is now also a SOURCE, so nothing
    already published can be lost on any clone, with no network needed; and
  * a note may only leave by being pushed off the BOTTOM. The first version of
    that check said "never fewer ids than before" and was wrong on its first
    real run -- adding 601 pushes 591 out of a ten-item window, which is the
    window working. The property that matters is that everything which left is
    OLDER than everything kept. A gap in the middle means something became
    unreachable.

Run: python3 tools/test_recent_updates_archive.py
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
TOOL = os.path.join(HERE, 'build_recent_updates.py')
REL = 'wizard/assets/notification_files'

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def ids(text):
    return [int(m.group(1)) for m in re.finditer(r'(?m)^(\d+)\|\|\|', text)]


def note(i, body='body'):
    return '%d|||title %d\n%s %d\n' % (i, i, body, i)


def build_repo(history_ids, archive_ids, head_id):
    """A throwaway git repo whose quick_update.txt history is exactly
    `history_ids` and whose archive already holds `archive_ids`."""
    d = tempfile.mkdtemp(prefix='recentupd-')
    os.makedirs(os.path.join(d, REL))
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=d, check=True)
    subprocess.run(['git', 'config', 'user.email', 't@t'], cwd=d, check=True)
    subprocess.run(['git', 'config', 'user.name', 't'], cwd=d, check=True)
    for i in history_ids:
        with open(os.path.join(d, REL, 'quick_update.txt'), 'w',
                  encoding='utf-8') as f:
            f.write(note(i))
        subprocess.run(['git', 'add', '-A'], cwd=d, check=True)
        subprocess.run(['git', 'commit', '-q', '-m', 'note %d' % i],
                       cwd=d, check=True)
    with open(os.path.join(d, REL, 'quick_update.txt'), 'w',
              encoding='utf-8') as f:
        f.write(note(head_id))
    with open(os.path.join(d, REL, 'recent_updates.txt'), 'w',
              encoding='utf-8') as f:
        f.write(''.join(note(i) for i in sorted(archive_ids, reverse=True)))
    return d


def run(d):
    """Run the real tool against that repo. Returns (rc, stdout+stderr)."""
    tool = os.path.join(d, 'tools', 'build_recent_updates.py')
    os.makedirs(os.path.dirname(tool), exist_ok=True)
    with open(TOOL, encoding='utf-8') as src, \
            open(tool, 'w', encoding='utf-8') as dst:
        dst.write(src.read())
    p = subprocess.run([sys.executable, tool], cwd=d,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def archive(d):
    with open(os.path.join(d, REL, 'recent_updates.txt'), encoding='utf-8') as f:
        return f.read()


# --- 1. the ordinary case: a new note arrives, the window slides -----------
d = build_repo(list(range(590, 601)), list(range(591, 601)), 601)
rc, out = run(d)
got = ids(archive(d))
check('a new note goes in and the window stays at ten', rc == 0 and len(got) == 10,
      'rc=%s ids=%s' % (rc, got))
check('the newest note is the one just written', got[:1] == [601], str(got))
check('and the one pushed out is the OLDEST, not an arbitrary one',
      got == list(range(601, 591, -1)), str(got))

# --- 2. THE SHALLOW CLONE: history cannot see the older notes --------------
# History holds only the last two. Without the archive as a source this writes
# three notes and calls it a success.
d = build_repo([599, 600], list(range(591, 601)), 601)
rc, out = run(d)
got = ids(archive(d))
check('a shallow history still produces ten notes', rc == 0 and len(got) == 10,
      'rc=%s ids=%s -- %s' % (rc, got, out.strip().splitlines()[-1:]))
check('...and they are the right ten', got == list(range(601, 591, -1)),
      str(got))
check('...with the bodies taken from the published archive, not invented',
      '\n'.join(archive(d).splitlines()).count('body 595') == 1,
      'note 595 came from somewhere unexpected')

# --- 3. the hole check must fire, and it needs an INJECTED fault ---------
# There is no fixture for this any more, and that is the finding rather than a
# gap: once the archive is a source, every id it holds is a candidate, so an id
# can only leave by having ten newer ones ahead of it -- which puts it below
# the window, not inside it. The guard is a tripwire for a route that does not
# currently exist. Testing a tripwire means injecting the fault.
#
# (The first attempt built a repo with no commits at all. `git log` fails on an
# empty repo, the tool exited non-zero, and the check passed -- for a reason
# that had nothing to do with the guard. Which is why it now asserts the
# MESSAGE, not just the exit code.)
d = build_repo(list(range(590, 601)), list(range(591, 601)), 601)
spec = importlib.util.spec_from_file_location('_ru3', TOOL)
holed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(holed)
holed.ROOT = __import__('pathlib').Path(d)
holed.OUT = holed.ROOT / REL / 'recent_updates.txt'
real_collect = holed.collect
holed.collect = lambda: [(i, note(i).strip('\n'))
                         for i in real_collect() and
                         [601, 600, 599, 598, 597, 595, 594, 593, 592, 591]]
before_bytes = archive(d)
try:
    holed.main()
    raised = ''
except SystemExit as e:
    raised = str(e)
check('SABOTAGE: a published note missing from INSIDE the window stops the '
      'build', 'INSIDE the window' in raised and '596' in raised,
      'raised %r' % raised[:200])
check('...and it refuses BEFORE writing, so the archive on disk survives',
      archive(d) == before_bytes,
      'a guard that writes first guards nothing')

# --- 4. and it does not cry wolf on the ordinary slide ---------------------
d = build_repo(list(range(590, 601)), list(range(591, 601)), 601)
rc, out = run(d)
check('SELF-CHECK: pushing 591 off the bottom is NOT reported as a hole',
      rc == 0 and 'INSIDE the window' not in out,
      'the guard fires on the normal case, which would block every release')

# --- 5. it does not walk the whole history to find ten --------------------
d = build_repo(list(range(400, 601)), list(range(591, 601)), 601)
spec = importlib.util.spec_from_file_location('_ru', TOOL)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
calls = []
real_git = mod._git
mod.ROOT = __import__('pathlib').Path(d)
mod.OUT = mod.ROOT / REL / 'recent_updates.txt'


def counting_git(*args):
    calls.append(args)
    return subprocess.run(('git',) + args, cwd=d, capture_output=True,
                          check=True).stdout


mod._git = counting_git
mod.collect()
shows = [c for c in calls if c[0] == 'show']
check('it stops reading history once it has ten, not after 200 commits',
      len(shows) < 15, 'ran %d `git show` calls' % len(shows))

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
