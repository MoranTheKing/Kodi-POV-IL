# Kodi POV IL — community AI-subtitle pool

> **Historical public reference only.** `pool/worker.js` is a frozen, sanitized,
> stale snapshot. It is not the source of the deployed Worker and must not be
> pasted or deployed. The current Worker, its configuration, and its deployment
> workflow are maintained out-of-band in the maintainer's local-only handoff and
> must never be committed here.

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

## Deployment

There is deliberately no valid deployment procedure in the public repository.
Do not infer the current bindings, storage layer, secrets, or routes from this
historical snapshot. Use only the maintainer's local-only Worker source and
handoff when operating the real service.

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

## Current client-side request safeguards

The public Worker file above remains historical, but the current add-on client
has request-safe behavior that is part of the public source:

- A subtitle fetched from the pool is cached locally by its content hash after
  the first `/sub` response. Display-only RTL repair is applied to a separate
  local copy, so future playback neither re-fetches the provider source nor
  rewrites the pooled object.
- Existing pooled Ktuvit releases are checked through the already-cached
  `/lookup` result before contribution. An exact release match suppresses the
  redundant `/contribute` request.
- Previously stored subtitles are not mass-downloaded or re-uploaded for
  punctuation migrations. New pristine provider sources are tagged in the
  client metadata so legacy display repair is used only where required.
