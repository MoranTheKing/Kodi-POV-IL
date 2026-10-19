"""The blind gender classifier after a referenced translation (NG Method B).

Only cues whose reference marks a role the Hebrew readers cannot read are
asked about; a label that contradicts the reference becomes a repair target;
a malformed or short reply, or any failure, adds nothing.
"""
import ast
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load(name):
    spec = importlib.util.spec_from_file_location('gc_' + name, LIB / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gg = _load('gender_guard')
with patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
        log=lambda *a, **k: None)}):
    ag = _load('arabic_gender')

TREE = ast.parse((LIB / 'translate.py').read_text(encoding='utf-8'))


def block(n, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,900\n%s' % (n, n, n, text)


def classifier(reply, logs=None):
    """translate.py's own _classifier_conflicts, run with a fake model."""
    sent = []

    def generate(**kw):
        sent.append(kw['prompt'])
        if isinstance(reply, Exception):
            raise reply
        return reply(kw['prompt']) if callable(reply) else reply

    class Abort(Exception):
        pass
    ns = dict(arabic_gender=ag, gender_guard=gg, gemini=types.SimpleNamespace(REQUEST_TIMEOUT=60),
              kodi_utils=types.SimpleNamespace(log=lambda m, **k: (logs or []).append(m)),
              _repair_generate=lambda **kw: generate(**kw), _gemini_rate_gate=lambda x: None,
              _rpm_interval=0, api_key='k', model='m', max_output_tokens=1024, top_p=1.0,
              thinking_budget=None, thinking_level=None, gemini_timeout=None,
              _CLASSIFIER_MAX_LINES=200, _AbortTranslation=Abort)
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == '_classifier_conflicts':
            node.col_offset = 0
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<x>', 'exec'), ns)
    return ns['_classifier_conflicts'], sent


class Parse(unittest.TestCase):
    def test_labels_for_every_asked_line(self):
        reply = '```json\n{"lines":[{"i":3,"speaker":"F","addressee":"NA"},{"i":"7","speaker":"na","addressee":"M"}]}\n```'
        self.assertEqual(gg.parse_classifier(reply, [3, 7]),
                         {3: {'speaker': 'F', 'addressee': None}, 7: {'speaker': None, 'addressee': 'M'}})

    def test_short_or_malformed_replies_abstain(self):
        self.assertIsNone(gg.parse_classifier('{"lines":[{"i":3,"speaker":"F"}]}', [3, 7]))
        self.assertIsNone(gg.parse_classifier('no json here', [3]))
        self.assertIsNone(gg.parse_classifier('{"lines": 5}', [3]))
        # an unasked index is ignored, a repeat keeps the first label
        self.assertEqual(gg.parse_classifier(
            '{"lines":[{"i":9,"speaker":"M"},{"i":3,"speaker":"M"},{"i":3,"speaker":"F"}]}', [3]),
            {3: {'speaker': 'M', 'addressee': None}})

    def test_prompt_sends_only_hebrew_lines_never_the_reference(self):
        p = gg.classifier_prompt([(4, '‫שלום,\nמה נשמע?')])
        self.assertTrue(p.startswith(gg.CLASSIFIER_PROMPT))
        self.assertTrue(p.endswith('4\tשלום, / מה נשמע?'))
        self.assertEqual(gg.classifier_prompt([]), '')


class Select(unittest.TestCase):
    # Entry 1: the reference marks a female addressee; the Hebrew uses a verb
    # outside the readers' lexicon (התחתנת) -- unread, so it is asked about.
    # Entry 2: the reader already reads it -- never asked.
    # Entry 3: no reference -- never asked.
    BLOCKS = [block(1, 'מתי התחתנת, גברת?'), block(2, 'אתה צודק.'), block(3, 'מתי התחתנת?')]
    REFS = {1: 'את התחתנת? את צודקת.', 2: 'את צודקת.'}

    def test_only_unread_marked_roles_are_asked(self):
        fn, sent = classifier('{"lines":[{"i":1,"speaker":"NA","addressee":"M"}]}')
        out = fn(self.BLOCKS, self.REFS, 'he', {2: [('addressee', 'F')]})
        self.assertEqual(len(sent), 1)
        self.assertIn('1\tמתי התחתנת, גברת?', sent[0])
        self.assertNotIn('אתה צודק', sent[0])
        self.assertNotIn('את צודקת', sent[0])          # the reference never goes out
        self.assertEqual(out, {1: [('addressee', 'F')]})

    def test_an_agreeing_label_adds_nothing(self):
        fn, _ = classifier('{"lines":[{"i":1,"speaker":"NA","addressee":"F"}]}')
        self.assertEqual(fn(self.BLOCKS, self.REFS, 'he', {}), {})

    def test_failures_add_nothing(self):
        for reply in ('garbage', '{"lines":[]}', RuntimeError('boom')):
            fn, _ = classifier(reply)
            self.assertEqual(fn(self.BLOCKS, self.REFS, 'he', {}), {})

    def test_a_cue_without_hebrew_is_not_asked(self):
        # a cue kept as English source, or one that is only direction marks
        fn, sent = classifier('{"lines":[]}')
        blocks = [block(1, "You're tired, sir?"), block(2, '‫')]
        self.assertEqual(fn(blocks, {1: 'את עייפה?', 2: 'את עייפה?'}, 'he', {}), {})
        self.assertEqual(sent, [])

    def test_nothing_to_ask_sends_nothing(self):
        fn, sent = classifier('{"lines":[]}')
        self.assertEqual(fn([block(2, 'אתה צודק.')], {2: 'את צודקת.'}, 'he', {}), {})
        self.assertEqual(sent, [])

    def test_no_speaker_question_on_a_two_speaker_cue(self):
        fn, sent = classifier('{"lines":[]}')
        fn([block(1, '- התחתנתי.\n- באמת?')], {1: '- אני נשואה.\n- באמת?'}, 'he', {})
        self.assertEqual(sent, [])

    def test_another_reference_language(self):
        fn, sent = classifier(lambda p: json.dumps({'lines': [
            {'i': 1, 'speaker': 'NA', 'addressee': 'M'}]}))
        out = fn([block(1, 'מתי התחתנת?')], {1: 'tú estás casada'}, 'es', {})
        self.assertEqual(out, {1: [('addressee', 'F')]})


if __name__ == '__main__':
    unittest.main()
