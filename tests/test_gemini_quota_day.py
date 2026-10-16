"""The free Gemini quota resets at midnight Pacific time, not UTC midnight.

Measured in a QA run: counting from UTC midnight showed a fresh daily budget
at 03:00 in Israel while Google still counted the night's requests against
the previous day, until about 10:00.
"""

import datetime as dt
import importlib.util
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
_spec = importlib.util.spec_from_file_location('gq_day', LIB / 'gemini_quota.py')
gq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gq)


class QuotaDayTests(unittest.TestCase):
    def test_the_day_turns_at_pacific_midnight(self):
        for utc, day in ((dt.datetime(2026, 10, 16, 0, 5), '2026-10-15'),   # 03:05 in Israel
                         (dt.datetime(2026, 10, 16, 6, 59), '2026-10-15'),
                         (dt.datetime(2026, 10, 16, 7, 0), '2026-10-16'),   # PDT: 07:00 UTC
                         (dt.datetime(2026, 12, 1, 7, 30), '2026-11-30'),
                         (dt.datetime(2026, 12, 1, 8, 0), '2026-12-01')):   # PST: 08:00 UTC
            self.assertEqual(gq._today_utc(utc), day, utc)

    def test_daylight_saving_edges(self):
        # 2026: starts Sunday 8 March 10:00 UTC, ends Sunday 1 November 09:00 UTC.
        self.assertEqual(gq._pacific_offset(dt.datetime(2026, 3, 8, 9, 59)), dt.timedelta(hours=-8))
        self.assertEqual(gq._pacific_offset(dt.datetime(2026, 3, 8, 10, 0)), dt.timedelta(hours=-7))
        self.assertEqual(gq._pacific_offset(dt.datetime(2026, 11, 1, 8, 59)), dt.timedelta(hours=-7))
        self.assertEqual(gq._pacific_offset(dt.datetime(2026, 11, 1, 9, 0)), dt.timedelta(hours=-8))

    def test_the_user_is_told_the_real_reset_time(self):
        text = (LIB / 'gemini_quota.py').read_text(encoding='utf-8')
        self.assertNotIn('חצות UTC', text)
        self.assertIn('10:00', text)


if __name__ == '__main__':
    unittest.main()
