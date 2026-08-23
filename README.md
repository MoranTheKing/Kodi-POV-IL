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
- חבילת בדיקה ל־Kodi: `dist/Kodi-POV-IL-FENtastic-test-0.1.119.zip`.
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

## Choosing the Android app: take 64-bit

Both Android builds run on a 64-bit device, but the 32-bit one opens large 4K
files much more slowly. Measured on an NVIDIA SHIELD, same file, minutes apart:
14 seconds on 32-bit against 3 seconds on 64-bit. The whole difference is in
reading the file's index, which for anything over 4 GB is work a 32-bit build
has to do several times over.

**Every SHIELD is 64-bit** -- all models, not only the Pro -- and so are Fire TV
Stick 4K and 4K Max, Onn 4K, Chromecast with Google TV and Mi Box S. The
download page used to send most of those to the 32-bit file. It no longer does.
Take 32-bit only if 64-bit refuses to install.

Switching is safe: both carry the same app id and signing key, so 64-bit
installs over 32-bit as an update and your data stays where it is.

## Sources no longer come back empty when they exist (from `0.2.506`)

Two reports on one evening: the count of sources found climbs while POV
searches -- forty, a hundred and twenty, three hundred -- and then the list
never opens. "No results" on a title that certainly has sources. Intermittent,
and only for people on Premiumize.

Once the scrapers have found their torrents, POV asks the debrid service which
of them it already holds, and it builds the list it shows you entirely out of
the answers that came back in time. One debrid configured means one answer, so
a debrid that is a second late leaves nothing to build from and the whole
search is thrown away unread. Worse, a check that FAILED -- timed out, refused,
answered nonsense -- was recorded as a definite "none of these are cached", and
the default setting then deletes every one of those from the list. Both roads
end at an empty screen after the counters climbed.

Why Premiumize and not TorBox on the same build: one number, "Scraper/Debrid
Timeout", is both how long POV waits for the answer and how long the Premiumize
request itself is allowed to take -- so a slow request always finishes at or
after the moment POV stopped waiting, and raising the number raises both halves
equally. TorBox sends all of its torrents in one compact request; Premiumize
sends each one as a separate field, hundreds of them on a popular title. And it
works
on the second try because POV remembers the answers, so a title you just
searched skips the request entirely.

A debrid that does not answer no longer erases anything. Its sources are kept
and marked "not checked" -- which is exactly what POV already does for
Real-Debrid and AllDebrid every time -- so you get the list, with the unverified
ones at the bottom. A debrid that does answer is treated exactly as before, and
an honest "nothing cached here" is still believed and still hidden.

## The add-on is never switched off while a dialog is open (from `0.2.506`)

To make a fix take effect the same evening the build switches the video add-on
off and on again, and it waits for the home screen to be idle first. But every
window that add-on puts up while it works -- the search progress, the list of
sources -- floats over the home screen. Start a title from a home-screen row
and the home screen is still there underneath, nothing is playing, no row is
loading, and somebody reading a list of sources is not pressing buttons. Every
test for "idle" said yes while the user was mid-search with a dialog in front
of their face.

One log shows the switch landing on an open source list and pulling the focus
back to the home screen; another shows it killing a search seven seconds in --
and that is the search that was reported as "no results". A dialog on screen is
now never a moment to do this, checked again in the last second before it
happens. If the moment never comes, the switch is recorded as still owed and
done at the next start instead of forced through.

## An update keeps the settings you changed that evening (from `0.2.506`)

The wizard closed Kodi by killing it, which skips the save Kodi does on a normal
shutdown. That is correct after a full build install, where a save would
overwrite the settings file that was just extracted -- and wrong after a quick
update, where nothing of the kind was written. Audio passthrough turning itself
back off is what made it visible, because that is a setting people set once and
notice immediately, but every setting was affected.

The quick update now asks Kodi to close properly and falls back to the kill only
if that does not take. The build install and the skin switch keep the kill they
need.

## Umbrella arrives on every device (from `0.2.506`)

Half the build already assumed it was there: the home screen carries Umbrella
tiles, the search wiring has an Umbrella branch, the account manager pushes
debrid accounts into it, and a dozen small repairs exist for no other reason
than to make it speak Hebrew. On a device without it every one of those quietly
did nothing, and the screen looked identical either way.

Umbrella and its scraper module now install once, in the background, on every
device including one taking a quick update -- and their own repositories come
with them, so from that moment the developers publish their updates rather than
us. A tile you remove stays removed.

## Add-ons that stopped updating themselves update again (from `0.2.506`)

Kodi keeps a table of add-ons excluded from automatic updates, and it writes
rows into that table by itself. An add-on whose ORIGIN repository stops
answering has no version to be compared against, so Kodi concludes it is not
the latest and excludes it for good. This build has such a repository -- a
field log catches it returning 404 -- and several of the add-ons registered to
it are ones the build ships.

The excluded add-on still appears in the manual "available updates" list, which
is why updating by hand worked and made the fault look random. The build now
clears those automatic exclusions for the add-ons it ships, never touches one
you set by hand or a version you installed from a zip on purpose, and names
every one it finds in the log.

## The logo in the player's on-screen display draws (from `0.2.506`)

Under the on-screen display, a pair of images: the title's own logo, and the
studio logo when the title has none. Each was shown by a condition missing one
closing bracket, so Kodi could not parse either, treated both as false, and drew
neither -- on every device, on every title, since the day it was written. One of
the two is meant to be showing at all times.

## Subtitle sync learns from a manual shift again (from `0.2.505`)

While one of our subtitles is playing, the amount you shift it by hand is the
strongest possible evidence about whether it is in sync -- it is the only thing
that resolves files no automatic method can. That measurement was reading zero
every time and the watch never started at all, because of three missing lines
that each failed quietly into a handler that swallowed them. It had never once
reported. It does now.

## The home rows no longer come back empty after an update (from `0.2.505`)

For the second and a half the video add-on is switched off, Kodi does not know
it. On a cold start the home screen is still loading its rows in exactly those
seconds, so the rows asked for an add-on that was not there, failed, and --
because it is the switching OFF that triggers the rebuild -- nothing rebuilt
them afterwards. They stayed empty for the session. Clearing the cache appeared
to fix it; so did moving to the 64-bit build. Neither fixed anything: both just
shifted the timing.

The switch now waits for the home screen to be genuinely settled, and if the
rows still come back empty it redraws them once. None of the waiting happens
where it can be felt, and startup is in fact slightly faster than before.

## POV's source list draws in about a second again (from `0.2.504`)

Reported as five to ten seconds to appear after the search had clearly
finished, where it used to be about one. The log timed it: two seconds with
three Hebrew subtitles available for the title, four with six, ten with
seventeen. The Hebrew-match badge on each row was comparing every source
against every available subtitle name and re-deriving both names from scratch
every time, so seventeen names were taken apart seventy times each before one
row could be drawn.

Each name is read once now, the built-in-Hebrew check costs nothing, and no
comparison runs that cannot change the answer -- about twenty-five times less
work, with every badge coming out identical. Umbrella's source list gets the
same. And the reason it slowed down out of nowhere with nothing having changed:
the subtitle lists that badge walks were never trimmed, so they grew a little
with every title watched. They are capped now.

## Kan 11 items in Idan Plus play (from `0.2.503`)

Nothing from that channel would start: YouTube answered "This video is
unavailable" for every one of them, five different player clients in a row,
because the id it was being asked for was the literal word "watch". Idan Plus
reads the video id out of the address path, and in the ordinary
youtube.com/watch?v= form the id is not in the path. The add-on builds that
address itself, from a bare id Kan hands it, and then fails to read back what
it just wrote -- so this was never a Kan change and never a regression: those
items have never played.

One line reads the id from the right place now, and only where what was
extracted cannot be an id at all, so every link the add-on already opened
correctly opens exactly as before. If Idan Plus fixes this on its side, the fix
simply stops applying.

## A debrid that refuses your account says why (from `0.2.502`, `0.2.505`, `0.2.506`)

A report of "no results" turned out not to be a no-results condition at all: 70
sources were found, and all 38 of the AllDebrid ones failed to start with the
same internal error. POV's own error handler was crashing on a variable it never
set, and that crash was replacing the message the provider had actually sent.

AllDebrid, TorBox and Premiumize all answer normally -- HTTP 200 -- and put a
refusal in the body, so an add-on that only records a problem when the status
code is bad throws the reason away one line after it arrives. If the key is not
valid, the access is blocked, the account is suspended or it is not premium,
you are told which, in Hebrew. Nothing is said for a timeout or a bad
connection -- only for an answer the service actually gave. None of this makes
a refused account work; it makes the refusal readable.

## Umbrella's "in progress" rows fill themselves in (from `0.2.501`)

An earlier fix cleared the sync cursor for the shows list, and cleared two more
keys alongside it that were not cursors -- they are the signal Umbrella reads to
decide whether there is new watched activity worth syncing. Zeroing them meant
"nothing new, serve the cache" forever, so the episodes list, which had always
been right, started needing a manual refresh too. Only the fetch cursor is
cleared now, and devices that took that release are repaired on their next
start.

Underneath both: the sync wrote "synced up to now" even when the fetch had
failed, and the cursor only ever moves forward, so anything inside a failed
request was skipped permanently. It now advances only when the fetch really
returned a page.

## A quick update writes only the files that differ (from `0.2.500`)

Every quick update was laying down all 1,969 files, 1,330 of them belonging to
the skin that was on screen at that moment -- and on some devices Kodi
force-closed partway through, over and over, before the update could finish. It
writes five files on a typical update now. A device several updates behind still
receives everything it is missing, because the comparison is against that
device's own files.

## The player bar hides itself on every skin that can (from `0.2.499`)

The setting that closes the player's on-screen bar after a few idle seconds was
being turned on by a check that named one skin — FENtastic — and returned for
everything else. `skin.povil.nox` ships the identical feature, off by default
like FENtastic's, so anyone on Nox had the bar stay up until they pressed Back.
Nothing was broken on those devices; a default simply never reached them.

It is detected from the active skin's own files now, rather than matched
against a list of names, so a skin that has the feature gets it and one that
does not is left alone. The record of having seeded it lives in the SKIN's
settings, which makes it per-skin for free: switch to a skin that has never
been seeded and it is seeded, and if you turn auto-close back off yourself it
stays off.

## Umbrella's "continue watching" for series catches up (from `0.2.499`)

The episodes list showed the right next episode while the series list sat
several episodes behind. They do not read the same thing: episodes come from
MDBList live, series are rebuilt from a table on the device. So the table was
missing rows — which is also why Umbrella's own "Force MDBList Sync" fixed it,
since that wipes the tables and re-reads everything from scratch.

The rows went missing because the sync stores its position as the clock time of
the last run, and stores it even when a request failed or came back empty. That
position only ever moves forward, so one network error, one empty response, or
a few seconds of disagreement between the device's clock and MDBList's, and
everything in that window was skipped for good.

The sync now reads thirty days further back than its stored position, so a
window missed for any reason is picked up on the next run instead of lost —
re-reading the same episodes costs nothing, they simply overwrite. And a table
that has already lost rows is refilled once, by itself, at the next start: the
same thing the Force button does, without needing to know the button is there.

## If you installed the subtitles add-on on its own (from `0.2.498`)

The automatic move to Gemini 3.7 Flash announced in `0.2.494` reached the build
but never reached anyone who installed the AI subtitles add-on by itself, from
the repository. The announcement was shared between the two; the change itself
was not, because the two are not the same program — the standalone runs a
slimmer service of its own.

Anyone still on 3.5 or 3.6 Flash is moved across once, now, at the next start.
Any other model you picked yourself is left exactly as it is. Nothing to do.

## Searching MDBList lists: a screen of its own (from `0.2.497`)

Searching for a list used to open the keyboard straight from the home screen,
which meant the results were the first thing on the screen after home — so
**Back** from them went all the way out, and looking up a second list meant
finding the tile again.

It now opens a screen of its own first, listing the searches you have run
before. Back from a set of results returns to that screen; Back again goes
home. A search you have run before is one click away, and long-pressing it
offers to remove it or clear the whole history. The results themselves also
carry a **new search** row at the top, so a second search never needs Back at
all.

**Cancelling the keyboard now leaves you where you were.** It used to take you
to an empty listing with nothing in it, which then had to be backed out of.

## Like and Unlike no longer send you back to the keyboard (from `0.2.497`)

Pressing either one on a list you found by searching said "Success" and then
re-opened the search keyboard. It now simply redraws the list you were looking
at, with the entry flipped to the other one. This applied to Unlike exactly as
it did to Like.

## MDBList lists get the menu Trakt lists already had (from `0.2.496`)

Holding down on an MDBList list used to offer almost nothing. It now offers the
same menu a Trakt list does, Like and Unlike included, so a list you find by
searching can be added to your own without leaving the search.

The entry you are shown is the one that applies: a list you have already liked
offers **Unlike**, a list you have not offers **Like**. That check reads the
list data the add-on has already fetched, so it costs no extra request and no
extra waiting. When that data is not there to read, both entries are offered
rather than the wrong one guessed — both are safe to press, because liking a
list you already like changes nothing.

Two kinds of list are deliberately left alone. Your own lists cannot be liked,
and lists MDBList only mirrors from another service cannot be either — MDBList
provides no way to do it. Neither is given a button that could not work.

## A Hebrew subtitle re-timed onto the built-in one (from `0.2.496`)

A new row in the subtitle list, **עברית מסונכרנת למובנה**, takes a Hebrew
subtitle and re-times it onto the timeline of the film's own built-in subtitle
track. When a Hebrew subtitle is written for a different cut and drifts against
your copy, this is the row that fixes it.

It appears only when there is both a Hebrew subtitle to re-time and a built-in
track to time it against, so if the film has no Hebrew subtitle at all the row
is simply not there and nothing else changes. It is never chosen for you: it
delivers a different translation from the one inside the file, so it stays a
choice you make rather than something applied on your behalf.

## Subtitle numbers no longer appear inside the text (from `0.2.496`)

A raw subtitle number and timecode could show up in the middle of a line of
dialogue, mid-film. Two subtitles had been welded into one when the translation
lost the blank line that separates them, and everything after the weld was read
as text rather than as the start of the next subtitle. They are separated
again.

## The piratebay source provider is off (from `0.2.496`)

It is now off by default. If you turn it back on it stays on, through this
update and any later one.

## Films and episodes play again (from `0.2.495`)

The video add-on updated itself and began asking the file host to put the
file's name inside the download link. The name arrives with spaces in it, which
makes the link invalid, and Kodi refused it without ever contacting the file —
so playback failed instantly, on everything, because every release name has
spaces.

The link is now repaired before playback rather than the request being taken
away, so the add-on keeps the feature it added and a future version of it needs
no further repair from us.

The same add-on update also moved its favourites code, which quietly stopped
the repair that makes a title you add appear straight away instead of only
after navigating away and back. That works again too.

## Kodi no longer closes on the way back to the home screen (from `0.2.494`)

When several rows on the home screen reloaded at the same moment, Kodi could
close itself completely. It happened most often on the way back from a submenu
to the home screen, and it took the whole application down rather than the row
that caused it.

The video add-on was set to run every one of those loads inside a single shared
Python interpreter. Loading several at once corrupted it, and a corrupted
interpreter is not something an add-on can recover from. Each load now gets its
own, so the same burst is merely slower instead of fatal. That closes the whole
family rather than the one way of provoking it that was reported -- two earlier
versions of this crash were each fixed by removing a single trigger, and a
third arrived by an ordinary route.

Two things worth knowing. **The fix takes effect from the next start of Kodi
after the update**, because Kodi reads that setting while it is starting, before
the update has run. And rows may take slightly longer to draw -- about a tenth
of a second per load, measured on a real device. Opening films and skipping
forward or back are not affected at all.

## AI translation moves to Gemini 3.7 Flash (from `0.2.494`)

Anyone already on 3.5 or 3.6 Flash is moved across once, automatically. Any
other model you picked yourself is left exactly as it is.

## The tile from the last update now opens (from `0.2.493`)

The "10 latest updates" tile arrived on the home screen with the previous
update, and on most devices it did nothing when clicked. It opens a screen that
belongs to the wizard, and the update carried a wizard that did not have that
screen yet -- so the tile was real and the destination was not.

This update ships them together, and adds the rule that keeps them together:
the tile is now only offered once the wizard installed on the device is new
enough to open it. Until then nothing is written and nothing is shown, so a
tile that cannot be clicked can no longer appear at all.

## The last ten updates, on the home screen (from `0.2.492`)

The ten most recent update notes are readable from a tile on the home screen,
newest first. The list is never longer than ten, so it stays quick to open.

Removing the tile is respected: it does not come back at the next update or the
next start. Switching skin rewrites the home tiles from the skin's own defaults
-- if that removes the tile without you asking, it is restored; if you removed
it yourself, it stays removed.

## Add-ons you switched off stay off (from `0.2.492`)

The build repairs a main add-on left disabled by an update that was interrupted
-- a device switched off mid-update, for example. It now does that only when
there is a record showing the build itself disabled it and could not switch it
back on. An add-on you turned off yourself is left alone.

## The main add-on keeps its background service (from `0.2.492`)

Kodi treats an add-on as unknown for a couple of seconds after it is switched
back on, while it finishes loading it -- but it starts that add-on's own
background service straight away. The main video add-on reads a setting as it
starts, so it could land in that gap and stop before it began: no Trakt sync
for the rest of the session, and an error in the log. It now waits the gap out
instead of giving up.

This covers the point the failure was reported from. The same add-on reads its
own details in a few other places that are not covered yet; those are next.

## No more update prompts you cannot act on (from `0.2.492`)

Two of the add-ons that ship with the build checked their own home page at
every start and offered a newer version. The build pins those versions on
purpose -- they carry changes made for this build, and taking the upstream
copy removes them -- so the prompt offered something the add-on screen had no
way to accept. The check is switched off once. If you switch it back on, it
stays on.

## You are not asked to reinstall the app for nothing (from `0.2.492`)

The Android and Windows packages are checked at every start, and if a newer
one exists you are offered it -- there is no "do not ask again", so an offer
you keep declining comes back at every start until you act on it. That is the
right behaviour for a package that changes the application.

It is the wrong behaviour for one that does not. A package also carries a copy
of the build, used only to set up a brand new install; an install that already
exists gets the same content through the ordinary update, so for it the new
package holds nothing new. Those releases are now marked, and the offer is not
raised for them. Nothing is hidden: the release exists, the download page
serves it, and "עדכון גרסת קודי" in the wizard menu still finds it and installs
it if you ask.

Installing a package over an existing one keeps everything -- settings,
add-ons, accounts, watched history. It is an upgrade, not a reinstall.

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
