"""MoranSubs 0.3.107: Google Translate says why it gave no Hebrew.

A viewer, Nov 2026: "Google Translate fails on everything, whatever I play". The same endpoint answered
from here, through Kodi's own Python too, so the cause was on his side -- and nothing could tell which:
every failure was swallowed into None, the toast was one "failed -- try again" and the log said nothing.
Now google_translate.last_failure() names the kind (blocked / tls / network / reply), the log carries it
and the toast tells the viewer what to check.
"""
import io
import socket
import ssl
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        # A 'resources' package another test left in sys.modules would keep these modules as its
        # attributes after the patch is undone, and a later test's import would then find them there
        # without importing (test_leak_rescue's KeyError in a full run): load into fresh packages.
        for name in [k for k in sys.modules if k == 'resources' or k.startswith('resources.')]:
            del sys.modules[name]
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import google_translate, translate  # noqa: F401
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return translate, mods


def http_error(code, body=b''):
    return urllib.error.HTTPError('https://translate.googleapis.com/x', code, 'x', {}, io.BytesIO(body))


SRT = '1\n00:00:01,000 --> 00:00:02,000\nWhere are you going?\n\n2\n00:00:03,000 --> 00:00:04,000\nHome.\n'


class GoogleWhy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tr, cls.mods = _load()

    def setUp(self):
        patcher = mock.patch.dict(sys.modules, self.mods)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.gt = self.mods['resources.lib.google_translate']
        homes = mock.patch.object(self.gt, '_home', return_value=None)
        homes.start()
        self.addCleanup(homes.stop)
        self.gt._GTX_REFUSED[0] = None
        self.addCleanup(self.gt._GTX_REFUSED.__setitem__, 0, None)

    def kind(self, exc):
        with mock.patch.object(self.gt.urllib.request, 'urlopen', side_effect=exc):
            self.assertIsNone(self.gt.translate_srt(SRT, 'en'))
        return self.gt.last_failure()

    def test_each_cause_has_its_kind(self):
        cases = [
            (http_error(429), 'blocked'),
            (http_error(403), 'blocked'),
            (http_error(503, b'<html>Our systems have detected unusual traffic from your computer'), 'blocked'),
            (http_error(500), 'reply'),
            (urllib.error.URLError(ssl.SSLCertVerificationError(1, 'certificate verify failed')), 'tls'),
            (ssl.SSLError(1, 'wrong version number'), 'tls'),
            (urllib.error.URLError(socket.gaierror(11001, 'getaddrinfo failed')), 'network'),
            (urllib.error.URLError(ConnectionRefusedError(10061, 'refused')), 'network'),
            (socket.timeout('timed out'), 'network'),
            (ValueError('Expecting value'), 'reply'),
        ]
        for exc, kind in cases:
            self.assertEqual(self.kind(exc)[0], kind, repr(exc))
        self.assertIn('429', self.kind(http_error(429))[1])

    def test_an_answer_with_no_text_is_a_reply_failure(self):
        with mock.patch.object(self.gt, '_translate_chunk', return_value=''):
            self.assertIsNone(self.gt.translate_srt(SRT, 'en'))
        self.assertEqual(self.gt.last_failure()[0], 'reply')
        with mock.patch.object(self.gt, '_translate_chunk', return_value=''):
            self.assertIsNone(self.gt.translate_lines(['Home.'], 'en'))
        self.assertEqual(self.gt.last_failure()[0], 'reply')

    def test_a_success_clears_the_last_failure(self):
        self.kind(http_error(429))
        with mock.patch.object(self.gt, '_translate_chunk', side_effect=lambda text, *a, **k: text):
            self.assertTrue(self.gt.translate_srt(SRT, 'en'))
        self.assertIsNone(self.gt.last_failure())
        with mock.patch.object(self.gt.urllib.request, 'urlopen', side_effect=http_error(429)):
            self.assertIsNone(self.gt.translate_lines(['Home.'], 'en'))
        self.assertEqual(self.gt.last_failure()[0], 'blocked')

    def save(self, why, heb=None):
        told, logged = [], []
        with mock.patch.object(self.gt, 'translate_srt', return_value=heb), \
                mock.patch.object(self.gt, 'last_failure', return_value=why), \
                mock.patch.object(self.tr.kodi_utils, 'notify',
                                  side_effect=lambda m, **k: told.append(m) or self.assertEqual(
                                      k.get('title'), self.tr._GOOGLE_FAIL_TITLE)), \
                mock.patch.object(self.tr.kodi_utils, 'log', side_effect=lambda m, **k: logged.append(m)):
            out = self.tr._google_translate_and_save(SRT, 'en', 'unused-path', {})
        self.assertIsNone(out)
        return told, logged

    def test_the_viewer_is_told_what_to_check_and_the_log_says_why(self):
        say = self.tr._GOOGLE_FAIL_SAY
        for kind in ('blocked', 'tls', 'network'):
            told, logged = self.save((kind, 'detail of ' + kind))
            self.assertEqual(told, [say[kind]])
            self.assertTrue(any(kind in m and 'detail of ' + kind in m for m in logged), logged)
        for why in (('reply', 'HTTP 500'), None):
            told, logged = self.save(why)
            self.assertEqual(told, [say['']])
            self.assertTrue(any(m.startswith('google translate failed') for m in logged), logged)
        self.assertIn('VPN', say['network'])
        self.assertIn('שעון', say['tls'])
        # a viewer who chose Google is not steered elsewhere (the owner, 21 Nov 2026)
        self.assertNotIn('AI', say['blocked'])

    def web(self, gtx, t_answer):
        """urlopen: gtx (translate_a/single) raises `gtx` or answers; translate_a/t answers `t_answer`
        (or raises it); a list of either is used up one call at a time."""
        asked = []

        class Reply(object):
            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data

        def answer(spec):
            if isinstance(spec, list):
                spec = spec.pop(0)
            return spec

        def urlopen(req, timeout=None):
            which = 't' if '/translate_a/t?' in req.full_url else 'gtx'
            asked.append(which)
            spec = answer(gtx) if which == 'gtx' else answer(t_answer)
            if isinstance(spec, Exception):
                raise spec
            if which == 'gtx':
                return Reply(b'[[["\\u05e9\\u05dc\\u05d5\\u05dd","x"]]]')
            return Reply(spec)
        return asked, mock.patch.object(self.gt.urllib.request, 'urlopen', side_effect=urlopen)

    T_OK = b'[["\\u05e9\\u05dc\\u05d5\\u05dd","en"]]'

    def test_a_refused_gtx_is_answered_by_the_second_address(self):
        asked, web = self.web(http_error(429, b'unusual traffic'), self.T_OK)
        with web:
            self.assertEqual(self.gt.translate_srt('Hello', 'auto'), 'שלום')
            self.assertEqual(self.gt.route(), 'dict-chrome-ex')
            self.assertIsNone(self.gt.last_failure())
            # for an hour the second address is asked first: no request to gtx
            self.assertEqual(self.gt.translate_lines(['Hello'], 'en'), ['שלום'])
        self.assertEqual(asked, ['gtx', 't', 't'])
        # an hour later gtx is asked again
        with mock.patch.object(self.gt.time, 'time', return_value=self.gt._GTX_REFUSED[0] + 3601):
            asked2, web2 = self.web(None, AssertionError('not asked'))
            with web2:
                self.assertEqual(self.gt.translate_srt('Hello', 'en'), 'שלום')
        self.assertEqual((asked2, self.gt.route()), (['gtx'], 'gtx'))

    def test_the_second_address_answers_in_both_shapes(self):
        for body in (b'["\\u05e9\\u05dc\\u05d5\\u05dd"]', self.T_OK):
            self.gt._GTX_REFUSED[0] = None
            asked, web = self.web(http_error(403), body)
            with web:
                self.assertEqual(self.gt.translate_srt('Hello', 'en'), 'שלום', body)

    def test_only_a_refusal_goes_to_the_second_address(self):
        for exc, kind in ((http_error(500), 'reply'),
                          (urllib.error.URLError(socket.gaierror(11001, 'getaddrinfo failed')), 'network'),
                          (urllib.error.URLError(ssl.SSLCertVerificationError(1, 'verify failed')), 'tls')):
            asked, web = self.web(exc, AssertionError('not asked'))
            with web:
                self.assertIsNone(self.gt.translate_srt('Hello', 'en'))
            self.assertEqual((asked, self.gt.last_failure()[0]), (['gtx'], kind))
            self.assertIsNone(self.gt._GTX_REFUSED[0])

    def test_both_refusing_is_blocked_and_the_log_names_both(self):
        asked, web = self.web(http_error(429), http_error(429))
        with web:
            self.assertIsNone(self.gt.translate_srt('Hello', 'en'))
        self.assertEqual((asked, self.gt.last_failure()[0]), (['gtx', 't'], 'blocked'))
        # reviewer C1: the second address failing otherwise names the first one's refusal too
        self.gt._GTX_REFUSED[0] = None
        asked, web = self.web(http_error(429), http_error(500))
        with web:
            self.assertIsNone(self.gt.translate_srt('Hello', 'en'))
        self.assertEqual(self.gt.last_failure(), ('reply', 'HTTP 500 (the first address: HTTP 429)'))

    def test_within_the_hour_a_refusing_second_address_tries_gtx_once_more(self):
        # reviewer S1: gtx may have recovered while the second address now refuses
        self.gt._GTX_REFUSED[0] = self.gt.time.time() - 60
        asked, web = self.web(None, http_error(429))
        with web:
            self.assertEqual(self.gt.translate_srt('Hello', 'en'), 'שלום')
        self.assertEqual((asked, self.gt.route(), self.gt._GTX_REFUSED[0]), (['t', 'gtx'], 'gtx', None))
        # both refusing within the hour: blocked, the hour kept
        self.gt._GTX_REFUSED[0] = since = self.gt.time.time() - 60
        asked, web = self.web(http_error(429), http_error(429))
        with web:
            self.assertIsNone(self.gt.translate_srt('Hello', 'en'))
        self.assertEqual((asked, self.gt.last_failure()[0], self.gt._GTX_REFUSED[0]),
                         (['t', 'gtx'], 'blocked', since))

    def test_the_hour_is_kept_where_every_part_of_kodi_sees_it(self):
        # reviewer S2: a subtitle search runs in a script of its own -- a window property, not module state
        props = {}

        class Home(object):
            def getProperty(self, key):
                return props.get(key, '')

            def setProperty(self, key, value):
                props[key] = value
        with mock.patch.object(self.gt, '_home', return_value=Home()):
            asked, web = self.web(http_error(429), self.T_OK)
            with web:
                self.assertEqual(self.gt.translate_srt('Hello', 'en'), 'שלום')
            self.assertTrue(props[self.gt._REFUSED_PROP].isdigit())
            self.gt._GTX_REFUSED[0] = None          # another script: no module memory
            asked, web = self.web(AssertionError('gtx not asked within the hour'), self.T_OK)
            with web:
                self.assertEqual(self.gt.translate_srt('Hello', 'en'), 'שלום')
            self.assertEqual(asked, ['t'])

    def test_the_log_names_the_second_address(self):
        logged = []
        with mock.patch.object(self.gt, 'translate_srt', return_value='1\n00:00:01,000 --> 00:00:02,000\nשלום\n'), \
                mock.patch.object(self.gt, 'route', return_value='dict-chrome-ex'), \
                mock.patch.object(self.tr.kodi_utils, 'notify'), \
                mock.patch.object(self.tr.cache, 'save_text'), \
                mock.patch.object(self.tr, '_reapply_rtl_fix_in_place'), \
                mock.patch('builtins.open', mock.mock_open()), \
                mock.patch.object(self.tr.kodi_utils, 'log', side_effect=lambda m, **k: logged.append(m)):
            self.assertEqual(self.tr._google_translate_and_save(SRT, 'en', 'p.srt', {}), 'p.srt')
        self.assertTrue(any('second address' in m for m in logged), logged)

    def test_the_messages_stay_one_toast_long_and_read_right_to_left(self):
        for text in list(self.tr._GOOGLE_FAIL_SAY.values()) + [self.tr._GOOGLE_FAIL_TITLE]:
            # Onyx's toast shows one line: a 73-character one was cut at both ends in QA
            self.assertLessEqual(len(text), 56, text)
            # Kodi takes a line's direction from its first strong letter
            first = next(c for c in text if c.isalpha())
            self.assertTrue('א' <= first <= 'ת', text)


if __name__ == '__main__':
    unittest.main()
