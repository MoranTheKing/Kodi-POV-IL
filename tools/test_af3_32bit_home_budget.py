"""Behavioural checks for Arctic Fuse 3's architecture-aware home plan."""

import importlib.util
import json
import os


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
MODULE = os.path.join(
    ROOT, 'addons', 'service.subtitles.kodipovilai', 'resources', 'lib',
    'af3_home_patcher.py')

spec = importlib.util.spec_from_file_location('af3_32bit_budget_test', MODULE)
af3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(af3)

FAIL = []


def check(label, condition, detail=''):
    print('{0:4} {1}{2}'.format(
        'ok' if condition else 'FAIL', label,
        (' -- ' + detail) if detail and not condition else ''))
    if not condition:
        FAIL.append(label)


compact, retired = af3._home_widgets_for_runtime(True)
full, retired64 = af3._home_widgets_for_runtime(False)
compact_paths = [row.get('path', '') for row in compact]

print('=== architecture plan ===')
check('64-bit keeps the complete AF3 home',
      full == af3.HOME_WIDGETS and not retired64)
check('32-bit shrinks 25 startup rows to nine',
      len(af3.HOME_WIDGETS) == 25 and len(compact) == 9,
      '{0}->{1}'.format(len(af3.HOME_WIDGETS), len(compact)))
check('32-bit keeps only three live POV catalogue rows',
      sum(('mode=build_movie_list' in p
           or 'mode=build_tvshow_list' in p
           or 'mode=build_next_episode' in p)
          for p in compact_paths) == 3)
check('personal movie/show and network choices stay on the home',
      all(any(needle in p for p in compact_paths) for needle in (
          'FENtastic%20-%20%D7%A1%D7%A8%D7%98%D7%99%D7%9D%20-%20%D7%90%D7%99%D7%96%D7%95%D7%A8%20%D7%90%D7%99%D7%A9%D7%99',
          'FENtastic%20-%20%D7%A1%D7%93%D7%A8%D7%95%D7%AA%20-%20%D7%90%D7%99%D7%96%D7%95%D7%A8%20%D7%90%D7%99%D7%A9%D7%99',
          '%D7%A1%D7%93%D7%A8%D7%95%D7%AA%20-%20%D7%9C%D7%A4%D7%99%20%D7%A8%D7%A9%D7%AA%D7%95%D7%AA')))
check('all nine individual network catalogues are retired on 32-bit',
      all(af3._item_key(row) in retired
          for row in af3.STREAMING_NETWORK_WIDGETS))
check('latest movies is served by spotlight instead of a duplicate row',
      not any('tmdb_movies_latest_releases' in p for p in compact_paths)
      and 'widget_limit=7' in af3._DEFAULT_SPOTLIGHT)


print('\n=== one-time three-way migration ===')
node_path = af3.AF3_NODES + 'skinvariables-shortcut-homewidgets.json'
base_path = (af3.POV_BASELINE_DIR
             + 'skinvariables-shortcut-homewidgets.json')
custom = {
    'label': 'user row',
    'path': 'plugin://example.user/?mode=mine',
    'target': 'videos',
}
legacy_defaults = [
    {'label': 'legacy build row', 'path': path, 'target': 'videos'}
    for path in af3._LEGACY_DIRECT_TMDB_WIDGET_PATHS
]
memory = {
    node_path: af3._json(
        list(af3.HOME_WIDGETS) + legacy_defaults + [custom]),
    base_path: af3._json(af3.HOME_WIDGETS),
}

af3._exists = lambda path: path in memory
af3._read = lambda path: memory[path]
af3._write = lambda path, data: memory.__setitem__(path, data)
af3._mkdir = lambda _path: None


def write_if_changed(filename, data):
    path = af3.AF3_NODES + filename
    new = af3._json(data)
    changed = memory.get(path) != new
    memory[path] = new
    return changed


af3._write_if_changed = write_if_changed
changed = af3._merge_widget_nodes(
    'skinvariables-shortcut-homewidgets.json', compact,
    retired_keys=retired,
    forced_retired_keys=tuple(
        af3._item_key(row) for row in legacy_defaults))
migrated = json.loads(memory[node_path])
keys = [af3._item_key(row) for row in migrated]
check('migration changes an existing full 32-bit profile', changed)
check('migration removes only known build rows and keeps the user row',
      len(migrated) == 10 and custom in migrated, str(len(migrated)))
check('migration installs every compact row exactly once',
      all(keys.count(af3._item_key(row)) == 1 for row in compact))
check('migration removes every retired baseline row',
      not any(key in retired for key in keys))
check('migration also removes exact pre-baseline legacy defaults',
      not any(af3._item_key(row) in keys for row in legacy_defaults))

before = dict(memory)
changed_again = af3._merge_widget_nodes(
    'skinvariables-shortcut-homewidgets.json', compact,
    retired_keys=retired,
    forced_retired_keys=tuple(
        af3._item_key(row) for row in legacy_defaults))
check('the migration is byte-idempotent',
      not changed_again and memory == before)

# Once the baseline is compact, manually adding a historical path is a user
# action, not a build row to delete again.
user_historical = dict(af3.HOME_WIDGETS[0])
current = json.loads(memory[node_path]) + [user_historical]
memory[node_path] = af3._json(current)
af3._merge_widget_nodes(
    'skinvariables-shortcut-homewidgets.json', compact,
    retired_keys=retired,
    forced_retired_keys=tuple(
        af3._item_key(row) for row in legacy_defaults))
after_user_add = json.loads(memory[node_path])
check('a historical row explicitly re-added by the user survives',
      user_historical in after_user_add)


print('\n=== spotlight ownership ===')


class FakeXbmc:
    def __init__(self, value):
        self.value = value
        self.commands = []

    def getSkinDir(self):
        return af3.AF3_SKIN_ID

    def getInfoLabel(self, _label):
        return self.value

    def executebuiltin(self, command):
        self.commands.append(command)


real_maxsize = af3.sys.maxsize
try:
    af3.sys.maxsize = 2 ** 31 - 1
    old = FakeXbmc(af3._LEGACY_DEFAULT_SPOTLIGHT)
    af3.xbmc = old
    check('the exact legacy build spotlight receives the seven-item budget',
          af3._migrate_32bit_default_spotlight()
          and any('widget_limit=7' in cmd for cmd in old.commands))
    custom_spotlight = FakeXbmc('plugin://user/custom')
    af3.xbmc = custom_spotlight
    check('a user-customized spotlight is never changed',
          not af3._migrate_32bit_default_spotlight()
          and not custom_spotlight.commands)
finally:
    af3.sys.maxsize = real_maxsize


if FAIL:
    print('\nFAILED: ' + ', '.join(FAIL))
    raise SystemExit(1)
print('\nAll AF3 32-bit home-budget checks passed.')
