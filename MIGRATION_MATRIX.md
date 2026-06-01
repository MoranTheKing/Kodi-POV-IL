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
