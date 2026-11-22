# MoranSubs by MoranTheKing - https://github.com/MoranTheKing/Kodi-POV-IL
# SPDX-License-Identifier: GPL-3.0-or-later (additional terms: LICENSE.txt)
"""Pairing from a phone through a relay, for a phone that cannot reach this device on the home network (0.3.112).

The local pair server (gemini_pair.py) needs the phone to open http://<this device>:<port>. That fails behind a VPN on
the phone or here, a router that keeps the wired side from the wireless one, or a PC's firewall (the owner, Nov 2026:
"people on a LAN cable, the phone on the same Wi-Fi -- it does not let them open the link; it used to work").

Here the phone sends the key through a public relay instead -- ntfy.sh, an open-source message service -- encrypted
TO THIS DEVICE, so the relay, the page's host and anyone who photographs the QR see nothing they can use:

  * this device makes a fresh P-256 key pair for every pairing; the QR carries only the PUBLIC key and a random topic.
    The private key is never written anywhere and is gone when the pairing ends;
  * the page (pair/ on GitHub Pages: our own script only, a strict Content-Security-Policy) makes its own fresh key
    pair, derives a shared secret with ECDH (WebCrypto), and HKDF-SHA256 turns it into an encryption key and a MAC
    key; the key is encrypted with HMAC-SHA256 in counter mode under a random nonce and signed with HMAC-SHA256
    (encrypt-then-MAC). Only this device's private key opens it, and a changed byte is refused;
  * anyone holding the QR could still send a key of THEIR own (the public key is public): the caller shows the
    received key's fingerprint and asks before saving it;
  * a link to the page is no secret either: anyone could make one with THEIR public key and post it ("connect
    Gemini here"), and the keys typed into it would be theirs to open. So the device shows a 6-digit code beside the
    QR (`pairing_code`, from its public key), and the page seals nothing until the viewer types the code their own
    screen shows: a link that did not come from that screen has a code no screen of theirs shows.

Python's standard library only (Kodi has nothing else): the P-256 arithmetic is the textbook Jacobian one, checked
against the NIST ECDH test vector and against the browser's own ECDH in the tests.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request

PAGE = 'https://morantheking.github.io/Kodi-POV-IL/pair/'
RELAY = 'https://ntfy.sh/'
INFO = b'povil-pair-v1'
VERSION = 'v1'
POLL_S = 5.0                 # ntfy.sh lets a visitor ask once in 5 s for good, after a burst of 60 (5 min = 60)
MAX_KEY_BYTES = 512
_UA = 'Kodi-POV-IL MoranSubs pairing'

# ---------------------------------------------------------------- P-256 (NIST FIPS 186-4, SEC 2 secp256r1)
P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
A = P - 3
B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
     0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)
_INF = (1, 1, 0)             # the point at infinity, in Jacobian coordinates (Z = 0)


def on_curve(x, y):
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


def _double(pt):
    x, y, z = pt
    if z == 0 or y == 0:
        return _INF
    yy = y * y % P
    s = 4 * x * yy % P
    zz = z * z % P
    m = (3 * x * x + A * zz * zz) % P
    x3 = (m * m - 2 * s) % P
    y3 = (m * (s - x3) - 8 * yy * yy) % P
    z3 = 2 * y * z % P
    return (x3, y3, z3)


def _add(p1, p2):
    if p1[2] == 0:
        return p2
    if p2[2] == 0:
        return p1
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    z1z1, z2z2 = z1 * z1 % P, z2 * z2 % P
    u1, u2 = x1 * z2z2 % P, x2 * z1z1 % P
    s1, s2 = y1 * z2 * z2z2 % P, y2 * z1 * z1z1 % P
    if u1 == u2:
        return _double(p1) if s1 == s2 else _INF
    h, r = (u2 - u1) % P, (s2 - s1) % P
    hh = h * h % P
    hhh = h * hh % P
    v = u1 * hh % P
    x3 = (r * r - hhh - 2 * v) % P
    y3 = (r * (v - x3) - s1 * hhh) % P
    z3 = h * z1 * z2 % P
    return (x3, y3, z3)


def _affine(pt):
    if pt[2] == 0:
        return None
    zi = pow(pt[2], -1, P)
    zi2 = zi * zi % P
    return (pt[0] * zi2 % P, pt[1] * zi2 * zi % P)


def scalar_mult(k, point):
    """k * point (affine in, affine out; None for the point at infinity). A Montgomery ladder: the same steps for
    every bit."""
    r0, r1 = _INF, (point[0], point[1], 1)
    for i in reversed(range(256)):
        if (k >> i) & 1:
            r0, r1 = _add(r0, r1), _double(r1)
        else:
            r1, r0 = _add(r0, r1), _double(r0)
    return _affine(r0)


def encode_point(pt):
    return b'\x04' + pt[0].to_bytes(32, 'big') + pt[1].to_bytes(32, 'big')


def decode_point(raw):
    """An uncompressed P-256 point, checked to be on the curve; None for anything else."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != 65 or raw[0] != 4:
        return None
    x, y = int.from_bytes(raw[1:33], 'big'), int.from_bytes(raw[33:], 'big')
    return (x, y) if on_curve(x, y) else None


def new_private_key():
    return secrets.randbelow(N - 1) + 1


def public_key(d):
    return encode_point(scalar_mult(d, G))


def ecdh(d, peer_raw):
    """The shared secret's x coordinate (32 bytes, as WebCrypto's ECDH deriveBits gives it), or None when the peer's
    point is not a valid one."""
    peer = decode_point(peer_raw)
    if peer is None:
        return None
    shared = scalar_mult(d, peer)
    if shared is None:
        return None
    return shared[0].to_bytes(32, 'big')


# ---------------------------------------------------------------- HKDF, the stream and the tag
def hkdf(ikm, salt, info, length):
    """RFC 5869 HKDF-SHA256."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, block, i = b'', b'', 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


def _keystream(key, nonce, length):
    out, i = b'', 0
    while len(out) < length:
        out += hmac.new(key, nonce + i.to_bytes(4, 'big'), hashlib.sha256).digest()
        i += 1
    return out[:length]


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _unb64(text):
    if not isinstance(text, str) or not text or len(text) > 2048:
        raise ValueError('bad field')
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _keys(shared, sender_pub, box_pub):
    okm = hkdf(shared, sender_pub + box_pub, INFO, 64)
    return okm[:32], okm[32:]


def _tag(mac_key, sender_pub, nonce, ct):
    return hmac.new(mac_key, VERSION.encode('ascii') + sender_pub + nonce + ct, hashlib.sha256).digest()


def seal(box_pub, text, sender_key=None, nonce=None):
    """The phone's side, as pair/pair.js does it (for the tests): 'v1.<sender pub>.<nonce>.<ct>.<tag>'."""
    sender_key = sender_key or new_private_key()
    sender_pub = public_key(sender_key)
    shared = ecdh(sender_key, box_pub)
    if shared is None:
        raise ValueError('bad public key')
    enc_key, mac_key = _keys(shared, sender_pub, box_pub)
    nonce = nonce or os.urandom(16)
    pt = text.encode('utf-8')
    ct = bytes(a ^ b for a, b in zip(pt, _keystream(enc_key, nonce, len(pt))))
    return '.'.join([VERSION] + [_b64(x) for x in (sender_pub, nonce, ct, _tag(mac_key, sender_pub, nonce, ct))])


def open_sealed(box_key, box_pub, message):
    """The text sealed to this device, or None for anything that is not exactly that (wrong format, a point off the
    curve, a changed byte, another device's message)."""
    parts = (message or '').strip().split('.')
    if len(parts) != 5 or parts[0] != VERSION:
        return None
    try:
        sender_pub, nonce, ct, tag = (_unb64(p) for p in parts[1:])
    except (ValueError, TypeError):
        return None
    if len(nonce) != 16 or len(tag) != 32 or not 0 < len(ct) <= MAX_KEY_BYTES:
        return None
    shared = ecdh(box_key, sender_pub)
    if shared is None:
        return None
    enc_key, mac_key = _keys(shared, sender_pub, box_pub)
    if not hmac.compare_digest(_tag(mac_key, sender_pub, nonce, ct), tag):
        return None
    pt = bytes(a ^ b for a, b in zip(ct, _keystream(enc_key, nonce, len(ct))))
    try:
        return pt.decode('utf-8')
    except UnicodeDecodeError:
        return None


def pairing_code(public):
    """Six digits from this pairing's public key: shown beside the QR, typed on the phone, and checked by the page
    (pair.js pairingCode) before it seals anything -- the code of a link someone else made is on no screen of the
    viewer's."""
    return '%06d' % (int.from_bytes(hashlib.sha256(public).digest()[:4], 'big') % 1000000)


# ---------------------------------------------------------------- the relay
def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': _UA, 'Accept': 'application/x-ndjson'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read(256 * 1024).decode('utf-8', 'replace')


class PairRelay(object):
    """One pairing: the page's address for the QR (`url`), a background poll of the relay, and the key that came,
    if one did (`received_key()`). `service` is 'gemini' or 'mdblist' (the page's wording and its check)."""

    def __init__(self, service, fetch=None, poll_s=POLL_S, log=None):
        self._key = new_private_key()
        self.public = public_key(self._key)
        self.code = pairing_code(self.public)
        self.topic = 'povil-pair-' + _b64(os.urandom(15))
        self.url = PAGE + '#' + urllib.parse.urlencode(
            {'s': service, 't': self.topic, 'p': _b64(self.public)})
        self._fetch = fetch or _fetch
        self._poll_s = poll_s
        self._log = log or (lambda m: None)
        self._received = ''
        self._seen = set()
        self.refused = 0          # messages on the topic that were not sealed to this device
        self.errors = 0           # polls that did not answer
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name='povil-pair-relay', daemon=True)
        self._thread.start()
        return self

    def poll_once(self):
        """Read what the relay holds for the topic; True once a key sealed to this device is in."""
        text = self._fetch(RELAY + self.topic + '/json?poll=1&since=all')
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get('event') != 'message':
                continue
            ident = event.get('id')
            if ident in self._seen:
                continue
            self._seen.add(ident)
            key = open_sealed(self._key, self.public, event.get('message') or '')
            if key:
                self._received = key
                return True
            self.refused += 1
        return False

    def _run(self):
        while not self._stop.is_set():
            try:
                if self.poll_once():
                    self._log('pair relay: a key sealed to this device came in')
                    return
            except Exception as exc:
                self.errors += 1
                if self.errors in (1, 5, 20):
                    self._log('pair relay: the relay did not answer ({0}, {1} time(s))'.format(
                        type(exc).__name__, self.errors))
            self._stop.wait(self._poll_s)

    def received_key(self):
        return self._received

    def shutdown(self):
        """Stop polling and forget the private key."""
        self._stop.set()
        self._key = 0
