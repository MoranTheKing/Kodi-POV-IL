"""Translation requests carry numbered entries without timecodes; the reply's
timecodes always come from the source (srt_wire.py)."""
import importlib.util
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
_spec = importlib.util.spec_from_file_location('srt_wire_t', LIB / 'srt_wire.py')
w = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w)

SRC = ['17\n00:01:02,345 --> 00:01:04,567\nHello there.',
       '18\n00:01:05,000 --> 00:01:06,500\n- Who?\n- Me.',
       '19\n00:01:07,000 --> 00:01:08,000\n18']


class Wire(unittest.TestCase):
    def test_to_wire_drops_only_the_timecode(self):
        self.assertEqual(w.to_wire(SRC), ['17\nHello there.', '18\n- Who?\n- Me.', '19\n18'])

    def test_round_trip(self):
        reply = '17\nשלום לך.\n\n18\n- מי?\n- אני.\n\n19\n18'
        self.assertEqual(w.from_wire(SRC, reply),
                         '17\n00:01:02,345 --> 00:01:04,567\nשלום לך.\n\n'
                         '18\n00:01:05,000 --> 00:01:06,500\n- מי?\n- אני.\n\n'
                         '19\n00:01:07,000 --> 00:01:08,000\n18')

    def test_a_cue_whose_text_is_the_next_number(self):
        src = ['5\n00:00:01,000 --> 00:00:02,000\n6', '6\n00:00:03,000 --> 00:00:04,000\nSix.']
        out = w.from_wire(src, '5\n6\n\n6\nשש.')
        self.assertEqual(out, '5\n00:00:01,000 --> 00:00:02,000\n6\n\n'
                              '6\n00:00:03,000 --> 00:00:04,000\nשש.')

    def test_welded_entries_are_split(self):
        out = w.from_wire(SRC[:2], '17\nשלום.\n18\n- מי?\n- אני.')
        self.assertEqual(out.split('\n\n')[1], '18\n00:01:05,000 --> 00:01:06,500\n- מי?\n- אני.')

    def test_echoed_timecodes_prefaces_and_fences_are_dropped(self):
        reply = ('```\nHere is the translation:\n17\n00:09:09,000 --> 00:09:10,000\nשלום.\n\n'
                 '18\n- מי?\n- אני.\n```')
        out = w.from_wire(SRC[:2], reply)
        self.assertEqual(out, '17\n00:01:02,345 --> 00:01:04,567\nשלום.\n\n'
                              '18\n00:01:05,000 --> 00:01:06,500\n- מי?\n- אני.')

    def test_unrequested_numbers_and_empty_entries(self):
        out = w.from_wire(SRC[:2], '17\n\n99\nזבל\n\n18\nמי?')
        # 17 came back empty: left out (the integrity gate fills it from the source);
        # 99 was never asked for: it is text of nothing and dropped.
        self.assertEqual(out, '18\n00:01:05,000 --> 00:01:06,500\nמי?')

    def test_out_of_order_entries_after_a_blank_line(self):
        out = w.from_wire(SRC[:2], '18\nמי?\n\n17\nשלום.')
        self.assertEqual([b.split('\n')[0] for b in out.split('\n\n')], ['18', '17'])

    def test_a_full_srt_reply_is_kept(self):
        reply = '17\n00:01:02,345 --> 00:01:04,567\nשלום.'
        self.assertEqual(w.from_wire(SRC[:1], reply), reply)


if __name__ == '__main__':
    unittest.main()
