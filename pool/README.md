# Kodi POV IL — community AI-subtitle pool

A tiny Cloudflare Worker that lets the AI subtitle add-on **share** Hebrew AI
translations and **pull** ones other users already made. A Telegram channel is
the file store; Workers KV is a small index. No server to maintain; free tier.

## Architecture
```
AI add-on (each device)
  POST /contribute  (after a translation)   ─┐
  GET  /lookup, /sub (before translating)   ─┤
                                             ▼
        Cloudflare Worker  (worker.js)  ── KV "POOL" (index: media -> variants)
                                             │
                                             ▼  Telegram Bot API (sendDocument / getFile)
                                   Telegram channel @povil_ai_subs (the .srt files)
```

Index key: `v1:<lang>:<tmdb-or-imdb>:s<season>:e<episode>` → list of variants,
one per distinct **source-subtitle content hash** (so a different English source
= a different sync = its own variant; nothing overwrites anything).

## Deploy (Cloudflare dashboard, no CLI)
1. **Workers & Pages → Create → Create Worker** → name e.g. `povil-subs-pool` → Deploy.
2. **Edit code** → paste `worker.js` → **Deploy**.
3. **KV:** Workers & Pages → **KV → Create namespace** named `POOL`. Then in the
   Worker → **Settings → Bindings → add KV Namespace binding**: variable `POOL` → that namespace.
4. **Secrets/vars** (Worker → Settings → Variables):
   - `BOT_TOKEN`  = your BotFather token   *(mark as Secret/encrypt)*
   - `CHANNEL_ID` = `-1004388223186`
   - `API_KEY`    = the shared write key    *(mark as Secret/encrypt)*
   - `UPLOAD_TOKEN` = a separate token for the manual web upload page
     *(mark as Secret/encrypt; only needed if you use `/upload`)*
5. Test: open `https://<worker-url>/health` → `{"ok":true}`.

The add-on is wired with the worker URL + `API_KEY` (read endpoints are open;
only `/contribute` requires the key).

## Manual web upload (for subs made outside the add-on)
`https://<worker-url>/upload` serves a small page where a trusted contributor
can upload a Hebrew `.srt` from their computer:
- It auto-parses season/episode/year from the filename, and resolves the
  movie/series via a **TMDB title search** (or a pasted TMDB/IMDb id).
- It requires the **`UPLOAD_TOKEN`** (entered in the page, sent as
  `x-upload-token`) — share it only with people you trust; revoke by changing
  the secret. The page never exposes `API_KEY`.
- Uploads go through the SAME pipeline as the add-on: deduped by source **and**
  Hebrew-result hash (so manual uploads never create a duplicate), and posted
  to the channel with the rich caption + document.

Endpoints added for this: `GET /upload` (page), `GET /tmdb-search` (token-gated
TMDB proxy), `POST /web-upload` (token-gated, multipart).
