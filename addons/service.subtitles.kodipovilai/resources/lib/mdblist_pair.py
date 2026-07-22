# MDBList API-key pairing -- the phone-served form + a Kodi-side validator.
#
# Reuses gemini_pair.PairServer's generic transport (free-port pick, 0.0.0.0
# bind, LAN detection, poll-for-key) by passing MDBLIST_FORM as the served HTML.
# Only the form (its on-phone validation URL + text) and the Kodi-side validator
# differ from Gemini; the server-side key sanitizer is shared (MDBList keys use
# the same [A-Za-z0-9_.-] charset).
#
# MDBList auth is an API key from https://mdblist.com/preferences (stored in
# POV's `mdblist.token` setting). Validation: GET https://api.mdblist.com/user
# ?apikey=<key> -> 200 valid, 403/401/400 rejected. The API sends
# Access-Control-Allow-Origin: * so the phone browser can validate before submit.
#
# stdlib only.

import urllib.error
import urllib.parse
import urllib.request

MDBLIST_USER_URL = 'https://api.mdblist.com/user'


def validate_key(key, timeout=15):
    """Kodi-side check: True if MDBList accepts the key, False if it rejects it,
    None on a transient/network error (so the caller can decide). Mirrors the
    phone-side classification."""
    k = (key or '').strip()
    if not k:
        return False
    url = MDBLIST_USER_URL + '?apikey=' + urllib.parse.quote(k, safe='')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'kodi-pov-il'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return getattr(resp, 'status', 200) == 200
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return False          # genuinely bad key
        return None               # 429 / 5xx -> ambiguous
    except Exception:
        return None               # network / timeout -> ambiguous


# Form served on GET / by the shared PairServer. Same iOS/WebKit corruption
# proofing as the Gemini form (type=password, raw-clipboard paste, sanitize,
# readOnly-during-check, AbortController timeout, fetch feature-detect, status
# classification), but validated against MDBList's /user endpoint.
MDBLIST_FORM = '''<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kodi POV IL - MDBList API Key</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
           margin: 0; padding: 24px; background: #101820; color: #f6f1df; }
    .card { max-width: 540px; margin: 32px auto; padding: 28px;
            background: #172635; border: 1px solid #34495e;
            border-radius: 16px; }
    h1 { margin: 0 0 8px 0; color: #ffd166; font-size: 1.4rem; }
    p { line-height: 1.6; color: #b7c4cf; font-size: 0.95rem; }
    label { display: block; margin-top: 16px; font-weight: bold; }
    input[type=password] { width: 100%; box-sizing: border-box; margin-top: 8px;
                       padding: 14px; font-size: 1.1rem; direction: ltr;
                       background: #0a0f15; color: #f6f1df;
                       border: 1px solid #34495e; border-radius: 8px; }
    button { width: 100%; margin-top: 20px; padding: 14px; font-size: 1.1rem;
             font-weight: bold; color: #101820; background: #ffd166;
             border: none; border-radius: 8px; cursor: pointer; }
    button:disabled { opacity: .5; cursor: default; }
    button:active { background: #e0b54a; }
    #fp { direction: ltr; text-align: center; margin-top: 10px; color: #f6f1df; }
    #msg { margin-top: 14px; padding: 12px; border-radius: 8px; font-size: 0.95rem;
           line-height: 1.5; display: none; }
    .ok { background: #16351f; color: #a7e0b0; display: block !important; }
    .err { background: #351a1a; color: #e6a6a6; display: block !important; }
    .info { background: #14202c; color: #b7c4cf; display: block !important; }
    .small { font-size: 0.85rem; color: #b7c4cf; margin-top: 12px; }
    code { background: #0a0f15; padding: 2px 6px; border-radius: 4px;
           font-size: 0.9rem; direction: ltr; }
  </style>
</head>
<body>
  <div class="card">
    <h1>חיבור MDBList</h1>
    <p>
      הדבק כאן את ה-MDBList API key מ-
      <code>mdblist.com/preferences</code>. נוודא מול MDBList
      שהמפתח תקין, ורק אז נשלח אותו ל-Kodi.
    </p>
    <form method="POST" action="/submit" id="f">
      <label for="key">MDBList API Key</label>
      <!--
        iOS/WebKit note: type=password suppresses the smart-punctuation /
        autocorrect that silently corrupt a pasted key on iOS (every iOS browser
        is WebKit). We also read the RAW clipboard on paste (bypassing field-level
        mangling) and validate the key against MDBList FROM THE PHONE before
        submitting -- so a corrupted / bad key is caught here with a clear message
        instead of a confusing error back in Kodi. The server still sanitizes.
      -->
      <input type="password" id="key" name="key"
             autocomplete="off" autocapitalize="off"
             autocorrect="off" spellcheck="false"
             inputmode="verbatim"
             placeholder="המפתח מ-mdblist.com/preferences" required>
      <div id="fp"></div>
      <button type="submit" id="go">בדוק ושלח ל-Kodi</button>
    </form>
    <div id="msg"></div>
    <p class="small">
      טיפ: פתחו את <code>mdblist.com/preferences</code>, העתיקו את
      ה-API key, וכאן לחצו לחיצה ארוכה בשדה והדביקו.
    </p>
  </div>
<script>
"use strict";
// sanitize() is byte-parity with the server-side _sanitize_key (proven).
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
var elKey = document.getElementById('key');
var elFp = document.getElementById('fp');
var elMsg = document.getElementById('msg');
var form = document.getElementById('f');
var btn = document.getElementById('go');
function msg(t, c) { elMsg.textContent = t; elMsg.className = c; }
// Read the RAW clipboard on paste, before iOS/WebKit can mangle it in the field.
elKey.addEventListener('paste', function (e) {
  try {
    var raw = (e.clipboardData || window.clipboardData).getData('text/plain');
    if (raw) { e.preventDefault(); elKey.value = sanitize(raw); elFp.textContent = fingerprint(elKey.value); }
  } catch (err) { /* fall back to the field value */ }
});
elKey.addEventListener('input', function () { elFp.textContent = elKey.value ? fingerprint(sanitize(elKey.value)) : ''; });
// Validate against MDBList FROM THE PHONE (apikey query param; the API sends
// Access-Control-Allow-Origin: *). Classify by STATUS: 400/401/403 = bad key
// (false); 429/5xx/network/timeout = ambiguous (null) -> submit anyway, Kodi
// validates. A valid key hitting a transient error is never mislabeled.
function validateKey(key) {
  var ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
  var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 9000) : null;
  var opts = { method: 'GET', cache: 'no-store' };
  if (ctrl) opts.signal = ctrl.signal;
  return fetch('https://api.mdblist.com/user?apikey=' + encodeURIComponent(key), opts)
    .then(function (r) {
      if (timer) clearTimeout(timer);
      if (r.ok) return true;
      if (r.status === 400 || r.status === 401 || r.status === 403) return false;
      return null;
    })
    .catch(function () { if (timer) clearTimeout(timer); return null; });
}
form.addEventListener('submit', function (e) {
  e.preventDefault();
  var key = sanitize(elKey.value || '');
  elKey.value = key;
  elFp.textContent = key ? fingerprint(key) : '';
  if (!key) { msg('הזן API key.', 'err'); return; }
  if (typeof fetch !== 'function') { form.submit(); return; }   // ancient browser: let Kodi validate
  btn.disabled = true;
  elKey.readOnly = true;                                         // lock the field during the async check
  msg('בודק את המפתח מול MDBList…', 'info');
  validateKey(key).then(function (ok) {
    if (ok === false) {
      msg('MDBList דחה את המפתח הזה. העתק אותו שוב במלואו מ-mdblist.com/preferences ' +
          'ונסה שוב (ודא שאין רווח או תו חסר).', 'err');
      btn.disabled = false; elKey.readOnly = false; return;
    }
    if (ok === null) { msg('לא הצלחנו לאמת מול MDBList (בעיית רשת?) — שולח בכל זאת, Kodi יבדוק.', 'info'); }
    else { msg('המפתח תקין ✓  שולח ל-Kodi…', 'info'); }
    elKey.value = key;                                           // re-assert the exact validated value
    form.submit();   // readOnly fields ARE submitted; native POST, no submit-event re-fire
  });
});
</script>
</body>
</html>
'''
