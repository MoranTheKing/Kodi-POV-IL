"""temperature / top_p go only to the models that still accept them.

GOOGLE'S NOTICE, verbatim from the Gemini API docs:

    temperature, top_p, and top_k are deprecated and ignored. In future model
    generations, supplying these parameters returns an HTTP 400 error. Remove
    these parameters from all requests.

"Ignored" today, a hard 400 tomorrow. A 400 on a translation chunk is not a
worse translation, it is no translation: gemini.generate() raises GeminiError
and the chunk is lost. So the parameters are gated per MODEL rather than
dropped outright, because on 2.5 and 3.1 they still do real work and the
build's 1.0 / 0.95 defaults were measured there.

WHAT THIS PINS.
  1. The rule itself: 2.5 and 3.1 keep the parameters, 3.5 and 3.7 do not, and
     a model id with no readable generation does not either.
  2. Every request builder in gemini.py obeys it -- checked by building real
     payloads through a stubbed `requests`, not by reading the source. That
     covers subsync.py's audio call for free, which passes a hardcoded
     temperature=0.0 and is the site an if-per-call-site would have missed.
  3. settings.xml's visibility whitelist and the code agree EXACTLY, for every
     model in the picker. This is the drift that would otherwise happen
     silently: a model added to the picker and not to the dependency, or the
     reverse, and nobody notices until a user asks why a slider does nothing.
  4. The parameters are still accepted and stored, so switching back to 2.5
     restores the user's own numbers rather than a default.

The sabotage section mutates the module and requires each mutant to be caught.

Run: python3 tools/test_gemini_sampling_params.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')
MODULE = os.path.join(LIB, 'gemini.py')
SETTINGS = os.path.join(ADDON, 'resources', 'settings.xml')

FAIL = []
_TMP = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


class _Resp(object):
    status_code = 200

    def __init__(self, sent):
        self._sent = sent

    def json(self):
        return {'candidates': [{'content': {'parts': [{'text': 'ok'}]}}]}

    @property
    def text(self):
        return ''


def load(src=None):
    """gemini.py with `requests` stubbed so post() records the payload."""
    for n in list(sys.modules):
        if n.startswith(('requests', 'gsp_mod')):
            sys.modules.pop(n, None)
    sent = {}
    rq = types.ModuleType('requests')

    def _post(url, data=None, headers=None, timeout=None):
        sent['url'] = url
        sent['payload'] = json.loads(data)
        return _Resp(sent)

    rq.post = _post
    rq.get = _post
    rq.RequestException = Exception
    sys.modules['requests'] = rq

    path = MODULE
    if src is not None:
        d = tempfile.mkdtemp(prefix='gsp_')
        _TMP.append(d)
        path = os.path.join(d, 'gemini.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(src)
    spec = importlib.util.spec_from_file_location('gsp_mod', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._sent = sent
    return mod


def config_for(mod, model):
    """generationConfig of a real generate() request for `model`."""
    mod.generate(api_key='k', model=model, prompt='p',
                 temperature=0.7, top_p=0.95)
    return mod._sent['payload']['generationConfig']


def media_config_for(mod, model):
    mod.generate_media(api_key='k', model=model, prompt='p',
                       media_bytes=b'\x00', mime='audio/aac',
                       temperature=0.0)
    return mod._sent['payload']['generationConfig']


# -------------------------------------------------------------- 1. the rule
mod = load()
KEEPS = ('gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-3.1-flash',
         'gemini-2.5-flash-lite-preview-06-17', 'gemini-1.5-pro',
         'gemini-2.0-flash')
DROPS = ('gemini-3.5-flash-lite', 'gemini-3.7-flash', 'gemini-4.0-pro',
         'gemini-10.0-flash', 'gemini-3.5-flash')
UNREADABLE = ('gemini-flash-latest', 'gemini-exp-1206', '', None,
              'some-other-model')

for m in KEEPS:
    check('rule: %s keeps the parameters' % m,
          mod.sampling_params_supported(m) is True)
for m in DROPS:
    check('rule: %s drops them' % m,
          mod.sampling_params_supported(m) is False)
for m in UNREADABLE:
    check('rule: %r has no readable generation, so it drops them' % (m,),
          mod.sampling_params_supported(m) is False)

check('rule: the cutoff is 3.5, not "anything 3.x"',
      mod.sampling_params_supported('gemini-3.1-flash') is True
      and mod.sampling_params_supported('gemini-3.5-flash') is False)
check('rule: a dated preview id resolves to its own generation',
      mod.model_generation('gemini-2.5-flash-lite-preview-06-17') == (2, 5))

# ------------------------------------------------- 2. the requests themselves
for m in KEEPS:
    cfg = config_for(mod, m)
    check('request: %s carries temperature and topP' % m,
          cfg.get('temperature') == 0.7 and cfg.get('topP') == 0.95,
          repr(cfg))
for m in DROPS:
    cfg = config_for(mod, m)
    check('request: %s carries neither' % m,
          'temperature' not in cfg and 'topP' not in cfg, repr(cfg))
    check('request: %s still carries maxOutputTokens' % m,
          'maxOutputTokens' in cfg, repr(cfg))

# top_k has never been sent; if that ever changes it must be gated too.
check('request: top_k is never sent, on any model',
      all('topK' not in config_for(mod, m) for m in KEEPS + DROPS))

# The media builder (subsync's audio call) obeys the same rule.
check('request: generate_media sends temperature on 2.5',
      media_config_for(mod, 'gemini-2.5-flash').get('temperature') == 0.0)
check('request: generate_media omits it on 3.5',
      'temperature' not in media_config_for(mod, 'gemini-3.5-flash-lite'))
check('request: generate_media keeps maxOutputTokens either way',
      'maxOutputTokens' in media_config_for(mod, 'gemini-3.5-flash-lite'))

# ------------------------------------------- 3. settings.xml agrees with it
tree = ET.parse(SETTINGS)
root = tree.getroot()

picker = None
for setting in root.iter('setting'):
    if setting.get('id') == 'model':
        picker = setting
        break
check('settings: the model picker is still there', picker is not None)

picker_models = []
if picker is not None:
    for opt in picker.iter('option'):
        picker_models.append((opt.text or '').strip())
check('settings: the picker lists models', len(picker_models) >= 2,
      repr(picker_models))

GATED = ('temperature', 'top_p')
for sid in GATED:
    node = None
    for setting in root.iter('setting'):
        if setting.get('id') == sid:
            node = setting
            break
    if node is None:
        check('settings: %s exists' % sid, False)
        continue
    shown_for = []
    for dep in node.iter('dependency'):
        if dep.get('type') != 'visible':
            continue
        for cond in dep.iter('condition'):
            if cond.get('setting') == 'model' and cond.get('operator') == 'is':
                shown_for.append((cond.text or '').strip())
    check('settings: %s has a visibility whitelist' % sid, bool(shown_for))
    expected = [m for m in picker_models if mod.sampling_params_supported(m)]
    check('settings: %s is shown for exactly the models that honour it' % sid,
          sorted(shown_for) == sorted(expected),
          'xml says {0}, the code says {1}'.format(sorted(shown_for),
                                                   sorted(expected)))
    check('settings: %s is hidden for every newer model' % sid,
          not [m for m in picker_models
               if m in shown_for and not mod.sampling_params_supported(m)])

# The default model is one of the newer ones, so out of the box neither
# slider shows and neither parameter is sent. If that ever stops being true
# the release note claiming it has to change too.
default_model = ''
if picker is not None:
    d = picker.find('default')
    if d is not None:
        default_model = (d.text or '').strip()
check('settings: the default model is one that drops the parameters',
      default_model and not mod.sampling_params_supported(default_model),
      'default is {0!r}'.format(default_model))

# ------------------------------------- 4. the settings themselves survive
check('settings: temperature is still a stored setting',
      any(s.get('id') == 'temperature' for s in root.iter('setting')))
check('settings: top_p is still a stored setting',
      any(s.get('id') == 'top_p' for s in root.iter('setting')))
check('signature: generate() still accepts both, so callers need no change',
      'temperature' in mod.generate.__code__.co_varnames
      and 'top_p' in mod.generate.__code__.co_varnames)


# ------------------------------------------------------------- sabotage
SRC = open(MODULE, encoding='utf-8').read()
MUTANTS = (
    ('M1 gate always says yes',
     '    generation = model_generation(model)\n'
     '    if generation is None:\n'
     '        return False\n'
     '    return generation < _SAMPLING_RETIRED_FROM',
     '    return True'),
    ('M2 gate always says no',
     '    generation = model_generation(model)\n'
     '    if generation is None:\n'
     '        return False\n'
     '    return generation < _SAMPLING_RETIRED_FROM',
     '    return False'),
    ('M3 cutoff moved to 3.0, so 3.1 loses its parameters',
     '_SAMPLING_RETIRED_FROM = (3, 5)',
     '_SAMPLING_RETIRED_FROM = (3, 0)'),
    ('M4 cutoff moved to 4.0, so 3.5 keeps sending them',
     '_SAMPLING_RETIRED_FROM = (3, 5)',
     '_SAMPLING_RETIRED_FROM = (4, 0)'),
    ('M5 an unreadable id defaults to sending them',
     '    generation = model_generation(model)\n'
     '    if generation is None:\n'
     '        return False\n',
     '    generation = model_generation(model)\n'
     '    if generation is None:\n'
     '        return True\n'),
    ('M6 the text builder ignores the gate',
     "    if sampling_params_supported(model):\n"
     "        generation_config['temperature'] = temperature\n"
     "        if top_p is not None:\n"
     "            generation_config['topP'] = top_p",
     "    generation_config['temperature'] = temperature\n"
     "    if top_p is not None:\n"
     "        generation_config['topP'] = top_p"),
    ('M7 the media builder ignores the gate',
     "    media_config = {'maxOutputTokens': max_output_tokens}\n"
     "    if sampling_params_supported(model):\n"
     "        media_config['temperature'] = temperature",
     "    media_config = {'maxOutputTokens': max_output_tokens,\n"
     "                    'temperature': temperature}"),
    ('M8 comparison is on the major only, so 3.7 keeps them',
     '    return generation < _SAMPLING_RETIRED_FROM',
     '    return generation[0] < _SAMPLING_RETIRED_FROM[0]'),
)
print('\n-- sabotage --')
for label, old, new in MUTANTS:
    if SRC.count(old) != 1:
        check(label, False, 'mutation target not found exactly once '
                            '({0})'.format(SRC.count(old)))
        continue
    m = load(src=SRC.replace(old, new, 1))
    caught = False
    try:
        for name in KEEPS:
            cfg = config_for(m, name)
            if cfg.get('temperature') != 0.7 or cfg.get('topP') != 0.95:
                caught = True
        for name in DROPS:
            cfg = config_for(m, name)
            if 'temperature' in cfg or 'topP' in cfg:
                caught = True
        for name in UNREADABLE:
            if m.sampling_params_supported(name):
                caught = True
        if 'temperature' in media_config_for(m, 'gemini-3.5-flash-lite'):
            caught = True
        if 'temperature' not in media_config_for(m, 'gemini-2.5-flash'):
            caught = True
    except Exception:
        caught = True
    check(label + ' -> caught', caught,
          'mutant SURVIVED -- the checks above do not test this')

for d in _TMP:
    shutil.rmtree(d, ignore_errors=True)

print('\n%d check(s) failed' % len(FAIL))
sys.exit(1 if FAIL else 0)
