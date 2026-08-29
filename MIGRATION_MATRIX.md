# Migration Matrix

## רכיבים שצריך להביא מ־Twillight

| רכיב | מקור ב־Twillight | יעד ב־POV |
|---|---|---|
| סקין FENtastic | `addons/skin.fentastic` | להוסיף לבילד POV |
| FENtastic helper | `addons/script.fentastic.helper` | להוסיף לבילד POV |
| הגדרות FENtastic | `userdata/addon_data/skin.fentastic/settings.xml` | להתאים ל־POV |
| FENtastic favourites | `media/builds_favourites_xml/skin.fentastic/favourites.xml` | לתרגם לפקודות POV |

## רכיבים שכבר קיימים ב־POV

| רכיב | סטטוס |
|---|---|
| `plugin.video.pov` | קיים |
| `Estuary` | קיים ופעיל |
| `Torbox` | קיים ומופעל בהגדרות |
| `Real Debrid` | קיים |
| `Trakt` | קיים |
| `Otaku` | קיים |

## התאמות חובה מ־Twilight ל־POV

| נושא | מצב |
|---|---|
| `RunAddon(plugin.video.twilight)` | הוחלף ל־`plugin.video.pov` בחבילת הבדיקה |
| `plugin://plugin.video.twilight/...` | הוחלף ל־`plugin.video.pov` בחבילת הבדיקה |
| חיבור שירותים | הותאם ל־`mode=myservices` של POV |
| סטטוס RD | הותאם ל־`real_debrid.show_account_info` של POV |
| סטטוס TorBox | נוסף כ־favourite ייעודי |
| שליחת לוג | הותאם ל־`navigator.log_utils` של POV |
| כפתור החלפת סקין | נשען על מנגנון הסקין/וויזארד הקיים; `Estuary` נשאר מותקן |

## הבדלים שכבר זוהו

- ב־`Twillight` יש favourite ייעודי ל־`Twilight`.
- ב־`POV` יש favourite ייעודי ל־`POV`.
- ב־`POV` יש גם favourite ל־`Otaku`, שלא היה באותו תפקיד בסט הישן.
- מבנה ה־favourites דומה מאוד, אבל ה־actions עצמם שונים ולכן לא נכון להעתיק אותם בלי התאמה.

## הערה חשובה

`Twillight` לא עולה כברירת מחדל על `FENtastic`; גם שם קובץ `guisettings.xml` מצביע על `skin.estuary`.
בחבילת הבדיקה הראשונה החלטנו כן להעלות את `POV` ישירות עם `skin.fentastic`, כדי שיהיה קל לבדוק בטלפון אם הסקין עובד כמו שצריך.

`Estuary` נשאר מותקן בתוך החבילה, כדי שיהיה אפשר לחזור אליו דרך החלפת סקין.

## A second migration question, opened 2026-08-27

The matrix above is the Twillight -> POV move, which is done. A different one
is now being investigated and is tracked in its own repository,
[Kodi-POV-IL-RedLight](https://github.com/MoranTheKing/Kodi-POV-IL-RedLight):
**POV -> Red Light**, and Kodi 21 -> Kodi 22.

The reason is not curiosity. POV ships every few days and each release can
break an anchor silently -- five repairs died that way on 6.08.14. But the
measurement that matters most cuts against the move, and it belongs here rather
than in a chat log:

**Red Light changes at least as often.** 164 commits on 71 distinct days in six
months; twelve version bumps in the eighteen days from 8 to 25 August. Swapping
add-ons does not reduce the breakage rate, because the breakage comes from
patching somebody else's source at all, not from whose source it is.

**And the patchers do not carry over.** Measured by running every one of them
against a real Red Light tree with the repo's own harness: of the 35 that
demonstrably work on POV 6.08.14, **5 still land on Red Light and 30 do not**.
The failures split in two, and the second half is the expensive one:

| | |
| --- | --- |
| ~15 report `unmatched` | the file exists, the code moved -- needs a new anchor |
| ~15 report `no_file` | **the file does not exist at all** -- POV has `menus/`, Red Light does not |

Whole features -- the Hebrew menus, genre folders, networks, discover -- have
nothing to land on and would need redesigning rather than re-anchoring.
Connect Services is the sharpest case: Red Light has no `myservices.py`, so the
window twelve versions of `pov_services_patcher` build has no equivalent to
patch. Red Light does carry more debrid APIs than POV, so the capability
exists; it is reached through its own navigator instead.

One genuine improvement on that side: POV scans its scraper folder with
`pkgutil.iter_modules` (the thing that broke on 6.08.14). Red Light imports by
name instead, so a third-party internal scraper needs only the settings
registration, not the folder-scan patch.
