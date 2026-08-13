# Kodi RD IL POV Fentastic Migration

מטרת הריפו הזה היא להכין גרסת `POV` עם `FENtastic` וכל ההגדרות הרלוונטיות, בהתבסס על הריפו הציבורי:

- `https://github.com/kodi7rd/kodi7rd.github.io`

## מה אומת עד כה

- בבילד `Twillight` קיימים:
  - `addons/skin.fentastic`
  - `addons/script.fentastic.helper`
  - `userdata/addon_data/skin.fentastic/settings.xml`
- בבילד `POV` קיים כרגע `Estuary` כסקין הפעיל.
- `POV` כן כולל `Torbox`:
  - `tb.enabled=true`
  - `tb.torrent.enabled=true`
  - `provider.tb_cloud`
  - `provider.torboxnews`
  - `store_torrent.torbox`
  - `store_usenet.torbox`
- מנגנון החלפת הסקין בבילד המקורי אינו "סקין ברירת מחדל", אלא חוויית החלפה דרך הוויזארד/הבילד.

## כיוון העבודה

1. להעתיק ל־`POV` את רכיבי `FENtastic` עצמם.
2. להתאים את הגדרות `FENtastic` לנתיבי `POV` במקום `Twilight`.
3. לתרגם favourites, קיצורים ו־widgets מ־`plugin.video.twilight` ל־`plugin.video.pov`.
4. לשמור אפשרות החלפה נוחה בין `Estuary` ל־`FENtastic`.
5. להכין חבילת בדיקה להתקנה בטלפון.

## מגבלות כרגע

- הריפו המקורי ציבורי אך אין כאן הרשאת כתיבה אליו.
- אין כרגע כלי זמין ליצירת ריפו GitHub חדש ישירות מתוך הסשן הזה.
- לכן שלב ראשון הוא להכין עותק עבודה מקומי מלא, ואז לפרסם אותו לריפו חדש כשיהיה יעד.

## תוצרים מתוכננים

- עץ קבצים מסודר של המיגרציה.
- מסמך diff של `Twilight -> POV`.
- חבילת בדיקה ל־Kodi: `dist/Kodi-POV-IL-FENtastic-test-0.1.105.zip`.
- הוראות התקנה ובדיקת smoke test לטלפון: `ANDROID_TESTING.md`.

## חבילת בדיקה (גרסה נוכחית)

החבילה מבוססת על `build21_kodirdil_pov-1.0.0.zip` ומוסיפה:

- `addons/skin.fentastic`
- `addons/script.fentastic.helper`
- `userdata/addon_data/skin.fentastic/settings.xml`
- הפעלה של `skin.fentastic` כברירת מחדל ב־`userdata/guisettings.xml`
- favourites מותאמים ל־`POV`, כולל כפתור `TorBox`
- רישום `skin.fentastic` ו־`script.fentastic.helper` כמופעלים ב־`userdata/Database/Addons33.db`

בוצעה התאמה של הפניות פנימיות מ־`plugin.video.twilight` ל־`plugin.video.pov`.
## Easy install via Wizard

For phone testing, install this Kodi add-on zip first:

`dist/plugin.program.kodipovilwizard-latest.zip`

After installing it in Kodi, open:

`Add-ons -> Program add-ons -> Kodi POV IL Wizard -> Builds -> Kodi POV IL - FENtastic`

The wizard reads build metadata from:

`wizard/assets/build.txt`

## Kodi File Source

After GitHub Pages deploys, add this source in Kodi:

`https://morantheking.github.io/Kodi-POV-IL/wizard/`

Then open:

`Settings -> File manager -> Add source -> Install from zip file -> Kodi POV IL -> plugin.program.kodipovilwizard-X.X.X.zip`

## Updates

The wizard checks `wizard/assets/build.txt` every Kodi startup.

Quick updates are controlled by:

`wizard/assets/notification_files/quick_update.txt`

When the quick update number increases, installed builds receive the `gui` package automatically on next Kodi startup.

## Update delivery (from wizard `0.1.42`)

A quick update no longer closes Kodi. The wizard applies it in place by cycling
the add-ons that hold a reused Python interpreter, waits for the service to
report a finished repair pass, and reloads the skin. Nothing is applied while
something is playing -- the update stays on disk and takes effect at the next
start, and the notification says so rather than claiming it was applied. If any
part does not take, it falls back to the previous behaviour (a restart), and an
add-on left switched off is recorded on disk and switched back on at the next
start.

## The skin refresh waits for POV (from `0.2.491`)

A quick update does two things that used to be able to collide: it refreshes
the skin, and it restarts the main video add-on so the update takes effect
straight away. When both happened at the same moment the home screen was
rebuilt while that add-on could not be loaded, every row backed by it failed,
and Kodi had to be closed.

Every refresh on the update path now waits for the add-on to be ready first --
on every skin. If it is not ready in time the refresh is left for the next
start rather than forced through, and the notification says the update applies
next time instead of claiming it was applied. A refresh that is postponed is
not recorded as done, so the next start does it.

## The last ten updates, on the home screen (from `0.2.491`)

The ten most recent update notes are readable from a tile on the home screen,
newest first. The list is never longer than ten, so it stays quick to open.

Removing the tile is respected: it does not come back at the next update or the
next start. Switching skin rewrites the home tiles from the skin's own defaults
-- if that removes the tile without you asking, it is restored; if you removed
it yourself, it stays removed.

## Add-ons you switched off stay off (from `0.2.491`)

The build repairs a main add-on left disabled by an update that was interrupted
-- a device switched off mid-update, for example. It now does that only when
there is a record showing the build itself disabled it and could not switch it
back on. An add-on you turned off yourself is left alone.

## POV self-update and its caches (from `0.2.489`)

POV updates itself from its author's repository, and its newer versions changed
the column order of their own cache tables while keeping `CREATE TABLE IF NOT
EXISTS`. On a device that already had the previous version, the old table
survives and the new code writes every value into the wrong column -- which
shows up as search errors and empty "new"/"popular" rows.

The build repairs this on startup: the affected cache tables are rebuilt in the
order POV's own source declares, in one transaction, keeping every row that is
still readable. Only caches are touched -- watched status, resume points, views
and the navigator lists are out of scope by rule. Favourites saved before the
change are copied into the table the newer POV reads, and the original file is
left untouched.

## Subtitle display and community-pool behavior

From MoranSubs `0.2.443` / quickfix `0.1.485`:

- Hebrew subtitle punctuation is repaired on a local playback copy. The
  downloaded or pooled source file remains unchanged.
- Existing pooled subtitles are not downloaded from providers again and are
  not uploaded again just to repair their display. After the first pool fetch,
  the source is cached locally by its content hash.
- The managed-build default is white subtitle text with a black outline around
  the letters, without a black rectangle. Existing users who customized their
  subtitle style keep their settings.
- The correction is global Kodi subtitle presentation, so it is not tied to a
  particular skin or player.

## Subtitle timing integrity

From MoranSubs `0.2.444` / quickfix `0.1.486`:

- Translated subtitles keep the timings of the subtitle they were translated
  from. The AI is sent whole entries including their timecodes and is asked to
  copy them unchanged; it is no longer trusted to do so, because a single
  mistyped digit could leave one line frozen on screen for the rest of the
  scene.
- A conservative safety bound also limits how long any entry may stay on
  screen. It is tuned not to touch correctly authored subtitles: long holds
  such as a credits card, and deliberate overlap such as a sign displayed
  across several lines of dialogue, are left exactly as authored.
- Subtitles that were already translated and shared with a stuck line are
  repaired on your device as they are delivered — from the community pool,
  from the local cache, and from a file saved next to the video. Shared and
  cached source files stay unchanged, so nothing is re-uploaded and no cache
  is purged.
- The repair only rewrites timecodes. Entry count, text and language are
  unchanged, so no subtitle that is accepted today starts being rejected.

## Embedded subtitles and translation repairs

From MoranSubs `0.2.445` / quickfix `0.1.487`:

- Turning off "auto-search and apply Hebrew on play" no longer removes the
  built-in subtitle entries from the list. Those entries, including "built-in
  translated to Hebrew (AI)", are shown either way; the setting now only
  controls whether a search runs automatically.
- Stray Arabic words that occasionally appeared inside translated Hebrew lines
  are removed on delivery. Hebrew and Arabic both mark gender, so a human
  Arabic translation of the same scene is given to the AI purely as a gender
  reference, and it sometimes copied a word out of it. The removal is
  deliberately cautious: it only takes Arabic out of a line that also has
  Hebrew, never removes a line or an entry, and never touches a line that is
  entirely Arabic — so a subtitle cannot fall silent while people are talking.
  Subtitles already stored with the problem are cleaned as they are delivered.
- It never runs on subtitles the AI did not produce — human subtitles mirrored
  from Ktuvit, Google Translate fallbacks, files you saved yourself, and
  downloads from the subtitle sites are all left exactly as they are.
- The "searching for subtitles" banner no longer flashes on live TV channels.

## Embedded-subtitle extraction speed

From MoranSubs `0.2.446` / quickfix `0.1.488`:

- Reading a video's embedded subtitle track over a debrid link now costs about
  half the network requests it used to. Each subtitle line used to pay for two
  separate range requests: one at the start of its cluster, purely to work out
  where the line sits and what time it starts at, and one for the line itself.
  Neither of those two facts has to be re-read for every line — the first is a
  property of how the file was muxed, and the second is already recorded in the
  file's own index. Both are verified against the old method before they are
  relied upon, and anything that does not check out falls back to it, so a file
  can only be extracted faster, never less accurately.
- A short buffering hiccup no longer cancels the extraction. Kodi reports a
  buffering stall and a seek the same way it reports a pause, and a single
  momentary one was enough to cancel — which is why extraction could run for
  minutes and finish nothing while the movie was simply playing. A pause now has
  to be held for a few seconds to count. Pausing deliberately and then resuming
  still hands the connection straight back to the player, as before.
- An interrupted extraction keeps what it collected. On a provider that limits
  requests aggressively the extraction can only ever be cut short, and every
  attempt used to start again from nothing — so on such a provider it never
  finished at all. Each attempt now continues where the last one stopped. A
  partial result is still never used as a subtitle; this only decides what
  survives an interruption.
- When the provider pushes back, the extraction slows down as before, and now
  speeds back up once the provider stops pushing back — it previously stayed
  slow for the rest of the run. It never goes faster than its normal starting
  rate.
- Extracting from a file stored on the device is no longer refused because
  another extraction appeared to be running. That guard protects a shared debrid
  connection and has no purpose for a local file.

From MoranSubs `0.2.447` / quickfix `0.1.489`:

- Pausing the film and resuming it no longer cancels an extraction in progress.
  Handing the connection back to the player is only worth doing when the
  provider is actually pushing back on the extra requests; when it is not, the
  extraction carries on and the player is unaffected.
- The extraction reports how far along it is, including over a full-screen
  picture, where nothing at all used to appear for several minutes. One that is
  cut short says how much of the file it managed to read — that much is kept,
  and choosing the subtitle again continues from there.
- A provider that starts refusing requests part-way through no longer ends the
  extraction. It is crawled through at whatever rate the provider tolerates, and
  the rate is raised again once the refusals stop. Against a provider refusing
  two requests in every three, that is the difference between no subtitle and a
  complete one.
- A subtitle can no longer come out with only part of its lines because a
  provider quietly returned a short answer. A capped or cut-off response carries
  no error of any kind, and when the bytes happen to run out on an internal
  boundary, reading them back looks normal too. The amount of data returned is
  now checked against the amount owed — for the file's index as well as for the
  subtitle data — and anything short defers the extraction instead of handing
  over a subtitle that is missing lines without saying so. A file whose provider
  merely reports its size a little wrong still finishes: that case is settled by
  asking the provider how long the file actually is, in the one form every
  provider answers precisely, rather than by reading anything into an answer
  that did not arrive.
- Lines the AI leaves out of its reply are asked for again instead of being left
  in the original language.

From MoranSubs `0.2.448` / quickfix `0.1.490`:

- Pressing play no longer cancels an extraction in progress. Resuming the film
  used to matter if the provider had refused even one request, and one refusal
  in fifty-seven is ordinary busy-CDN noise, not a provider in trouble. The
  pause being resumed is usually one the add-on itself caused, too, because
  opening the subtitle list pauses playback — so every subtitle picked by hand
  began paused, and pressing play to carry on watching was being read as a
  signal about the provider. Cancelling now requires the provider to have
  actually throttled the extraction down, and to have done so recently rather
  than at some point earlier in the run. The separate guard that watches for the
  picture freezing is unchanged.
- The extraction says that it is working from the first line it reads, then
  every ten per cent, and never goes more than three quarters of a minute in
  silence while lines are still arriving. It used to wait for the first whole
  twenty per cent, which on a distant provider is minutes — long enough that a
  working extraction was indistinguishable from nothing happening at all.

From MoranSubs `0.2.449`–`0.2.455` / quickfixes `0.1.491`–`0.1.497`:

- One switch turns off every change this add-on makes to POV, for anyone who
  would rather run POV exactly as upstream ships it.
- An AIOStreams provider that cannot answer no longer swallows the whole
  scrape, and our own additions can no longer empty POV's source list.
- The update package stopped shipping POV's own files, so a quick update can
  no longer overwrite a newer POV with an older copy.
- A downloaded subtitle is converted to UTF-8 however it arrived, not only
  when it came out of a zip, and the cp1255 fallback is accepted only when it
  actually produces Hebrew.
- One congestion event is no longer punished six times over.

From MoranSubs `0.2.456` / quickfix `0.1.498` / build `0.1.103`:

- MDBList home tiles appear on the first restart instead of the second.

From MoranSubs `0.2.457` / quickfix `0.1.499` / build `0.1.104`:

- A fresh install no longer starts with the AIOStreams takeover armed, which
  used to plant "No Results" on every title until the add-on disarmed it.

From MoranSubs `0.2.458` / quickfix `0.1.500`:

- When POV cannot resolve a source it now says which one failed and why,
  instead of returning silently.

From MoranSubs `0.2.459` / quickfix `0.1.501`:

- AI-translated subtitles are cleaned where they are made rather than only on
  the way to the player, so the pool never learns the defect. Two faults are
  removed: the source language echoed above its own translation, and letters
  that arrived in a presentation form the subtitle font has no glyph for and
  drew as a hollow box.

From MoranSubs `0.2.460` / quickfix `0.1.502`:

- POV 6.08 changed what its scraper timeout covers — it now has to pay for the
  debrid cache check out of the same budget — so a value that used to be
  generous became too small and produced "no results" on the first attempt and
  sources on the second. The floor is raised for anyone still on the old value;
  a value you chose yourself is left alone.

From MoranSubs `0.2.461` / quickfix `0.1.503`:

- Kodi's own Hebrew strings now repair themselves, not just the skin's. One
  half-written translation file looked like three separate faults: "Favourites"
  and "Exit" back in English, power-menu entries with no caption at all, and a
  FENtastic screen that read as empty because on that skin the labels are the
  content.
- Forty-three internal settings Kodi was dropping on every startup are fixed,
  two POV repairs are back after POV's update moved what they matched, and the
  MDBList QR screen no longer carries Gemini's title.

From MoranSubs `0.2.462` / Wizard `0.1.36` / quickfix `0.1.504` / build
`0.1.105`:

- A new installation no longer skips the five FENtastic home-widget files, so
  Movies, TV shows and Idan+ come up with their content instead of empty. A
  home layout you customized is still kept on a quick update; only files that
  are missing get written, and a deliberate reinstall still lays down defaults.
  A device that already lost those files repairs itself at startup.
- The seek bar Kodi refused to load on every start is fixed — the shipped file
  was missing one closing tag, so Kodi rejected the whole window.
- POV can now read the shortcut folders the build ships. They are stored in one
  spelling and were read in another, so POV saw them all as empty and never
  said so; the same mismatch also made POV quietly replace the build's menus
  with its own defaults. Nothing in the database changes.

## Upstream POV Watch

`.github/workflows/check-upstream-pov.yml` checks the original kodi7rd build metadata every 6 hours and opens an issue if upstream POV changes.

## Repository Protection

See `SECURITY.md` for the GitHub settings that should be enabled to prevent accidental force-pushes, branch deletion, or unreviewed changes.

`CODEOWNERS` is configured for `@MoranTheKing`; GitHub branch protection must enable "Require review from Code Owners" for this to be enforced.

## APK Downloads

The current Android, Windows and LG webOS packages are published as
[`21.3-povil.48`](https://github.com/MoranTheKing/Kodi-POV-IL/releases/tag/v21.3-povil.48).
Use the platform download pages under `downloads/`; see `APK_RELEASE.md` for
update behavior, verified package identities and release evidence.
