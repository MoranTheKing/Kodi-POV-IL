"""Prove the widget budget reduces hidden work and cannot leak into lists.

This is intentionally behavioural. Merely finding ``widget_limit`` in a file
would stay green if the bounded worker were disconnected. The probe executes
the patched call site, including adaptive backfill, and the mutation check
disconnects the wrapper and requires that the same assertion would then fail.
"""

import importlib.util
import io
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
PATCHER = os.path.join(LIB, 'pov_widget_budget_patcher.py')
NATIVE = os.path.join(LIB, 'pov_native_menus')
AF3 = os.path.join(LIB, 'af3_home_patcher.py')
SERVICE = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                       'service.py')

FAIL = []


def check(label, condition, detail=''):
    print('{0:4} {1}{2}'.format(
        'ok' if condition else 'FAIL', label,
        (' -- ' + detail) if detail and not condition else ''))
    if not condition:
        FAIL.append(label)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patcher = load('widget_budget_test', PATCHER)
menus_patcher = load('widget_budget_menus_test',
                     os.path.join(LIB, 'pov_menus_patcher.py'))


print('=== current POV menu shapes ===')
for filename in ('movies.py', 'tvshows.py'):
    with tempfile.TemporaryDirectory(prefix='pov-budget-menu-') as folder:
        target = os.path.join(folder, filename)
        shutil.copy2(os.path.join(NATIVE, filename), target)
        first = patcher._patch_pov_file(target)
        once = open(target, 'rb').read()
        second = patcher._patch_pov_file(target)
        twice = open(target, 'rb').read()
        text = once.decode('utf-8')
        check(filename + ' patches', first == 'patched', first)
        check(filename + ' compiles', bool(compile(text, target, 'exec')))
        check(filename + ' has one live block',
              text.count('AI_SUBS_POV_WIDGET_BUDGET_v1') == 1)
        check(filename + ' is byte-idempotent',
              second == 'unchanged' and once == twice, second)

        # Startup currently runs this budget before pov_menus_patcher.  The
        # latter must preserve the block while injecting its personal lists.
        suffix = 'movies' if filename == 'movies.py' else 'tvshows'
        tmdb_type = 'movie' if filename == 'movies.py' else 'tv'
        trakt_type = 'movies' if filename == 'movies.py' else 'shows'
        menus_patcher._patch_one(target, filename, tmdb_type, trakt_type, suffix)
        after_menu = io.open(target, encoding='utf-8').read()
        check(filename + ' keeps its budget after the menu patcher',
              after_menu.count('AI_SUBS_POV_WIDGET_BUDGET_v1') == 1)


PROBE = '''class Probe:
\tdef __init__(self, is_widget, value, hide_watched=False, dropped=()):
\t\tself.is_widget = is_widget
\t\tself.widget_hide_watched = hide_watched
\t\tself.params = {} if value is None else {'widget_limit': value}
\t\tself.list = list(range(20))
\t\tself.dropped = set(dropped)
\t\tself.items = []
\t\tself.append = self.items.append
\tdef worker(self):
\t\treturn [item for item in self.list if item not in self.dropped]
\tdef run(self):
\t\t__handle__ = 1
\t\tparams_get = self.params.get
\t\tworker = self.worker
\t\tkodi_utils.add_items(__handle__, worker())
'''


def execute_probe(module, is_widget, value, hide_watched=False, dropped=(),
                  self_worker=False, return_instance=False):
    with tempfile.TemporaryDirectory(prefix='pov-budget-probe-') as folder:
        path = os.path.join(folder, 'probe.py')
        probe = PROBE
        if self_worker:
            probe = probe.replace(
                '\t\tworker = self.worker\n'
                '\t\tkodi_utils.add_items(__handle__, worker())',
                '\t\tkodi_utils.add_items(__handle__, self.worker())')
        with io.open(path, 'w', encoding='utf-8') as handle:
            handle.write(probe)
        status = module._patch_pov_file(path)
        source = io.open(path, encoding='utf-8').read()
        class Recorder:
            items = None

            @classmethod
            def add_items(cls, _handle, items):
                cls.items = list(items)
        namespace = {'kodi_utils': Recorder}
        exec(compile(source, path, 'exec'), namespace)
        instance = namespace['Probe'](
            is_widget, value, hide_watched, dropped)
        instance.run()
        result = (status, Recorder.items)
        if return_instance:
            return result + (instance,)
        return result


print('\n=== behavioural gate ===')
status, items = execute_probe(patcher, True, '7')
check('an explicit widget request starts only seven workers',
      status == 'patched' and items == list(range(7)), str(items))
_status, items, instance = execute_probe(
    patcher, True, '7', self_worker=True, return_instance=True)
check('the TV-style self.worker anchor also starts only seven workers',
      items == list(range(7)), str(items))
check('the TV-style wrapper restores the original method after one run',
      getattr(instance.worker, '__name__', '') == 'worker',
      getattr(instance.worker, '__name__', ''))
_status, items = execute_probe(
    patcher, True, '7', dropped=(1, 2, 5))
check('failed metadata entries are backfilled to a complete seven-item row',
      items == [0, 3, 4, 6, 7, 8, 9], str(items))
for label, is_widget, value in (
        ('normal navigation', False, '7'),
        ('an untagged widget', True, None),
        ('a malformed limit', True, 'twelve'),
        ('a negative limit', True, '-4')):
    _status, full = execute_probe(patcher, is_widget, value)
    check(label + ' remains a complete 20-item page',
          full == list(range(20)), str(full))
_status, full = execute_probe(patcher, True, '7', hide_watched=True)
check('hide-watched widgets keep the full page so POV can backfill the row',
      full == list(range(20)), str(full))

# Prove the preceding check depends on the implementation, not the renderer.
mutant = load('widget_budget_mutant', PATCHER)
real_block = mutant._budget_block
mutant._budget_block = lambda indent, worker, eol='\n': real_block(
    indent, worker, eol=eol).replace(
    'worker = _pov_widget_worker', 'worker = worker')
_status, mutant_items = execute_probe(mutant, True, '7')
check('disconnecting the bounded worker is detected by the behavioural test',
      mutant_items != list(range(7)), str(mutant_items))

service_text = io.open(SERVICE, encoding='utf-8').read()
registration = '_maybe_patch_pov_widget_budget,'
check('startup registers the widget-budget repair exactly once',
      service_text.count(registration) == 1,
      str(service_text.count(registration)))
check('widget budgeting runs before AF3 home regeneration',
      service_text.index(registration)
      < service_text.index('_maybe_patch_af3_home,'))

with tempfile.TemporaryDirectory(prefix='pov-budget-crlf-') as folder:
    path = os.path.join(folder, 'probe.py')
    with open(path, 'wb') as handle:
        handle.write(PROBE.replace('\n', '\r\n').encode('utf-8'))
    before = open(path, 'rb').read()
    status = patcher._patch_pov_file(path)
    after = open(path, 'rb').read()
    check('a CRLF host module patches successfully', status == 'patched', status)
    check('patching preserves CRLF without mixed line endings',
          after.count(b'\r\n') == after.count(b'\n')
          and after.count(b'\n') > before.count(b'\n'))


print('\n=== skin delivery ===')
old_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<includes>
  <include name="Rows">
    <include content="WidgetListBigPoster">
      <param name="content_path" value="plugin://plugin.video.pov/?action=tmdb_movies_popular&amp;mode=build_movie_list"/>
      <param name="list_id" value="1"/>
    </include>
    <include content="WidgetListBigPoster">
      <param name="content_path" value="plugin://plugin.video.other/?mode=build_movie_list"/>
      <param name="limit" value="9"/>
    </include>
  </include>
</includes>
'''
with tempfile.TemporaryDirectory(prefix='pov-budget-xml-') as folder:
    path = os.path.join(folder, 'widgets.xml')
    with io.open(path, 'w', encoding='utf-8') as handle:
        handle.write(old_xml)
    first = patcher._patch_skin_file(path, 12)
    once = io.open(path, encoding='utf-8').read()
    second = patcher._patch_skin_file(path, 12)
    twice = io.open(path, encoding='utf-8').read()
    ET.fromstring(once.encode('utf-8'))
    check('POV media row receives a producer budget',
          'widget_limit=12' in once)
    check('POV media row receives a matching visible limit',
          once.count('name="limit" value="12"') == 1)
    check('another add-on row and its limit stay untouched',
          'plugin.video.other' in once and 'name="limit" value="9"' in once)
    check('skin migration is byte-idempotent',
          first == 'patched' and second == 'unchanged' and once == twice,
          '{0}/{1}'.format(first, second))

with tempfile.TemporaryDirectory(prefix='pov-budget-xml-crlf-') as folder:
    path = os.path.join(folder, 'widgets.xml')
    with open(path, 'wb') as handle:
        handle.write(old_xml.replace('\n', '\r\n').encode('utf-8'))
    status = patcher._patch_skin_file(path, 12)
    after = open(path, 'rb').read()
    check('a CRLF skin file patches successfully', status == 'patched', status)
    check('skin migration preserves CRLF without mixed line endings',
          after.count(b'\r\n') == after.count(b'\n'))


print('\n=== Arctic Fuse 3 delivery ===')
af3 = load('af3_widget_budget_test', AF3)
media = []
for row in af3.HOME_WIDGETS:
    path = row.get('path', '') or ''
    if ('mode=build_movie_list' in path
            or 'mode=build_tvshow_list' in path):
        media.append(row)
check('every AF3 movie/TV row carries the seven-item producer budget',
      bool(media) and all('widget_limit=7' in row['path'] for row in media),
      '{0}/{1}'.format(sum('widget_limit=7' in row['path'] for row in media),
                       len(media)))
old = 'plugin://plugin.video.pov/?action=x&mode=build_movie_list&name=y'
new = old + '&widget_limit=7'
check('AF3 treats the budget as an in-place upgrade, not a duplicate tile',
      af3._item_key({'path': old}) == af3._item_key({'path': new}))
first = ('plugin://plugin.video.pov/?widget_limit=7&action=x'
         '&mode=build_movie_list')
check('AF3 identity also handles the budget as the first query parameter',
      af3._item_key({'path': first})
      == 'plugin://plugin.video.pov/?action=x&mode=build_movie_list')


if FAIL:
    print('\nFAILED: ' + ', '.join(FAIL))
    raise SystemExit(1)
print('\nAll POV widget-budget checks passed.')
