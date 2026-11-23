"""MoranSubs 0.3.112: pairing from a phone through an encrypted relay.

The owner, Nov 2026: "people say the QR connection to Gemini does not work -- they are on a LAN cable, the phone on
the same Wi-Fi, and it does not let them open the link; it used to work" -- and: "the most important is security, of
course, at the highest level there is". The local pair server needs the phone to reach this device (a VPN, a router
that keeps wired from wireless, a firewall break it). Now the QR leads to pair/ on GitHub Pages, which seals the key to
this device's one-time P-256 public key (ECDH + HKDF-SHA256 + HMAC-SHA256 counter-mode stream + HMAC-SHA256 tag) and
posts it to a relay (ntfy.sh); only this device's private key opens it. The received key is shown by its letters and
saved only on a yes.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'
PAGE = ROOT / 'pair'


def load():
    spec = importlib.util.spec_from_file_location('pair_relay_test', LIB / 'pair_relay.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load()

# NIST CAVS ECDH, P-256, COUNT = 0 (SP 800-56A test vectors)
QX = 0x700c48f77f56584c5cc632ca65640db91b6bacce3a4df6b42ce7cc838833d287
QY = 0xdb71e509e3fd9b060ddb20ba5c51dcc5948d46fbf640dfe0441782cab85fa4ac
D = 0x7d7dc5f71eb29ddaf80d6214632eeae03d9058af1fb6d22ed80badb62bc1a534
OX = 0xead218590119e8876b29146ff89ca61770c4edbbf97d38ce385ed281d8a6b230
OY = 0x28af61281fd35e2fa7002523acc85a429cb06ee6648325389f59edfce1405141
Z = 0x46fc62106420ff012e54a434fbdd2d25ccc5852060561e68040dd7778997bd7b
# A made-up key that looks like no real one (GitHub's secret scanning flagged a dummy in a Google key's shape).
KEY = 'TEST-not-a-real-key_0123456789AB'


class Crypto(unittest.TestCase):
    def test_nist_vector(self):
        self.assertEqual(R.scalar_mult(D, R.G), (OX, OY))
        self.assertEqual(R.ecdh(D, R.encode_point((QX, QY))), Z.to_bytes(32, 'big'))

    def test_a_point_off_the_curve_or_misshapen_is_refused(self):
        self.assertIsNone(R.ecdh(D, R.encode_point((QX, QY ^ 1))))
        self.assertIsNone(R.ecdh(D, b'\x02' + bytes(64)))
        self.assertIsNone(R.ecdh(D, R.encode_point((QX, QY))[:64]))
        self.assertIsNone(R.decode_point(b'\x04' + R.P.to_bytes(32, 'big') + bytes(32)))

    def test_hkdf_rfc5869_case_1(self):
        okm = R.hkdf(bytes.fromhex('0b' * 22), bytes.fromhex('000102030405060708090a0b0c'),
                     bytes.fromhex('f0f1f2f3f4f5f6f7f8f9'), 42)
        self.assertEqual(okm.hex(), '3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf'
                                    '34007208d5b887185865')

    def test_round_trip_and_every_change_is_refused(self):
        box = R.new_private_key()
        pub = R.public_key(box)
        sealed = R.seal(pub, KEY)
        self.assertEqual(R.open_sealed(box, pub, sealed), KEY)
        self.assertNotIn(KEY, sealed)
        parts = sealed.split('.')
        for i in range(1, 5):
            raw = bytearray(R._unb64(parts[i]))
            raw[len(raw) // 2] ^= 1
            changed = parts[:i] + [R._b64(bytes(raw))] + parts[i + 1:]
            with self.subTest(field=i):
                self.assertIsNone(R.open_sealed(box, pub, '.'.join(changed)))
        self.assertIsNone(R.open_sealed(box, pub, 'v2' + sealed[2:]))
        self.assertIsNone(R.open_sealed(box, pub, sealed + '.x'))
        self.assertIsNone(R.open_sealed(box, pub, 'not a message'))
        other = R.new_private_key()                          # another device's message
        self.assertIsNone(R.open_sealed(other, R.public_key(other), sealed))
        self.assertIsNone(R.open_sealed(box, pub, R.seal(R.public_key(other), KEY)))

    def test_a_fresh_nonce_and_sender_key_every_time(self):
        box = R.new_private_key()
        pub = R.public_key(box)
        a, b = R.seal(pub, KEY), R.seal(pub, KEY)
        self.assertNotEqual(a.split('.')[1:4], b.split('.')[1:4])


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class ThePagesOwnCode(unittest.TestCase):
    """pair/pair.js under node's WebCrypto: what it seals, the device opens."""

    def node(self, script, *args):
        out = subprocess.check_output(['node', '-e', script, str(PAGE / 'pair.js')] + list(args), text=True,
                                      timeout=60)
        return json.loads(out)

    def test_the_page_seals_what_the_device_opens(self):
        box = R.new_private_key()
        pub = R.public_key(box)
        js = r'''
const pair = require(process.argv[1]);
(async () => {
  const sealed = await pair.seal(pair.unb64u(process.argv[2]), process.argv[3]);
  console.log(JSON.stringify({sealed}));
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
        for key in (KEY, 'AQ.Ab8RN6LMSPFFEXAMPLE.only-a-shape_x', 'k' * 512):
            with self.subTest(length=len(key)):
                got = self.node(js, R._b64(pub), key)
                self.assertNotIn('error', got)
                self.assertEqual(R.open_sealed(box, pub, got['sealed']), key)
        too_long = self.node(js, R._b64(pub), 'k' * 513)
        self.assertIn('error', too_long)

    def test_the_page_computes_the_code_the_device_shows(self):
        pubs = [R.public_key(R.new_private_key()) for _ in range(6)]
        js = r'''
const pair = require(process.argv[1]);
(async () => {
  const codes = [];
  for (const p of process.argv.slice(2)) codes.push(await pair.pairingCode(pair.unb64u(p)));
  console.log(JSON.stringify({codes, typed: [pair.digits(' 482 913 '), pair.digits('４８２-９１３'), pair.digits('')]}));
})().catch(e => { console.log(JSON.stringify({error: String(e)})); });
'''
        got = self.node(js, *[R._b64(p) for p in pubs])
        self.assertEqual(got['codes'], [R.pairing_code(p) for p in pubs])
        self.assertEqual(got['typed'], ['482913', '482913', ''])

    def test_the_link_is_checked_and_sanitize_matches_the_device(self):
        relay = R.PairRelay('gemini', fetch=lambda url: '')
        js = r'''
const pair = require(process.argv[1]);
const link = pair.readLink(process.argv[2]);
console.log(JSON.stringify({
  ok: !!link, service: link && link.service, topic: link && link.topic, pubLen: link && link.pub.length,
  bad1: pair.readLink('#s=gemini&t=povil-pair-x&p=AA'), bad2: pair.readLink('#s=evil&t=' + (link && link.topic) + '&p=x'),
  clean: pair.sanitize(process.argv[3])}));
'''
        raw = ' “AIza–Sy DUMMY​”\n'
        got = self.node(js, '#' + relay.url.split('#', 1)[1], raw)
        self.assertEqual((got['ok'], got['service'], got['topic'], got['pubLen']), (True, 'gemini', relay.topic, 65))
        self.assertIsNone(got['bad1'])
        self.assertIsNone(got['bad2'])
        sys.path.insert(0, str(LIB))
        try:
            spec = importlib.util.spec_from_file_location('gemini_pair_test', LIB / 'gemini_pair.py')
            gp = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gp)
        finally:
            sys.path.remove(str(LIB))
        self.assertEqual(got['clean'], gp._sanitize_key(raw))


class ThePage(unittest.TestCase):
    def test_a_strict_policy_and_no_code_but_ours(self):
        html = (PAGE / 'index.html').read_text(encoding='utf-8')
        csp = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', html).group(1)
        for rule in ("default-src 'none'", "script-src 'self'", "style-src 'self'", "base-uri 'none'",
                     "form-action 'none'", 'connect-src https://ntfy.sh https://generativelanguage.googleapis.com '
                                           'https://api.mdblist.com'):
            self.assertIn(rule, csp)
        self.assertNotIn('unsafe', csp)
        self.assertIn('<meta name="referrer" content="no-referrer">', html)
        self.assertEqual(re.findall(r'<script[^>]*>', html), ['<script src="pair.js">'])
        self.assertNotIn('<style', html)
        self.assertNotRegex(html, r'\son[a-z]+=')                       # no inline handlers
        js = (PAGE / 'pair.js').read_text(encoding='utf-8')
        self.assertNotIn('localStorage', js)
        self.assertNotIn('sessionStorage', js)
        self.assertNotIn('innerHTML', js)
        self.assertNotIn('console.', js)
        self.assertIn("credentials: 'omit'", js)

    def test_nothing_leaves_the_page_before_the_code_from_the_screen_matches(self):
        # a link to the page with someone else's public key, posted in a group, would otherwise collect keys
        html = (PAGE / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="code"', html)
        self.assertIn('קישור או קוד שקיבלתם ממישהו אחר', html)
        js = (PAGE / 'pair.js').read_text(encoding='utf-8')
        submit = js[js.index("form.addEventListener('submit'"):]
        check = submit.index('pairingCode(link.pub)')
        self.assertLess(check, submit.index('if (typed !== code)'))
        self.assertLess(submit.index('if (typed !== code)'), submit.index('validate(link.service, key)'))
        self.assertLess(submit.index('validate(link.service, key)'), submit.index('send(link, key)'))
        self.assertEqual(submit.count('validate('), 1)
        self.assertEqual(submit.count('send('), 1)


class TheRelay(unittest.TestCase):
    def test_the_link_holds_only_public_things(self):
        relay = R.PairRelay('gemini', fetch=lambda url: '')
        self.assertTrue(relay.url.startswith('https://morantheking.github.io/Kodi-POV-IL/pair/#s=gemini&t=povil-pair-'))
        self.assertRegex(relay.topic, r'^povil-pair-[A-Za-z0-9_-]{20}$')
        self.assertIn('p=' + R._b64(relay.public), relay.url)
        self.assertNotIn(format(relay._key, 'x'), relay.url)
        self.assertNotIn(R._b64(relay._key.to_bytes(32, 'big')), relay.url)
        self.assertNotEqual(R.PairRelay('gemini', fetch=lambda url: '').topic, relay.topic)
        self.assertRegex(relay.code, r'^[0-9]{6}$')
        self.assertEqual(relay.code, R.pairing_code(relay.public))
        self.assertNotIn(relay.code, relay.url)

    def test_the_code_is_the_one_the_page_computes(self):
        # SHA-256 of the public key, its first 4 bytes big-endian, mod 10**6, six digits
        import hashlib
        pub = R.public_key(12345)
        n = int.from_bytes(hashlib.sha256(pub).digest()[:4], 'big')
        self.assertEqual(R.pairing_code(pub), '%06d' % (n % 1000000))
        self.assertEqual(R.POLL_S, 5.0)          # ntfy.sh: one ask in 5 s for good, after a burst of 60

    def test_only_a_message_sealed_to_this_device_is_taken(self):
        asked = []
        relay = R.PairRelay('mdblist', fetch=None)
        other = R.new_private_key()
        lines = [
            {'event': 'open', 'id': 'o'},
            {'event': 'keepalive', 'id': 'k'},
            {'event': 'message', 'id': 'm1', 'message': 'hello'},
            {'event': 'message', 'id': 'm2', 'message': R.seal(R.public_key(other), 'not-for-us')},
            {'event': 'message', 'id': 'm3', 'message': R.seal(relay.public, KEY)},
        ]

        def fetch(url):
            asked.append(url)
            return '\n'.join(json.dumps(x) for x in lines) + '\nnot json\n'
        relay._fetch = fetch
        self.assertTrue(relay.poll_once())
        self.assertEqual(relay.received_key(), KEY)
        self.assertEqual(relay.refused, 2)
        self.assertEqual(asked, ['https://ntfy.sh/' + relay.topic + '/json?poll=1&since=all'])

    def test_polls_until_a_key_and_shutdown_forgets_the_private_key(self):
        relay = R.PairRelay('gemini', fetch=None, poll_s=0.01)
        answers = iter([OSError('down'), '', json.dumps({'event': 'message', 'id': 'x',
                                                         'message': R.seal(relay.public, KEY)})])

        def fetch(url):
            a = next(answers)
            if isinstance(a, Exception):
                raise a
            return a
        relay._fetch = fetch
        relay.start()
        relay._thread.join(5)
        self.assertEqual(relay.received_key(), KEY)
        self.assertEqual(relay.errors, 1)
        relay.shutdown()
        self.assertEqual(relay._key, 0)


class TheDevice(unittest.TestCase):
    def test_the_pair_flow_uses_the_relay_draws_the_qr_and_asks_before_saving(self):
        src = (ROOT / 'service.subtitles.kodipovilai/default.py').read_text(encoding='utf-8')
        flow = src.split('def _run_pair_qr(')[1].split('\ndef ')[0]
        self.assertIn('relay = _pair_relay(service)', flow)
        self.assertIn('qr_data = relay.url if relay else primary', flow)
        self.assertIn('_pair_qr_image(qr_data)', flow)
        self.assertLess(flow.index('_pair_qr_image(qr_data)'), flow.index('api.qrserver.com'))  # only a fallback
        self.assertIn('relay.shutdown()', flow)
        self.assertIn('if not _approve_received_key(key, title_text):', flow)
        self.assertIn("code=relay.code if relay else ''", flow)
        # without segno, the relay's address goes to no QR web service: the QR then leads to the home network
        fallback = flow[flow.index('if not qr_url:'):flow.index('api.qrserver.com')]
        self.assertIn('relay = None', fallback)
        self.assertIn('_url_quote(primary)', flow)
        self.assertNotIn('_url_quote(qr_data)', flow)
        self.assertIn("_run_pair_qr(ps, 'MDBList - התאמה מטלפון', service='mdblist')", src)
        self.assertTrue((LIB / 'segno/__init__.py').is_file())
        self.assertTrue((LIB / 'segno/LICENSE').is_file())

    def functions(self, *names, scope=None):
        src = (ROOT / 'service.subtitles.kodipovilai/default.py').read_text(encoding='utf-8')
        ns = dict(scope or {})
        for name in names:
            start = src.index('def %s(' % name)
            exec(src[start:src.index('\ndef ', start + 10)], ns)
        return ns

    def test_the_qr_png_is_8_bit_and_holds_the_matrix(self):
        # segno's own PNG is 1-bit, and QA Kodi 21 drew it as nothing
        import struct
        import tempfile
        import zlib
        sys.path.insert(0, str(ROOT / 'service.subtitles.kodipovilai'))
        try:
            from resources.lib import segno
        finally:
            sys.path.remove(str(ROOT / 'service.subtitles.kodipovilai'))
        matrix = segno.make_qr(R.PairRelay('gemini', fetch=lambda url: '').url, error='m').matrix
        fd, path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        try:
            self.functions('_qr_png')['_qr_png'](matrix, path, scale=3, border=2)
            with open(path, 'rb') as f:
                data = f.read()
        finally:
            os.remove(path)
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        w, h, depth, colour = struct.unpack('>IIBB', data[16:26])
        side = (len(matrix) + 4) * 3
        self.assertEqual((w, h, depth, colour), (side, side, 8, 0))
        at, idat = 8, b''
        while at < len(data):
            n = struct.unpack('>I', data[at:at + 4])[0]
            kind, body = data[at + 4:at + 8], data[at + 8:at + 8 + n]
            self.assertEqual(struct.unpack('>I', data[at + 8 + n:at + 12 + n])[0], zlib.crc32(kind + body) & 0xffffffff)
            if kind == b'IDAT':
                idat += body
            at += 12 + n
        raw = zlib.decompress(idat)
        rows = [raw[y * (side + 1) + 1:(y + 1) * (side + 1)] for y in range(side)]
        for r, row in enumerate(matrix):
            for c, dark in enumerate(row):
                with self.subTest(r=r, c=c):
                    self.assertEqual(rows[(r + 2) * 3 + 1][(c + 2) * 3 + 1], 0 if dark else 255)
        self.assertEqual(rows[0][0], 255)                     # the quiet border is light

    def test_the_approval_starts_on_no_and_saves_only_on_yes(self):
        asked = []

        class Dialog(object):
            answer = 0

            def select(self, heading, options, preselect=-1):
                asked.append((heading, list(options), preselect))
                return Dialog.answer
        xbmcgui = type('xbmcgui', (), {'Dialog': Dialog})
        approve = self.functions('_approve_received_key', scope={'xbmcgui': xbmcgui})['_approve_received_key']
        self.assertFalse(approve(KEY, 'Gemini AI - התאמה מטלפון'))
        heading, options, preselect = asked[0]
        self.assertEqual(preselect, 0)
        self.assertEqual(options[0], 'לא, לבטל')
        self.assertEqual(options[1], 'כן, לשמור: ' + KEY[:8] + '…' + KEY[-8:])
        Dialog.answer = 1
        self.assertTrue(approve(KEY, 'x'))
        Dialog.answer = -1                                    # Back
        self.assertFalse(approve(KEY, 'x'))

    def test_the_bundled_qr_holds_the_whole_link(self):
        sys.path.insert(0, str(ROOT / 'service.subtitles.kodipovilai'))
        try:
            from resources.lib import segno
        finally:
            sys.path.remove(str(ROOT / 'service.subtitles.kodipovilai'))
        relay = R.PairRelay('gemini', fetch=lambda url: '')
        qr = segno.make_qr(relay.url, error='m')
        self.assertLessEqual(qr.version, 12)


if __name__ == '__main__':
    unittest.main()
