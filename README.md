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
- חבילת בדיקה ל־Kodi: `dist/Kodi-POV-IL-FENtastic-test-0.1.2.zip`.
- הוראות התקנה ובדיקת smoke test לטלפון: `ANDROID_TESTING.md`.

## חבילת בדיקה 0.1.2

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

`dist/plugin.program.kodipovilwizard-0.1.1.zip`

After installing it in Kodi, open:

`Add-ons -> Program add-ons -> Kodi POV IL Wizard -> Builds -> Kodi POV IL - FENtastic`

The wizard reads build metadata from:

`wizard/assets/build.txt`

## Kodi File Source

After GitHub Pages deploys, add this source in Kodi:

`https://morantheking.github.io/Kodi-POV-IL/`

Then open:

`Settings -> File manager -> Add source -> Install from zip file -> Kodi POV IL -> wizard -> plugin.program.kodipovilwizard-0.1.1.zip`

## Updates

The wizard checks `wizard/assets/build.txt` every Kodi startup.

Quick updates are controlled by:

`wizard/assets/notification_files/quick_update.txt`

When the quick update number increases, installed builds receive the `gui` package automatically on next Kodi startup.

## Upstream POV Watch

`.github/workflows/check-upstream-pov.yml` checks the original kodi7rd build metadata every 6 hours and opens an issue if upstream POV changes.
