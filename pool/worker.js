// Kodi POV IL — community AI-subtitle pool (Cloudflare Worker)
// ---------------------------------------------------------------------------
// A tiny backend that lets the AI subtitle add-on SHARE Hebrew AI translations
// and PULL ones other users already made, using a Telegram channel as the file
// store and Workers KV as a small index.
//
// Routes:
//   GET  /health
//   GET  /lookup?tmdb=<id>&type=movie|episode&season=&episode=&lang=he
//          -> { ok, key, count, variants:[{hash,release,source_lang,ts}] }
//   GET  /sub?tmdb=<id>&type=&season=&episode=&lang=he[&hash=<source_hash>]
//          -> the .srt bytes (200) or 404. With hash -> that exact variant;
//             without -> the newest variant.
//   POST /contribute   (header X-API-Key: <API_KEY>)
//          body JSON: { tmdb_id, imdb_id, type:"movie"|"episode", season, episode,
//                       lang:"he", release, source_hash, source_lang, title, year,
//                       srt:"<raw utf-8 srt text>" }
//          -> uploads the .srt to the channel, indexes it, dedups by source_hash.
//
// Bindings (set in the Cloudflare dashboard):
//   KV namespace binding:  POOL
//   Secrets / vars:        BOT_TOKEN (secret), CHANNEL_ID, API_KEY (secret)
//
// Identity model: the index key is (lang, tmdb/imdb, season, episode). Each key
// holds a list of VARIANTS, one per distinct source-subtitle content hash, so a
// different English source (= different sync) becomes its own variant and never
// overwrites another. Exact source reuse is a hash match.

const MAX_SRT = 2 * 1024 * 1024;   // 2 MB
const MAX_VARIANTS = 25;

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
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

function looksLikeSrt(text) {
  if (!text || text.length < 30 || text.length > MAX_SRT) return false;
  const cues = (text.match(/-->/g) || []).length;
  return cues >= 3;            // at least a few timecoded cues
}

async function readIndex(env, key) {
  const raw = await env.POOL.get(key);
  if (!raw) return [];
  try { const a = JSON.parse(raw); return Array.isArray(a) ? a : []; }
  catch { return []; }
}

async function uploadSrt(env, filename, srtText, caption) {
  const fd = new FormData();
  fd.append('chat_id', String(env.CHANNEL_ID));
  fd.append('caption', String(caption).slice(0, 1024));
  fd.append('document',
    new Blob([srtText], { type: 'application/x-subrip' }), filename);
  const r = await fetch(tg(env.BOT_TOKEN, 'sendDocument'), { method: 'POST', body: fd });
  const data = await r.json();
  if (!data.ok) throw new Error('sendDocument: ' + JSON.stringify(data).slice(0, 300));
  return data.result && data.result.document && data.result.document.file_id;
}

async function downloadById(env, fileId) {
  const gf = await fetch(tg(env.BOT_TOKEN, 'getFile') + '?file_id=' + encodeURIComponent(fileId));
  const gd = await gf.json();
  if (!gd.ok || !gd.result || !gd.result.file_path) return null;
  const fr = await fetch(`https://api.telegram.org/file/bot${env.BOT_TOKEN}/${gd.result.file_path}`);
  if (!fr.ok) return null;
  return await fr.text();
}

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
        variants: variants.map(v => ({
          hash: v.hash, release: v.release, source_lang: v.source_lang, ts: v.ts,
        })),
      });
    }

    if (path === '/sub' && request.method === 'GET') {
      const p = Object.fromEntries(url.searchParams);
      const variants = await readIndex(env, keyFor(p));
      if (!variants.length) return new Response('not found', { status: 404 });
      const want = (p.hash || '').trim();
      let v = want ? variants.find(x => x.hash === want) : null;
      if (!v) v = variants[variants.length - 1];   // newest as fallback
      const srt = await downloadById(env, v.file_id);
      if (!srt) return new Response('fetch failed', { status: 502 });
      return new Response(srt, {
        headers: { 'content-type': 'application/x-subrip; charset=utf-8' },
      });
    }

    if (path === '/contribute' && request.method === 'POST') {
      if (request.headers.get('x-api-key') !== env.API_KEY)
        return json({ ok: false, error: 'unauthorized' }, 401);
      let body;
      try { body = await request.json(); } catch { return json({ ok: false, error: 'bad json' }, 400); }

      const lang = (body.lang || 'he').toLowerCase();
      if (lang !== 'he') return json({ ok: false, error: 'only he supported' }, 400);
      const srt = body.srt || '';
      if (!looksLikeSrt(srt)) return json({ ok: false, error: 'invalid srt' }, 400);
      const id = String(body.tmdb_id || body.imdb_id || '').trim();
      if (!id) return json({ ok: false, error: 'no id' }, 400);

      const key = keyFor({
        lang, tmdb: body.tmdb_id, imdb: body.imdb_id,
        type: body.type, season: body.season, episode: body.episode,
      });
      const hash = (body.source_hash || '').trim();
      const variants = await readIndex(env, key);
      if (hash && variants.some(v => v.hash === hash))
        return json({ ok: true, dedup: true, key });
      if (variants.length >= MAX_VARIANTS)
        return json({ ok: false, error: 'too many variants' }, 429);

      const rel = (body.release || '').replace(/[^A-Za-z0-9._-]/g, '').slice(0, 80) || ('tmdb' + id);
      const filename = `${rel}.he.srt`;
      const caption = [
        (body.title || '').slice(0, 120),
        body.type === 'episode' ? `S${body.season}E${body.episode}` : (body.year || ''),
        `tmdb:${id}`,
        `src:${body.source_lang || '?'}`,
        '#AI #he',
      ].filter(Boolean).join(' · ');

      let fileId;
      try { fileId = await uploadSrt(env, filename, srt, caption); }
      catch (e) { return json({ ok: false, error: String(e).slice(0, 200) }, 502); }
      if (!fileId) return json({ ok: false, error: 'no file_id' }, 502);

      variants.push({
        hash, release: body.release || '', source_lang: body.source_lang || '',
        file_id: fileId, ts: Date.now(),
      });
      await env.POOL.put(key, JSON.stringify(variants));
      return json({ ok: true, stored: true, key });
    }

    return new Response('Kodi POV IL — AI subtitle pool', { status: 200 });
  },
};
