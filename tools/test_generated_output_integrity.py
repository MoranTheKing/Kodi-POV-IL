"""Regression tests for model-output structure and self-edit contamination.

Run: python tools/test_generated_output_integrity.py
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "addons" / "service.subtitles.kodipovilai" / "resources" / "lib"
spec = importlib.util.spec_from_file_location("srt_integrity", LIB / "srt.py")
srt = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(srt)


def block(index, start, end, text):
    return f"{index}\n00:00:{start:02d},000 --> 00:00:{end:02d},000\n{text}"


SOURCE = [
    block(1, 1, 2, "First source line."),
    block(2, 3, 4, "Second source line."),
    block(3, 5, 6, "Third source line."),
]
HE = [
    block(1, 1, 2, "שורה ראשונה."),
    block(2, 3, 4, "שורה שנייה."),
    block(3, 5, 6, "שורה שלישית."),
]


def body(value):
    return srt.block_text_only(value)


print("== structural gate ==")
preface = "Kohrt, let's translate these subtitles carefully."
out, missing, editorial = srt.generated_output_blocks(
    SOURCE, preface + "\n\n" + srt.stitch_blocks(HE), fill_missing=True)
assert out == HE, out
assert missing == [] and editorial == 0
print("  ok - an untimed preface is not an SRT cue")

# Equal parsed count used to look healthy: two requested cues plus one preface.
out, missing, _ = srt.generated_output_blocks(
    SOURCE, preface + "\n\n" + srt.stitch_blocks(HE[:2]), fill_missing=True)
assert len(out) == 3 and len(missing) == 1
assert body(out[2]) == "Third source line."
print("  ok - equal block count cannot hide a missing requested cue")

invented = block(99, 40, 41, "זמן שלא התבקש.")
out, missing, _ = srt.generated_output_blocks(
    SOURCE, srt.stitch_blocks(HE[:2] + [invented]), fill_missing=True)
assert len(out) == 3 and len(missing) == 1 and body(out[2]) == "Third source line."
print("  ok - an invented timestamp is dropped and its source slot survives")

duplicate = block(22, 3, 4, "כפילות לא מורשית.")
out, missing, _ = srt.generated_output_blocks(
    SOURCE, srt.stitch_blocks(HE + [duplicate]), fill_missing=True)
assert out == HE and missing == []
print("  ok - duplicate output cannot exceed source multiplicity")

# Equal count plus agreeing neighbours positively pins an isolated time typo.
mistimed = block(2, 33, 34, "שורה שנייה.")
out, missing, _ = srt.generated_output_blocks(
    SOURCE, srt.stitch_blocks([HE[0], mistimed, HE[2]]), fill_missing=True)
assert out == HE and missing == []
print("  ok - the existing safe isolated-timing repair is preserved")


print("== generated editorial commentary ==")
bad_shapes = [
    "חוץ מזה. אתה עורר אנשים.\n"
    "[Wait, let's fix \"עורר\" -> \"עוזר\"]\n"
    "חוץ מזה. אתה עוזר לאנשים.",
    "אל תדאגי, אני הולכת להרוג אותה. "
    "(Wait, \"I'm not gonna kill her\" -> אני לא הולכת להרוג אותה.)",
    "ועשירה ב-100 אלף דולר יותר. (Wait, let's fix idiom)\n"
    "ועשירה ב-100 אלף דולר.",
    "ממנו מגיע השיר הישן. "
    "[Wait, translate naturally: \"שיר חדש\". Or keep as is: \"שיר ישן\".]",
]
for number, text in enumerate(bad_shapes, 1):
    candidate = [block(1, 1, 2, text)]
    assert srt.generated_editorial_leak_indices([SOURCE[0]], candidate) == [0], text
print("  ok - all four observed self-edit shapes are rejected")

bad = [block(1, 1, 2, bad_shapes[1])]
out, missing, editorial = srt.generated_output_blocks(
    [SOURCE[0]], srt.stitch_blocks(bad), fill_missing=True)
assert editorial == 1 and len(missing) == 1 and out == [SOURCE[0]]
print("  ok - a contaminated cue is retriable/missing, never substring-cleaned")

preserved = [
    "הוא לחש (Wait) ואז יצא.",
    'הסיסמה היא "Wait->Go".',
    "הפונקציה היא x -> y והכול תקין.",
    "המתן כאן. (Wait)",
    "הערה בסוגריים (literal) היא חלק מהדיאלוג.",
]
for text in preserved:
    candidate = [block(1, 1, 2, text)]
    assert srt.generated_editorial_leak_indices([SOURCE[0]], candidate) == [], text
print("  ok - stage directions, passwords, arrows and literals are preserved")

literal_source = [block(1, 1, 2, "Wait, let's fix the translation.")]
literal_output = [block(
    1, 1, 2,
    "בוא נתקן את התרגום. (Wait, let's fix the translation.)",
)]
assert srt.generated_editorial_leak_indices(literal_source, literal_output) == []
print("  ok - source dialogue about editing is not mistaken for model metadata")

english_only = [block(1, 1, 2, "[Wait, let's fix this -> that]")]
assert srt.generated_editorial_leak_indices([SOURCE[0]], english_only) == []
print("  ok - untranslated/source-only cues stay under the normal fallback gate")


print("== generated full-source echo ==")
echo_source = [block(1, 1, 2, "And his victim is in the wind,")]
echo_shapes = [
    "והקורבן שלו נעלמה,\n[and his victim is in the wind,]",
    "והקורבן שלו נעלמה.\nAnd his victim is in the wind,",
    "והקורבן שלו נעלמה. (AND HIS VICTIM IS IN THE WIND)",
]
for echo_text in echo_shapes:
    candidate = [block(1, 1, 2, echo_text)]
    assert srt.generated_source_echo_indices(echo_source, candidate) == [0]
print("  ok - trailing full-source echoes that survive normal cleanup are rejected")

safe_echo_cases = [
    ("The code is ERROR 42.", "הקוד הוא [ERROR 42]."),
    ("Play We Will Rock You tonight.", "נגנו הערב [We Will Rock You]."),
    ("And his victim is in the wind,", "And his victim is in the wind,"),
    ("And his victim is in the wind,", "הקורבן שלו נעלם [in the wind]."),
    ("ברוכים הבאים\nWelcome to New York", "ברוכים הבאים\nWelcome to New York"),
    ("The Lord of the Rings.", "שר הטבעות\n(The Lord of the Rings)"),
    ("The Man Who Would Be King.", "האיש שרצה להיות מלך\n(The Man Who Would Be King)"),
    ("I know what you did last summer.",
     "אני יודע מה עשית בקיץ האחרון\n[I know what you did last summer]"),
    ('"the key is under the red stone"',
     'המפתח נמצא מתחת לאבן האדומה\n["the key is under the red stone"]'),
    ("Alpha Bravo Charlie Delta", "אלפא בראבו צ'רלי דלתא\n[Alpha Bravo Charlie Delta]"),
    ("And his victim is in the wind,",
     "And his victim is in the wind,\nוהקורבן שלו נעלמה."),
]
for source_text, target_text in safe_echo_cases:
    assert srt.generated_source_echo_indices(
        [block(1, 1, 2, source_text)],
        [block(1, 1, 2, target_text)],
    ) == [], (source_text, target_text)
print("  ok - bilingual sources, titles, codes, leading echoes and literals survive")

out, missing, rejected = srt.generated_output_blocks(
    echo_source, srt.stitch_blocks([block(1, 1, 2, echo_shapes[0])]),
    fill_missing=True,
)
assert rejected == 1 and len(missing) == 1 and out == echo_source
print("  ok - an echoed cue is retried/falls back as a whole")


print("== narrow negation-loss rejection ==")
negation_cases = [
    ("Don't worry, I'm not gonna kill her.",
     "אל תדאגי, אני הולכת להרוג אותה."),
    ("Don 't worry, I 'm not gonna kill her.",
     "אל תדאגי, אני הולכת להרוג אותה."),
    ("Don't worry, I'm not gonna kill her.",
     "\u202bאל תדאגי, אני הולכת להרוג אותה.\u202c"),
    ("I'm not going to hurt him.", "אני הולך לפגוע בו."),
    ("She is not going to murder him.", "היא מתכוונת לרצוח אותו."),
]
for source_text, target_text in negation_cases:
    candidate = [block(1, 1, 2, target_text)]
    assert srt.generated_negation_loss_indices(
        [block(1, 1, 2, source_text)], candidate) == [0], source_text
print("  ok - the observed polarity inversion and equivalent shapes are rejected")

safe_negation_cases = [
    ("I'm not gonna kill her.", "אני לא הולכת להרוג אותה."),
    ("I'm not going to leave.", "אינני מתכוון לעזוב."),
    ("I'm going to kill her.", "אני הולכת להרוג אותה."),
    ("I'm not going to spare her.", "אני אחוס עליה."),
    ("I'm not going to fail to help.", "אני מתכוון לעזור."),
    ("I'm not going to forget to call.", "אני מתכוון להתקשר."),
    ("I'm not going to not go.", "אני הולך."),
    ("I'm not going to be unhappy.", "אני עומד להיות שמח."),
    ("I'm not going to lie.", "אני מתכוון לומר את האמת."),
    ("I'm not going to tell lies.", "אני מתכוון לספר את האמת."),
    ("I'm not going to leave without you.", "אני מתכוון לעזוב איתך."),
    # A positive Hebrew main verb can be equivalent when the condition carries
    # the restriction. The narrow detector must abstain rather than rewrite it.
    ("I'm not going to hurt you unless you attack me.",
     "אני הולך לפגוע בך רק אם תתקוף אותי."),
    ("I'm not going to kill him until tomorrow.", "אני אהרוג אותו רק מחר."),
    ("If he returns, I'm not going to hurt him.",
     "אם הוא יחזור, אני הולך לפגוע בו רק אם יתקוף."),
    # Different punctuation/clause topology is ambiguous, so this gate abstains.
    ("Wait. I'm not going to leave.", "רגע אני הולך לעזוב."),
]
for source_text, target_text in safe_negation_cases:
    candidate = [block(1, 1, 2, target_text)]
    assert srt.generated_negation_loss_indices(
        [block(1, 1, 2, source_text)], candidate) == [], source_text
print("  ok - correct, paraphrased, double-negative and ambiguous cases survive")

bad_negation = [block(1, 1, 2, "אני הולכת להרוג אותה.")]
bad_source = [block(1, 1, 2, "I'm not gonna kill her.")]
out, missing, rejected = srt.generated_output_blocks(
    bad_source, srt.stitch_blocks(bad_negation), fill_missing=True)
assert rejected == 1 and len(missing) == 1 and out == bad_source
print("  ok - final gate keeps source on a high-confidence polarity suspicion")

timed_source = [
    block(1, 1, 2, "Before."),
    block(2, 3, 4, "I'm not going to kill her."),
    block(3, 5, 6, "After."),
]
mistimed_inversion = [
    block(1, 1, 2, "לפני."),
    block(2, 33, 34, "אני הולך להרוג אותה."),
    block(3, 5, 6, "אחרי."),
]
out, missing, rejected = srt.generated_output_blocks(
    timed_source, srt.stitch_blocks(mistimed_inversion), fill_missing=True)
assert rejected == 1 and len(missing) == 1
assert body(out[1]) == "I'm not going to kill her."
print("  ok - safe timing repair cannot bypass semantic rejection")


print("== mutations and production wiring ==")
real_pattern = srt._EDITORIAL_ACTION_RE
try:
    srt._EDITORIAL_ACTION_RE = re.compile(r"(?!)")
    assert srt.generated_editorial_leak_indices(
        [SOURCE[0]], [block(1, 1, 2, bad_shapes[1])]) == []
finally:
    srt._EDITORIAL_ACTION_RE = real_pattern
print("  ok - removing the detector restores the regression (mutation killed)")

real_negation_pattern = srt._NEGATIVE_FUTURE_RE
try:
    srt._NEGATIVE_FUTURE_RE = re.compile(r"(?!)")
    assert srt.generated_negation_loss_indices(
        bad_source, bad_negation) == []
finally:
    srt._NEGATIVE_FUTURE_RE = real_negation_pattern
print("  ok - removing the negation detector restores the polarity regression")

real_conditional_pattern = srt._NEGATIVE_FUTURE_CONDITIONAL_RE
try:
    srt._NEGATIVE_FUTURE_CONDITIONAL_RE = re.compile(r"(?!)")
    assert srt.generated_negation_loss_indices(
        [block(1, 1, 2,
               "I'm not going to hurt you unless you attack me.")],
        [block(1, 1, 2,
               "אני הולך לפגוע בך רק אם תתקוף אותי.")],
    ) == [0]
finally:
    srt._NEGATIVE_FUTURE_CONDITIONAL_RE = real_conditional_pattern
print("  ok - removing conditional abstention restores its false positive")

real_echo_pattern = srt._LATIN_ECHO_WORD_RE
try:
    srt._LATIN_ECHO_WORD_RE = re.compile(r"(?!)")
    assert srt.generated_source_echo_indices(
        echo_source, [block(1, 1, 2, echo_shapes[0])]) == []
finally:
    srt._LATIN_ECHO_WORD_RE = real_echo_pattern
print("  ok - removing the source-echo detector restores the leak")

real_align = srt.align_blocks
try:
    srt.align_blocks = lambda _src, *candidates: list(candidates[0])
    mutated, _, _ = srt.generated_output_blocks(
        SOURCE, preface + "\n\n" + srt.stitch_blocks(HE), fill_missing=True)
    assert preface in mutated
finally:
    srt.align_blocks = real_align
print("  ok - removing source-slot alignment restores the preface leak")

try:
    def broken_align(*_args, **_kwargs):
        raise RuntimeError("simulated ownership-gate failure")
    srt.align_blocks = broken_align
    guarded, missing, rejected = srt.generated_output_blocks(
        SOURCE, preface + "\n\n" + srt.stitch_blocks(HE), fill_missing=True)
    assert guarded == SOURCE and missing == SOURCE and rejected == 0
    retryable, missing, rejected = srt.generated_output_blocks(
        SOURCE, srt.stitch_blocks(HE), fill_missing=False)
    assert retryable == [] and missing == SOURCE and rejected == 0
finally:
    srt.align_blocks = real_align
print("  ok - an internal ownership-gate failure fails closed to source/retry")

translate_source = (LIB / "translate.py").read_text("utf-8")
compile(translate_source, str(LIB / "translate.py"), "exec")
assert "generated_editorial_leak_indices(\n                    ch," in translate_source
assert "generated_source_echo_indices(\n                    ch," in translate_source
assert "generated_negation_loss_indices(\n                    ch," in translate_source
assert "generated_output_blocks(\n                        chunks[idx - 1], response, fill_missing=True)" in translate_source
call = translate_source.index("response = gemini.generate(")
reject = translate_source.index("generated_editorial_leak_indices(", call)
negation_reject = translate_source.index("generated_negation_loss_indices(", reject)
return_response = translate_source.index("return response", reject)
assert call < reject < negation_reject < return_response
print("  ok - rejection runs before API output returns; final gate fills every rung")

print("PASS: generated output integrity")
