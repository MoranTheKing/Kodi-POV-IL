// Kodi POV IL — community AI-subtitle pool (Cloudflare Worker)
// ---------------------------------------------------------------------------
// Shares/pulls Hebrew AI translations. Telegram channel = file store, Workers
// KV = small index. Posts are formatted like a subtitle-release channel:
// poster + title + genre hashtags + season/episode + IMDb|TMDb + plot, then the
// .srt document.
//
// Routes:
//   GET  /health
//   GET  /lookup?tmdb=<id>&type=movie|episode&season=&episode=&lang=he
//   GET  /sub?tmdb=<id>&type=&season=&episode=&lang=he[&hash=<source_hash>]
//   POST /contribute  (X-API-Key)  body JSON {tmdb_id,imdb_id,type,season,episode,
//                       lang:"he",release,source_hash,source_lang,title,year,srt}
//
// Bindings: KV "POOL"; secrets BOT_TOKEN, CHANNEL_ID, API_KEY; optional TMDB_KEY.

const MAX_SRT = 2 * 1024 * 1024;
const MAX_VARIANTS = 25;
// Public TMDB v3 key bundled in jurialmunkey's tmdbhelper (same one the add-on
// uses). Override per-deployment by setting a TMDB_KEY variable.
const BUNDLED_TMDB_KEY = 'a07324c669cac4d96789197134ce272b';

const tg = (token, method) => `https://api.telegram.org/bot${token}/${method}`;

function keyFor(p) {
  const lang = (p.lang || 'he').toLowerCase();
  const id = String(p.tmdb || p.imdb || '').trim();
  const s = String(p.season || '0').trim() || '0';
  const e = String(p.episode || '0').trim() || '0';
  return `v1:${lang}:${id}:s${s}:e${e}`;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status, headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

function looksLikeSrt(text) {
  if (!text || text.length < 30 || text.length > MAX_SRT) return false;
  return (text.match(/-->/g) || []).length >= 3;
}

// sha1 hex of a string (Web Crypto). Used to dedup by the Hebrew RESULT, so two
// byte-identical translations never get stored twice even when one has no
// source hash (e.g. a bulk "share my cache" upload).
async function sha1hex(text) {
  const buf = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(text || ''));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function hashtag(s) {
  const t = String(s).trim().replace(/[\s\-]+/g, '_').replace(/[^\wא-ת]/g, '');
  return t ? '#' + t : '';
}

async function readIndex(env, key) {
  const raw = await env.POOL.get(key);
  if (!raw) return [];
  try { const a = JSON.parse(raw); return Array.isArray(a) ? a : []; }
  catch { return []; }
}

async function tmdbMeta(env, body) {
  const key = env.TMDB_KEY || BUNDLED_TMDB_KEY;
  const id = String(body.tmdb_id || '').trim();
  if (!/^\d+$/.test(id)) return {};
  const isEp = body.type === 'episode';
  const base = isEp ? 'tv' : 'movie';
  try {
    const r = await fetch(`https://api.themoviedb.org/3/${base}/${id}` +
      `?api_key=${key}&language=he&append_to_response=external_ids`);
    if (!r.ok) return {};
    const d = await r.json();
    const meta = {
      title: d.title || d.name || body.title || '',
      original_title: d.original_title || d.original_name || '',
      year: String(d.release_date || d.first_air_date || '').slice(0, 4) || body.year || '',
      overview: d.overview || '',
      poster_url: d.poster_path ? `https://image.tmdb.org/t/p/w500${d.poster_path}` : '',
      genres: (d.genres || []).map(g => g.name),
      imdb_id: (d.external_ids && d.external_ids.imdb_id) || d.imdb_id || body.imdb_id || '',
    };
    if (isEp && body.season && body.episode) {
      try {
        const er = await fetch(`https://api.themoviedb.org/3/tv/${id}/season/` +
          `${body.season}/episode/${body.episode}?api_key=${key}&language=he`);
        if (er.ok) {
          const ed = await er.json();
          if (ed.overview) meta.overview = ed.overview;
          if (ed.name) meta.ep_name = ed.name;
        }
      } catch (_) { /* ignore */ }
    }
    return meta;
  } catch (_) { return {}; }
}

// A real subtitle release name carries a year and/or a quality/source token
// (1080p, BluRay, x265, ...). The client's `release` can also be a tokenized
// stream/temp basename with none of those -- we reject those and fall back to
// the TMDB title so the Telegram filename stays meaningful.
function looksLikeRelease(s) {
  if (!s || s.length < 5) return false;
  if (/(?:^|[^0-9])(?:19|20)\d{2}(?:[^0-9]|$)/.test(s)) return true;
  if (/\b(2160p|1080p|720p|480p|bluray|blu-ray|webrip|web-dl|webdl|web|hdtv|brrip|bdrip|dvdrip|hdrip|x264|x265|h264|h265|hevc|xvid|aac|ac3|dts)\b/i.test(s)) return true;
  return false;
}

// Build a clean, human-readable .srt filename. Prefer a real release name (it
// tells you which video version the subtitle is synced to); otherwise use the
// English/original TMDB title + year (+ SxxEyy for episodes); fall back to the
// id. Cosmetic only -- the pool is indexed by id/season/episode, not the name.
function cleanFilename(body, meta) {
  const isEp = body.type === 'episode';
  const id = String(body.tmdb_id || body.imdb_id || '').trim();
  const rel = String(body.release || '')
    .replace(/[^A-Za-z0-9._-]/g, '.').replace(/\.{2,}/g, '.')
    .replace(/^\.+|\.+$/g, '').slice(0, 80);
  if (looksLikeRelease(rel)) return rel + '.he.srt';
  let base = (meta.original_title || meta.title || body.title || '')
    .replace(/[^A-Za-z0-9]+/g, '.').replace(/^\.+|\.+$/g, '').slice(0, 60);
  if (!base) base = (isEp ? 'tv' : 'movie') + (id || '');
  if (!isEp && meta.year) base += '.' + meta.year;
  if (isEp) {
    const pad = (n) => String(parseInt(n, 10) || 0).padStart(2, '0');
    base += `.S${pad(body.season)}E${pad(body.episode)}`;
  }
  return base + '.he.srt';
}

function buildCaption(body, meta) {
  const isEp = body.type === 'episode';
  const title = meta.title || body.title || 'Unknown';
  const lines = [];
  let head = `${isEp ? '📺' : '🎬'} <b>${escapeHtml(title)}</b>`;
  if (!isEp && meta.year) head += ` (${meta.year})`;
  lines.push(head);
  if (isEp) {
    lines.push(`עונה ${body.season} · פרק ${body.episode}` +
      (meta.ep_name ? ` — ${escapeHtml(meta.ep_name)}` : ''));
  }
  const tags = (meta.genres || []).slice(0, 5).map(hashtag).filter(Boolean);
  if (tags.length) lines.push(tags.join(' '));
  const links = [];
  if (meta.imdb_id) links.push(`<a href="https://www.imdb.com/title/${meta.imdb_id}/">IMDb</a>`);
  const tid = String(body.tmdb_id || '').trim();
  if (tid) links.push(`<a href="https://www.themoviedb.org/${isEp ? 'tv' : 'movie'}/${tid}">TMDb</a>`);
  if (links.length) lines.push(links.join(' | '));
  if (meta.overview) { lines.push(''); lines.push(escapeHtml(meta.overview.slice(0, 500))); }
  lines.push('');
  lines.push('🤖 תרגום AI · #כתוביות_AI #עברית');
  let cap = lines.join('\n');
  if (cap.length > 1024) cap = cap.slice(0, 1020) + '…';
  return cap;
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

// Telegram rate-limits a bot per token / per chat (~20 msgs/min to a channel).
// On 429 it returns parameters.retry_after seconds. Do ONE bounded retry that
// honours retry_after (capped, so we never blow the Worker's request budget);
// if it's still throttled, the caller treats it as a failure and the client
// retries later. doFetch is a thunk so the request body (FormData) is rebuilt
// fresh for the retry.
async function tgRetry(doFetch) {
  let r = await doFetch();
  if (r.status === 429) {
    let wait = 2;
    try {
      const j = await r.clone().json();
      wait = (j.parameters && j.parameters.retry_after) || 2;
    } catch (_) { /* keep default */ }
    if (wait <= 12) { await sleep(wait * 1000 + 300); r = await doFetch(); }
  }
  return r;
}

async function sendPhoto(env, photoUrl, caption) {
  try {
    const r = await tgRetry(() => fetch(tg(env.BOT_TOKEN, 'sendPhoto'), {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ chat_id: String(env.CHANNEL_ID), photo: photoUrl, caption, parse_mode: 'HTML' }),
    }));
    return (await r.json()).ok;
  } catch (_) { return false; }
}

async function uploadSrt(env, filename, srtText, caption, parseMode) {
  const buildFd = () => {
    const fd = new FormData();
    fd.append('chat_id', String(env.CHANNEL_ID));
    if (caption) fd.append('caption', String(caption).slice(0, 1024));
    if (parseMode) fd.append('parse_mode', parseMode);
    fd.append('document', new Blob([srtText], { type: 'application/x-subrip' }), filename);
    return fd;
  };
  const r = await tgRetry(() => fetch(tg(env.BOT_TOKEN, 'sendDocument'), { method: 'POST', body: buildFd() }));
  const data = await r.json();
  if (!data.ok) throw new Error('sendDocument: ' + JSON.stringify(data).slice(0, 300));
  return data.result && data.result.document && data.result.document.file_id;
}

// Edge-cached fetch of a stored SRT by its (immutable) Telegram file_id. The
// first pull downloads from Telegram and stores the bytes in Cloudflare's edge
// cache; subsequent pulls are served from the edge and never touch the Telegram
// getFile API -- which keeps many concurrent /sub requests off the bot's rate
// limit and makes pulls much faster.
async function downloadById(env, fileId) {
  const cache = caches.default;
  const cacheKey = new Request('https://pool-file-cache/' + encodeURIComponent(fileId));
  try {
    const hit = await cache.match(cacheKey);
    if (hit) return await hit.text();
  } catch (_) { /* fall through to live fetch */ }

  const gf = await tgRetry(() => fetch(tg(env.BOT_TOKEN, 'getFile') + '?file_id=' + encodeURIComponent(fileId)));
  const gd = await gf.json();
  if (!gd.ok || !gd.result || !gd.result.file_path) return null;
  const fr = await fetch(`https://api.telegram.org/file/bot${env.BOT_TOKEN}/${gd.result.file_path}`);
  if (!fr.ok) return null;
  const text = await fr.text();
  try {
    await cache.put(cacheKey, new Response(text, {
      headers: {
        'content-type': 'application/x-subrip; charset=utf-8',
        'cache-control': 'public, max-age=2592000',
      },
    }));
  } catch (_) { /* caching is best-effort */ }
  return text;
}

// Shared contribution pipeline: validate, dedup (source + Hebrew-result hash,
// with lazy backfill), post the rich message + document to the channel, and
// index the variant. Used by both /contribute (add-on, X-API-Key) and
// /web-upload (manual web page, X-Upload-Token). Returns a json() Response.
async function contributeCore(env, body) {
  const lang = (body.lang || 'he').toLowerCase();
  if (lang !== 'he') return json({ ok: false, error: 'only he supported' }, 400);
  const srt = body.srt || '';
  if (!looksLikeSrt(srt)) return json({ ok: false, error: 'invalid srt' }, 400);
  const id = String(body.tmdb_id || body.imdb_id || '').trim();
  if (!id) return json({ ok: false, error: 'no id' }, 400);

  const key = keyFor({ lang, tmdb: body.tmdb_id, imdb: body.imdb_id, type: body.type, season: body.season, episode: body.episode });
  const hash = (body.source_hash || '').trim();
  const variants = await readIndex(env, key);

  // Dedup layer 1: same SOURCE hash already present (cheap, no downloads).
  if (hash && variants.some(v => v.hash === hash)) return json({ ok: true, dedup: true, key });

  // Dedup layer 2: same RESULT (Hebrew) already present. Catches uploads with
  // no source hash (bulk "share my cache", manual web upload) and prevents two
  // byte-identical Hebrew files coexisting. Old variants stored before this
  // layer have no result_hash, so backfill it lazily (download + hash, write
  // back) -- bounded by MAX_VARIANTS and only on this path.
  const resultHash = await sha1hex(srt);
  let indexDirty = false;
  for (const v of variants) {
    if (!v.result_hash) {
      try {
        const existing = await downloadById(env, v.file_id);
        if (existing) { v.result_hash = await sha1hex(existing); indexDirty = true; }
      } catch (_) { /* leave it; just won't dedup by result for this one */ }
    }
  }
  if (variants.some(v => v.result_hash === resultHash)) {
    if (indexDirty) await env.POOL.put(key, JSON.stringify(variants));
    return json({ ok: true, dedup: true, key });
  }

  if (variants.length >= MAX_VARIANTS) {
    if (indexDirty) await env.POOL.put(key, JSON.stringify(variants));
    return json({ ok: false, error: 'too many variants' }, 429);
  }

  const meta = await tmdbMeta(env, body);
  const filename = cleanFilename(body, meta);
  const caption = buildCaption(body, meta);

  let fileId;
  try {
    if (meta.poster_url) {
      await sendPhoto(env, meta.poster_url, caption);
      fileId = await uploadSrt(env, filename, srt, `📄 <code>${escapeHtml(filename)}</code>`, 'HTML');
    } else {
      fileId = await uploadSrt(env, filename, srt, caption, 'HTML');
    }
  } catch (e) { return json({ ok: false, error: String(e).slice(0, 200) }, 502); }
  if (!fileId) return json({ ok: false, error: 'no file_id' }, 502);

  variants.push({ hash, result_hash: resultHash, release: body.release || '', source_lang: body.source_lang || '', file_id: fileId, ts: Date.now() });
  await env.POOL.put(key, JSON.stringify(variants));
  return json({ ok: true, stored: true, key });
}

// Manual-upload auth: a token separate from the add-on's API_KEY, so it can be
// shared with trusted contributors (and revoked) without exposing the add-on
// key. Set UPLOAD_TOKEN as a Worker secret.
function checkUploadToken(env, token) {
  return !!env.UPLOAD_TOKEN && String(token || '') === String(env.UPLOAD_TOKEN);
}

// Proxy a TMDB title search (so the upload page can resolve a name -> id
// without ever exposing the TMDB key to the browser).
async function tmdbSearch(env, query) {
  const key = env.TMDB_KEY || BUNDLED_TMDB_KEY;
  const q = (query || '').trim();
  if (!q) return [];
  try {
    const r = await fetch('https://api.themoviedb.org/3/search/multi?api_key=' +
      key + '&language=he&query=' + encodeURIComponent(q));
    if (!r.ok) return [];
    const d = await r.json();
    return (d.results || [])
      .filter(x => x.media_type === 'movie' || x.media_type === 'tv')
      .slice(0, 12)
      .map(x => ({
        id: x.id,
        type: x.media_type === 'tv' ? 'episode' : 'movie',
        title: x.title || x.name || '',
        year: String(x.release_date || x.first_air_date || '').slice(0, 4),
        poster: x.poster_path ? ('https://image.tmdb.org/t/p/w92' + x.poster_path) : '',
      }));
  } catch (_) { return []; }
}

const UPLOAD_HTML = `<!doctype html>
<html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>העלאת כתובית למאגר POV IL</title>
<style>
:root{color-scheme:dark}
body{font-family:system-ui,Arial,sans-serif;max-width:640px;margin:0 auto;padding:18px;background:#15171c;color:#e8eaed}
h1{font-size:20px;margin:0 0 6px}
.sub{color:#9aa0a6;font-size:13px;margin:0 0 18px}
label{display:block;margin:10px 0 4px;font-size:14px;color:#c8ccd0}
input,select,button{font-size:15px;padding:9px;border-radius:8px;border:1px solid #333;background:#1f232b;color:#e8eaed;box-sizing:border-box}
input,select{width:100%}
fieldset{border:1px solid #2a2f38;border-radius:10px;margin:14px 0;padding:12px}
legend{color:#9aa0a6;font-size:13px;padding:0 6px}
.row{display:flex;gap:10px}.row>div{flex:1}
button{cursor:pointer;background:#3b6;border-color:#3b6;color:#08140c;font-weight:600}
button.sec{background:#2a2f38;border-color:#3a4150;color:#e8eaed;font-weight:500}
#results{margin-top:8px;display:grid;gap:6px}
.res{display:flex;gap:8px;align-items:center;padding:6px;border:1px solid #2a2f38;border-radius:8px;cursor:pointer;background:#1b1f27}
.res:hover{border-color:#3b6}
.res img{width:38px;height:auto;border-radius:4px;background:#333}
.res small{color:#9aa0a6}
#status{margin-top:14px;padding:10px;border-radius:8px;font-size:14px;white-space:pre-wrap;display:none}
.ok{background:#16361f;border:1px solid #2c6}.err{background:#3a1c1c;border:1px solid #c55}
#submitBtn{width:100%;margin-top:16px;padding:12px}
</style></head><body>
<h1>העלאת כתובית עברית למאגר הקהילתי</h1>
<p class="sub">לתרגומים שעשית מחוץ לתוסף. בחר קובץ SRT, זהה את הסרט/פרק, ושלח. כפילויות נמנעות אוטומטית.</p>

<label for="token">טוקן מעלה</label>
<input id="token" placeholder="הדבק כאן את הטוקן שקיבלת" autocomplete="off">

<label for="file">קובץ כתובית (.srt)</label>
<input type="file" id="file" accept=".srt,.txt">

<fieldset>
<legend>זיהוי הסרט / הסדרה</legend>
<div class="row"><div><input id="q" placeholder="חיפוש לפי שם..."></div><div style="flex:0 0 90px"><button class="sec" id="searchBtn" type="button">חפש</button></div></div>
<div id="results"></div>
<div class="row" style="margin-top:8px">
<div><label for="tmdb_id">TMDB id</label><input id="tmdb_id" inputmode="numeric"></div>
<div><label for="imdb_id">IMDb id</label><input id="imdb_id" placeholder="tt..."></div>
</div>
</fieldset>

<div class="row">
<div><label for="type">סוג</label><select id="type"><option value="movie">סרט</option><option value="episode">פרק</option></select></div>
<div><label for="year">שנה</label><input id="year" inputmode="numeric"></div>
</div>
<div class="row" id="eprow" style="display:none">
<div><label for="season">עונה</label><input id="season" value="0" inputmode="numeric"></div>
<div><label for="episode">פרק</label><input id="episode" value="0" inputmode="numeric"></div>
</div>
<label for="title">כותרת (לתצוגה בערוץ)</label><input id="title">
<label for="source_lang">שפת מקור התרגום</label><input id="source_lang" value="en">

<button id="submitBtn" type="button">העלה למאגר</button>
<div id="status"></div>

<script>
var $=function(id){return document.getElementById(id)};
function showStatus(msg,ok){var s=$('status');s.textContent=msg;s.className=ok?'ok':'err';s.style.display='block'}
function syncEpRow(){$('eprow').style.display=$('type').value==='episode'?'flex':'none'}
$('type').addEventListener('change',syncEpRow);
try{var t=localStorage.getItem('povil_upload_token');if(t)$('token').value=t}catch(e){}
$('token').addEventListener('change',function(){try{localStorage.setItem('povil_upload_token',$('token').value.trim())}catch(e){}});

var lastFileName='';
$('file').addEventListener('change',function(){
  var f=this.files&&this.files[0];if(!f)return;lastFileName=f.name;
  var base=f.name.replace(/\\.[^.]+$/,'');
  var m=base.match(/S(\\d{1,2})[._\\s-]?E(\\d{1,2})/i)||base.match(/(\\d{1,2})x(\\d{1,2})/i);
  if(m){$('type').value='episode';$('season').value=String(parseInt(m[1],10));$('episode').value=String(parseInt(m[2],10))}
  var y=base.match(/(19|20)\\d{2}/);if(y)$('year').value=y[0];
  var cut=base.search(/[._\\s-](?:S\\d{1,2}[._\\s-]?E\\d{1,2}|\\d{1,2}x\\d{1,2}|(?:19|20)\\d{2}|2160p|1080p|720p|480p|web|bluray|brrip|bdrip|x264|x265|hevc)/i);
  var guess=(cut>0?base.slice(0,cut):base).replace(/[._]+/g,' ').trim();
  if(guess){if(!$('title').value)$('title').value=guess;$('q').value=guess}
  syncEpRow();
});

$('searchBtn').addEventListener('click',function(){
  var token=$('token').value.trim();if(!token){showStatus('צריך טוקן מעלה.',false);return}
  var q=$('q').value.trim();if(!q){showStatus('הקלד שם לחיפוש.',false);return}
  $('results').innerHTML='מחפש...';
  fetch('/tmdb-search?token='+encodeURIComponent(token)+'&q='+encodeURIComponent(q))
   .then(function(r){return r.json()}).then(function(d){
     if(!d.ok){$('results').innerHTML='';showStatus('חיפוש נכשל (טוקן שגוי?).',false);return}
     var R=$('results');R.innerHTML='';
     if(!d.results.length){R.textContent='לא נמצאו תוצאות.';return}
     d.results.forEach(function(it){
       var div=document.createElement('div');div.className='res';
       div.innerHTML=(it.poster?'<img src="'+it.poster+'">':'<img>')+'<div><b>'+it.title+'</b> <small>'+(it.year||'')+' · '+(it.type==='episode'?'סדרה':'סרט')+'</small></div>';
       div.addEventListener('click',function(){
         $('tmdb_id').value=it.id;$('imdb_id').value='';$('type').value=it.type;
         if(it.title)$('title').value=it.title;if(it.year)$('year').value=it.year;
         syncEpRow();showStatus('נבחר: '+it.title+' ('+it.year+')',true);
       });
       R.appendChild(div);
     });
   }).catch(function(){$('results').innerHTML='';showStatus('שגיאת רשת בחיפוש.',false)});
});

$('submitBtn').addEventListener('click',function(){
  var token=$('token').value.trim();if(!token){showStatus('צריך טוקן מעלה.',false);return}
  var f=$('file').files&&$('file').files[0];if(!f){showStatus('בחר קובץ SRT.',false);return}
  if(!$('tmdb_id').value.trim()&&!$('imdb_id').value.trim()){showStatus('זהה את הסרט/הסדרה (חיפוש או id).',false);return}
  var fd=new FormData();
  fd.append('srt',f,f.name);
  fd.append('release',lastFileName.replace(/\\.[^.]+$/,''));
  fd.append('tmdb_id',$('tmdb_id').value.trim());
  fd.append('imdb_id',$('imdb_id').value.trim());
  fd.append('type',$('type').value);
  fd.append('season',$('season').value.trim()||'0');
  fd.append('episode',$('episode').value.trim()||'0');
  fd.append('title',$('title').value.trim());
  fd.append('year',$('year').value.trim());
  fd.append('source_lang',$('source_lang').value.trim()||'en');
  $('submitBtn').disabled=true;showStatus('מעלה...',true);
  fetch('/web-upload',{method:'POST',headers:{'x-upload-token':token},body:fd})
   .then(function(r){return r.json()}).then(function(d){
     $('submitBtn').disabled=false;
     if(d.ok&&d.dedup)showStatus('כבר קיים במאגר — לא נוצרה כפילות. ✔',true);
     else if(d.ok)showStatus('הועלה למאגר בהצלחה! ✔',true);
     else showStatus('שגיאה: '+(d.error||'לא ידוע'),false);
   }).catch(function(){$('submitBtn').disabled=false;showStatus('שגיאת רשת בהעלאה.',false)});
});
syncEpRow();
</script></body></html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    if (path === '/health') return json({ ok: true });

    if (path === '/lookup' && request.method === 'GET') {
      const p = Object.fromEntries(url.searchParams);
      const key = keyFor(p);
      const variants = await readIndex(env, key);
      return json({
        ok: true, key, count: variants.length,
        variants: variants.map(v => ({ hash: v.hash, release: v.release, source_lang: v.source_lang, ts: v.ts })),
      });
    }

    if (path === '/sub' && request.method === 'GET') {
      const p = Object.fromEntries(url.searchParams);
      const variants = await readIndex(env, keyFor(p));
      if (!variants.length) return new Response('not found', { status: 404 });
      const want = (p.hash || '').trim();
      let v = want ? variants.find(x => x.hash === want) : null;
      if (!v) { if (want) return new Response('not found', { status: 404 }); v = variants[variants.length - 1]; }
      const srt = await downloadById(env, v.file_id);
      if (!srt) return new Response('fetch failed', { status: 502 });
      return new Response(srt, { headers: { 'content-type': 'application/x-subrip; charset=utf-8' } });
    }

    if (path === '/contribute' && request.method === 'POST') {
      if (request.headers.get('x-api-key') !== env.API_KEY)
        return json({ ok: false, error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ ok: false, error: 'bad json' }, 400); }
      return await contributeCore(env, body);
    }

    // Manual web upload (for translations made outside the add-on).
    if (path === '/upload' && request.method === 'GET') {
      return new Response(UPLOAD_HTML, {
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    if (path === '/tmdb-search' && request.method === 'GET') {
      if (!checkUploadToken(env, url.searchParams.get('token')))
        return json({ ok: false, error: 'unauthorized' }, 401);
      return json({ ok: true, results: await tmdbSearch(env, url.searchParams.get('q')) });
    }

    if (path === '/web-upload' && request.method === 'POST') {
      if (!checkUploadToken(env, request.headers.get('x-upload-token')))
        return json({ ok: false, error: 'unauthorized' }, 401);
      let form;
      try { form = await request.formData(); } catch { return json({ ok: false, error: 'bad form' }, 400); }
      const file = form.get('srt');
      let srt = '';
      try { srt = (file && typeof file.text === 'function') ? await file.text() : String(file || ''); } catch (_) {}
      const body = {
        tmdb_id: String(form.get('tmdb_id') || '').trim(),
        imdb_id: String(form.get('imdb_id') || '').trim(),
        type: String(form.get('type') || 'movie'),
        season: String(form.get('season') || '0'),
        episode: String(form.get('episode') || '0'),
        lang: 'he',
        release: String(form.get('release') || '').trim(),
        source_hash: '',
        source_lang: String(form.get('source_lang') || 'en'),
        title: String(form.get('title') || '').trim(),
        year: String(form.get('year') || '').trim(),
        srt: srt,
      };
      return await contributeCore(env, body);
    }

    return new Response('Kodi POV IL — AI subtitle pool', { status: 200 });
  },
};
