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
- חבילת בדיקה ל־Kodi: `dist/Kodi-POV-IL-FENtastic-test-0.1.101.zip`.
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
