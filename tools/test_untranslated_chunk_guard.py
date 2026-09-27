"""A valid-looking SRT reply left wholly in English must be retried."""
import ast
import importlib.util
import sys
import types
from pathlib import Path

LIB = (Path(__file__).resolve().parents[1] / 'addons'
       / 'service.subtitles.kodipovilai' / 'resources' / 'lib')
sys.path.insert(0, str(LIB))
xbmc = types.ModuleType('xbmc')
xbmc.LOGDEBUG = 0
xbmc.LOGINFO = 1
xbmc.LOGWARNING = 2
xbmc.LOGERROR = 3
sys.modules['xbmc'] = xbmc
for name in ('xbmcaddon', 'xbmcgui', 'xbmcvfs'):
    sys.modules.setdefault(name, types.ModuleType(name))
resources = types.ModuleType('resources')
resources.__path__ = [str(LIB.parent)]
lib_package = types.ModuleType('resources.lib')
lib_package.__path__ = [str(LIB)]
sys.modules['resources'] = resources
sys.modules['resources.lib'] = lib_package
spec = importlib.util.spec_from_file_location(
    'resources.lib.translate', LIB / 'translate.py')
translate = importlib.util.module_from_spec(spec)
sys.modules['resources.lib.translate'] = translate
spec.loader.exec_module(translate)
from resources.lib import srt


def cue(index, dialogue):
    return ('{0}\n00:00:{0:02d},000 --> 00:00:{1:02d},000\n{2}'
            .format(index, index + 1, dialogue))


source = [cue(i, 'Please tell me what happened in the other room tonight.')
          for i in range(1, 6)]
untranslated = [cue(i, 'Can you tell me what happened in that other room?')
                for i in range(1, 6)]
assert len(srt.parse_blocks('\n\n'.join(untranslated))) == len(source)
assert not srt.generated_source_echo_indices(source, untranslated)
assert translate._is_untranslated_chunk_response(source, untranslated)

second_copy = [cue(i, 'אתה יכול לספר לי מה קרה בחדר השני?')
               for i in range(1, 6)]
assert translate._is_untranslated_chunk_response(
    source, untranslated + second_copy)
assert not translate._is_untranslated_chunk_response(
    source, second_copy + untranslated)

translated = list(untranslated)
translated[2] = cue(3, 'אתה יכול לספר לי מה קרה בחדר השני?')
assert not translate._is_untranslated_chunk_response(source, translated)
assert not translate._is_untranslated_chunk_response(source[:2],
                                                     untranslated[:2])

# A helper that is never called cannot repair the observed production path.
tree = ast.parse((LIB / 'translate.py').read_text(encoding='utf-8'))
resolve = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name == 'resolve')
call = next(n for n in resolve.body if isinstance(n, ast.FunctionDef)
            and n.name == '_call_gemini')
assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == '_is_untranslated_chunk_response'
           for n in ast.walk(call))

print('ok - whole English chunk is rejected; mixed and tiny tails abstain')
