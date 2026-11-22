// Kodi POV IL -- a key from the phone to the device that shows the QR, through a relay (MoranSubs 0.3.112).
// The QR's address carries, after '#' (never sent to any server): s = the service, t = a random relay topic,
// p = the device's one-time P-256 PUBLIC key. Here: a one-time key pair of our own, ECDH with the device's key
// (WebCrypto), HKDF-SHA256 -> an encryption key and a MAC key, HMAC-SHA256 in counter mode under a random nonce,
// and an HMAC-SHA256 tag (encrypt-then-MAC). Only the device's private key, which never leaves it, opens it.
// Byte for byte what service.subtitles.kodipovilai/resources/lib/pair_relay.py opens (tests/test_pair_relay.py).
'use strict';

var RELAY = 'https://ntfy.sh/';
var INFO = 'povil-pair-v1';
var MAX_KEY_BYTES = 512;
var SERVICES = {
  gemini: {
    title: 'חיבור Gemini AI',
    label: 'Gemini API Key',
    intro: 'הדביקו כאן את ה-Gemini API key שיצרתם ב-',
    site: 'https://aistudio.google.com/apikey',
    siteText: 'aistudio.google.com/apikey',
    tip: 'בטלפון: "Copy" ב-AI Studio, ואז כאן לחיצה ארוכה בשדה והדבקה.',
    placeholder: 'AIza... או AQ.Ab8...',
    check: 'Google'
  },
  mdblist: {
    title: 'חיבור MDBList',
    label: 'MDBList API Key',
    intro: 'הדביקו כאן את ה-MDBList API key מ-',
    site: 'https://mdblist.com/preferences',
    siteText: 'mdblist.com/preferences',
    tip: 'העתיקו את ה-API key מ-mdblist.com/preferences, ואז כאן לחיצה ארוכה בשדה והדבקה.',
    placeholder: 'המפתח מ-mdblist.com/preferences',
    check: 'MDBList'
  }
};

// The same cleaning as the device's _sanitize_key: iOS smart dashes, NFKC, then the key's own characters only.
var DASH = /[‐‑‒–—―⁃−﹘﹣－]/g;
function sanitize(raw) {
  if (!raw) return '';
  return raw.normalize('NFKC').replace(DASH, '-').replace(/[^A-Za-z0-9_.-]/g, '');
}
function fingerprint(k) {
  var h = k.length >= 8 ? k.slice(0, 8) : k;
  var t = k.length >= 16 ? k.slice(-8) : '';
  return h + (t ? '…' + t : '') + '   (' + k.length + ' chars)';
}

function b64u(bytes) {
  var s = '';
  for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function unb64u(text) {
  if (!/^[A-Za-z0-9_-]+$/.test(text || '')) throw new Error('bad field');
  var s = atob(text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - text.length % 4) % 4));
  var out = new Uint8Array(s.length);
  for (var i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}
function concat() {
  var n = 0, i;
  for (i = 0; i < arguments.length; i++) n += arguments[i].length;
  var out = new Uint8Array(n), at = 0;
  for (i = 0; i < arguments.length; i++) { out.set(arguments[i], at); at += arguments[i].length; }
  return out;
}
function u32(i) { return new Uint8Array([(i >>> 24) & 255, (i >>> 16) & 255, (i >>> 8) & 255, i & 255]); }

function subtle() { return globalThis.crypto.subtle; }
function hmac(key, data) {
  return subtle().importKey('raw', key, {name: 'HMAC', hash: 'SHA-256'}, false, ['sign'])
    .then(function (k) { return subtle().sign('HMAC', k, data); })
    .then(function (sig) { return new Uint8Array(sig); });
}
function hkdf(ikm, salt, info, length) {             // RFC 5869, as pair_relay.hkdf
  return hmac(salt, ikm).then(function (prk) {
    var out = new Uint8Array(0);
    function step(block, i) {
      if (out.length >= length) return out.slice(0, length);
      return hmac(prk, concat(block, info, new Uint8Array([i]))).then(function (next) {
        out = concat(out, next);
        return step(next, i + 1);
      });
    }
    return step(new Uint8Array(0), 1);
  });
}
function keystream(key, nonce, length) {
  var out = new Uint8Array(0);
  function step(i) {
    if (out.length >= length) return Promise.resolve(out.slice(0, length));
    return hmac(key, concat(nonce, u32(i))).then(function (b) { out = concat(out, b); return step(i + 1); });
  }
  return step(0);
}

// 'v1.<our public key>.<nonce>.<ciphertext>.<tag>', sealed to the device's public key (raw, 65 bytes).
function seal(devicePub, text) {
  var enc = new TextEncoder();
  var pt = enc.encode(text);
  if (!pt.length || pt.length > MAX_KEY_BYTES) return Promise.reject(new Error('bad length'));
  var algo = {name: 'ECDH', namedCurve: 'P-256'};
  var mine, minePub, nonce = globalThis.crypto.getRandomValues(new Uint8Array(16));
  return subtle().generateKey(algo, true, ['deriveBits'])
    .then(function (kp) { mine = kp; return subtle().exportKey('raw', kp.publicKey); })
    .then(function (raw) {
      minePub = new Uint8Array(raw);
      // importKey refuses a point that is not on the curve
      return subtle().importKey('raw', devicePub, algo, false, []);
    })
    .then(function (peer) { return subtle().deriveBits({name: 'ECDH', public: peer}, mine.privateKey, 256); })
    .then(function (bits) { return hkdf(new Uint8Array(bits), concat(minePub, devicePub), enc.encode(INFO), 64); })
    .then(function (okm) {
      var encKey = okm.slice(0, 32), macKey = okm.slice(32);
      return keystream(encKey, nonce, pt.length).then(function (ks) {
        var ct = new Uint8Array(pt.length);
        for (var i = 0; i < pt.length; i++) ct[i] = pt[i] ^ ks[i];
        return hmac(macKey, concat(enc.encode('v1'), minePub, nonce, ct)).then(function (tag) {
          return ['v1', b64u(minePub), b64u(nonce), b64u(ct), b64u(tag)].join('.');
        });
      });
    });
}

function readLink(hash) {
  var q = new URLSearchParams((hash || '').replace(/^#/, ''));
  var s = q.get('s'), t = q.get('t'), p = q.get('p');
  if (!SERVICES[s] || !/^povil-pair-[A-Za-z0-9_-]{16,40}$/.test(t || '')) return null;
  var pub;
  try { pub = unb64u(p); } catch (e) { return null; }
  if (pub.length !== 65 || pub[0] !== 4) return null;
  return {service: s, topic: t, pub: pub};
}

function send(link, key) {
  return seal(link.pub, key).then(function (message) {
    return fetch(RELAY + link.topic, {method: 'POST', body: message, cache: 'no-store', referrerPolicy: 'no-referrer',
                                      credentials: 'omit', headers: {'X-Firebase': 'no'}});
  }).then(function (r) { if (!r.ok) throw new Error('relay ' + r.status); return true; });
}

// The key checked against its service FROM THE PHONE, by status: 400/401/403 = a bad key (false); anything else
// that is not a yes (429, 5xx, no network) = unknown (null), sent anyway -- the device checks it again.
function validate(service, key) {
  var ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
  var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 9000) : null;
  var opts = {method: 'GET', cache: 'no-store', referrerPolicy: 'no-referrer', credentials: 'omit'};
  if (ctrl) opts.signal = ctrl.signal;
  var url;
  if (service === 'gemini') {
    url = 'https://generativelanguage.googleapis.com/v1beta/models';
    opts.headers = {'x-goog-api-key': key};
  } else {
    url = 'https://api.mdblist.com/user?apikey=' + encodeURIComponent(key);
  }
  return fetch(url, opts).then(function (r) {
    if (timer) clearTimeout(timer);
    if (r.ok) return true;
    if (r.status === 400 || r.status === 401 || r.status === 403) return false;
    return null;
  }).catch(function () { if (timer) clearTimeout(timer); return null; });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {seal: seal, sanitize: sanitize, readLink: readLink, b64u: b64u, unb64u: unb64u};
} else {
  // public code, no secrets: for checking the page in a browser's console
  globalThis.povilPair = {seal: seal, readLink: readLink};
}

if (typeof document !== 'undefined') {
  (function () {
    var link = readLink(location.hash);
    var el = function (id) { return document.getElementById(id); };
    var elKey = el('key'), elFp = el('fp'), elMsg = el('msg'), form = el('f'), btn = el('go');
    function msg(t, c) { elMsg.textContent = t; elMsg.className = c; }
    if (!link || !globalThis.crypto || !globalThis.crypto.subtle) {
      form.hidden = true;
      msg(link ? 'הדפדפן הזה לא תומך בהצפנה שהחיבור צריך. נסו Chrome, Safari או Firefox מעודכנים.'
               : 'הקישור לא שלם. סרקו שוב את ה-QR שעל המסך.', 'err');
      return;
    }
    var svc = SERVICES[link.service];
    document.title = 'Kodi POV IL - ' + svc.title;
    el('title').textContent = svc.title;
    el('label').textContent = svc.label;
    el('intro').textContent = svc.intro;
    var a = document.createElement('a');
    a.href = svc.site; a.textContent = svc.siteText; a.target = '_blank'; a.rel = 'noopener noreferrer';
    el('intro').appendChild(a);
    el('intro').appendChild(document.createTextNode('. נוודא מול ' + svc.check + ' שהמפתח תקין, ורק אז נשלח אותו ל-Kodi.'));
    el('tip').textContent = svc.tip;
    elKey.placeholder = svc.placeholder;
    // the raw clipboard on paste, before iOS/WebKit can mangle it in the field
    elKey.addEventListener('paste', function (e) {
      try {
        var raw = (e.clipboardData || window.clipboardData).getData('text/plain');
        if (raw) { e.preventDefault(); elKey.value = sanitize(raw); elFp.textContent = fingerprint(elKey.value); }
      } catch (err) { /* the field's value then */ }
    });
    elKey.addEventListener('input', function () {
      elFp.textContent = elKey.value ? fingerprint(sanitize(elKey.value)) : '';
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var key = sanitize(elKey.value || '');
      elKey.value = key;
      elFp.textContent = key ? fingerprint(key) : '';
      if (!key) { msg('הזינו API key.', 'err'); return; }
      btn.disabled = true;
      elKey.readOnly = true;
      msg('בודק את המפתח מול ' + svc.check + '…', 'info');
      validate(link.service, key).then(function (ok) {
        if (ok === false) {
          msg(svc.check + ' דחה את המפתח הזה. העתיקו אותו שוב במלואו (בלי רווח או תו חסר) ונסו שוב.', 'err');
          btn.disabled = false; elKey.readOnly = false;
          return null;
        }
        msg((ok ? 'המפתח תקין. ' : 'לא הצלחנו לבדוק מול ' + svc.check + ' (בעיית רשת?), שולחים בכל זאת. ')
            + 'שולח ל-Kodi מוצפן…', 'info');
        return send(link, key).then(function () {
          elKey.value = '';
          msg('המפתח נשלח ל-Kodi: ' + fingerprint(key) + '. בטלוויזיה יופיעו אותן אותיות. אשרו שם, ואפשר לסגור את הדף.', 'ok');
        });
      }).catch(function () {
        btn.disabled = false; elKey.readOnly = false;
        msg('השליחה לא הצליחה (אין חיבור לאינטרנט?). נסו שוב, או בחרו ב-Kodi "הזנה ידנית".', 'err');
      });
    });
  })();
}
