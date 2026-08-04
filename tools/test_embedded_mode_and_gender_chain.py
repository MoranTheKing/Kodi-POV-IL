#!/usr/bin/env python3
"""Focused regression tests for the embedded UX and gender-reference ordering."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "addons" / "service.subtitles.kodipovilai"
KODI_UTILS = ADDON_ROOT / "resources" / "lib" / "kodi_utils.py"
ARABIC_GENDER = ADDON_ROOT / "resources" / "lib" / "arabic_gender.py"
TRANSLATE = ADDON_ROOT / "resources" / "lib" / "translate.py"
EMBEDDED_EXTRACT = ADDON_ROOT / "resources" / "lib" / "embedded_extract.py"
MKV_PROBE = ADDON_ROOT / "resources" / "lib" / "mkv_probe.py"

EXPECTED_CHAIN = (
    "he", "ar", "hi", "es", "ru", "pt", "pl", "uk", "fr", "it",
    "cs", "ro", "el", "bg", "sr", "hr", "sk", "ur", "nl",
)


def _load_gender_module():
    sys.path.insert(0, str(ADDON_ROOT))
    try:
        spec = importlib.util.spec_from_file_location(
            "_povil_test_arabic_gender", ARABIC_GENDER
        )
        if spec is None or spec.loader is None:
            raise AssertionError("could not load arabic_gender.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _load_kodi_utils_module():
    spec = importlib.util.spec_from_file_location(
        "_povil_test_kodi_utils", KODI_UTILS
    )
    if spec is None or spec.loader is None:
        raise AssertionError("could not load kodi_utils.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedded_mode_mapping():
    module = _load_kodi_utils_module()

    def run(initial, fail_writes=()):
        store = dict(initial)
        module.get_setting = lambda key, default="": store.get(key, default)
        module.get_bool = lambda key, default=False: (
            default if key not in store
            else str(store[key]).strip().lower() == "true"
        )

        def write(key, value):
            if key in fail_writes:
                return False
            store[key] = str(value)
            return True

        module.set_setting = write
        return module.embedded_translation_mode(), store

    # Real Kodi upgrade shape: the new schema supplies default "auto" even when
    # there is no persisted new-mode value. Legacy choices still win pre-marker.
    mode, store = run({
        "embedded_translation_mode": "auto",
        "embedded_translate": "false",
        "embedded_http_extract": "true",
    })
    assert mode == "off"
    assert store["_embedded_mode_v1"] == "1"
    assert store["embedded_translation_mode"] == "off"

    mode, store = run({
        "embedded_translation_mode": "auto",
        "embedded_translate": "true",
        "embedded_http_extract": "false",
    })
    assert mode == "local_only"
    assert store["embedded_translation_mode"] == "local_only"

    # A non-default mode selected before service startup is already intentional.
    mode, store = run({
        "embedded_translation_mode": "direct",
        "embedded_translate": "false",
        "embedded_http_extract": "false",
    })
    assert mode == "direct"
    assert store["embedded_translate"] == "true"
    assert store["embedded_http_extract"] == "true"

    for mode in ("auto", "align_only", "direct", "local_only", "off"):
        got, store = run({
            "_embedded_mode_v1": "1",
            "embedded_translation_mode": mode,
            "embedded_translate": "true",
            "embedded_http_extract": "true",
        })
        assert got == mode
        assert store["embedded_translate"] == (
            "false" if mode == "off" else "true"
        )
        assert store["embedded_http_extract"] == (
            "false" if mode in ("off", "local_only") else "true"
        )

    assert module.embedded_translation_policy("auto") == {
        "mode": "auto", "enabled": True, "try_align": True,
        "try_extract": True, "allow_http": True,
    }
    assert module.embedded_translation_policy("align_only") == {
        "mode": "align_only", "enabled": True, "try_align": True,
        "try_extract": False, "allow_http": True,
    }
    assert module.embedded_translation_policy("direct") == {
        "mode": "direct", "enabled": True, "try_align": False,
        "try_extract": True, "allow_http": True,
    }
    assert module.embedded_translation_policy("local_only") == {
        "mode": "local_only", "enabled": True, "try_align": True,
        "try_extract": True, "allow_http": False,
    }
    assert module.embedded_translation_policy("off") == {
        "mode": "off", "enabled": False, "try_align": False,
        "try_extract": False, "allow_http": False,
    }

    # A failed canonical write must not stamp the migration marker; next startup
    # retries instead of losing the legacy choice.
    mode, store = run({
        "embedded_translation_mode": "auto",
        "embedded_translate": "false",
        "embedded_http_extract": "true",
    }, fail_writes={"embedded_translation_mode"})
    assert mode == "off"
    assert "_embedded_mode_v1" not in store

    # Corrupt canonical value must fail safe to the mirrored legacy boundary,
    # not silently re-enable remote extraction.
    mode, store = run({
        "_embedded_mode_v1": "1",
        "embedded_translation_mode": "corrupt",
        "embedded_translate": "true",
        "embedded_http_extract": "false",
    })
    assert mode == "local_only"
    assert store["embedded_translation_mode"] == "local_only"


def test_direct_embedded_feeds_common_gender_pipeline():
    """Direct extraction is a source-acquisition step, not a translator.

    Neither embedded_extract.py nor mkv_probe.py should import the gender
    oracle. The contract is that resolve() turns the extracted SRT into a normal
    AI payload and falls through to the one common pipeline that calls
    arabic_gender.begin(). Keep that bridge explicit so a future refactor cannot
    accidentally create a separate, English-only direct-extraction path.
    """
    assert "arabic_gender" not in EMBEDDED_EXTRACT.read_text(encoding="utf-8")
    assert "arabic_gender" not in MKV_PROBE.read_text(encoding="utf-8")

    source = TRANSLATE.read_text(encoding="utf-8")
    embedded_start = source.index("    if kind == 'embedded_ai':")
    engine_start = source.index("    if kind == 'engine_ai':", embedded_start)
    embedded_branch = source[embedded_start:engine_start]

    direct_pos = embedded_branch.index(
        "elif _emb_policy['try_extract']:")
    extract_pos = embedded_branch.index(
        "_extract_embedded_srt(", direct_pos)
    payload_pos = embedded_branch.index(
        "payload = {'type': 'ai',", extract_pos)
    ai_pos = embedded_branch.index("kind = 'ai'", payload_pos)

    assert "'embedded': True" in embedded_branch[payload_pos:ai_pos]
    assert "# fall through to the AI logic below" in embedded_branch[ai_pos:]

    common_gate = source.index("    if kind != 'ai':", engine_start)
    gender_begin = source.index(
        "arabic_gender.begin(info, src_text)", common_gate)
    direct_abs = embedded_start + direct_pos
    extract_abs = embedded_start + extract_pos
    payload_abs = embedded_start + payload_pos
    ai_abs = embedded_start + ai_pos
    assert (
        embedded_start < direct_abs < extract_abs < payload_abs < ai_abs
        < engine_start < common_gate < gender_begin
    )


def _candidate(lang, number):
    return {
        "language": lang,
        "_engine_kind": "human_he" if lang == "he" else "other",
        "filename": f"{lang}-{number}.srt",
        "number": number,
    }


def test_primary_chain_is_round_robin_and_deeper_than_three(module):
    """Round-robin WITHIN a quality tier; tier 1 exhausted before tier 2.

    This used to pin all ten Hebrew candidates before the first Arabic one.
    That spent the search on one language: the active-work deadline is
    dominated by downloads, so ten Hebrew misses could exhaust it before
    Arabic -- the oracle the prompt is built around -- was tried at all, and
    the job then translated with no oracle and defaulted to masculine.

    A flat round-robin fixed that and broke something else: it takes whatever
    aligns FIRST, so a weak language's opening candidate could beat a strong
    language's third. Tiers keep both properties. Hebrew and Arabic alternate,
    so Arabic is attempt 2; and every Hebrew and Arabic candidate is tried
    before any other language, so no weaker oracle can take a job away from an
    Arabic one that would have aligned.
    """
    candidates = (
        [_candidate("he", number) for number in range(1, 13)]
        + [_candidate("ar", 1), _candidate("hi", 1)]
    )
    module._reference_candidates = lambda info: candidates
    plan, diag = module.begin(
        {}, "1\n00:00:01,000 --> 00:00:02,000\nhello\n"
    )
    assert plan is not None
    assert diag["cands"] == 12  # top ten Hebrew + Arabic + Hindi
    # tier 1 alternates and is exhausted first; hi (tier 2) comes last.
    assert [lang for lang, _ in plan._ordered] == (
        ["he", "ar"] + ["he"] * 9 + ["hi"]
    )

    attempts = []
    module._download_candidate = lambda cand: (
        attempts.append((cand["language"], cand["number"])) or cand
    )
    module.align_one = lambda src, blocks, cand: (
        ({1: "reference"}, "ok")
        if (cand["language"], cand["number"]) == ("he", 9)
        else (None, "miss")
    )
    lang, mapping = plan.next()
    assert lang == "he" and mapping == {1: "reference"}
    assert attempts == (
        [("he", 1), ("ar", 1)]
        + [("he", number) for number in range(2, 10)]
    )


def test_next_walks_the_given_order_faithfully(module):
    # Constructs `ordered` by hand, so this pins ReferencePlan.next()'s
    # traversal rather than begin()'s ordering (which is round-robin now, see
    # above): whatever order it is handed, it tries every candidate in it,
    # in that order, until one aligns.
    ordered = (
        [("he", _candidate("he", number)) for number in range(1, 11)]
        + [("ar", _candidate("ar", 1))]
    )
    plan = module.ReferencePlan("src", ["block"], ordered, len(ordered))
    attempts = []
    module._download_candidate = lambda cand: (
        attempts.append((cand["language"], cand["number"])) or cand
    )
    module.align_one = lambda src, blocks, cand: (
        ({1: "مرجع"}, "ok")
        if cand["language"] == "ar"
        else (None, "miss")
    )
    lang, mapping = plan.next()
    assert lang == "ar" and mapping
    assert attempts == (
        [("he", number) for number in range(1, 11)] + [("ar", 1)]
    )


def test_concurrent_fallback_pulls_are_serialized(module):
    ordered = [
        ("he", _candidate("he", 1)),
        ("ar", _candidate("ar", 1)),
    ]
    plan = module.ReferencePlan("src", ["block"], ordered, len(ordered))
    guard = threading.Lock()
    active = 0
    max_active = 0

    def download(cand):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with guard:
            active -= 1
        return cand

    module._download_candidate = download
    module.align_one = lambda src, blocks, cand: ({1: "ref"}, "ok")
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(plan.next()))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert max_active == 1
    assert {lang for lang, mapping in results if mapping} == {"he", "ar"}


def test_all_miss_is_globally_bounded(module):
    ordered = []
    for lang in ("he", "ar", "hi", "es", "ru", "pt"):
        ordered.extend(
            (lang, _candidate(lang, number)) for number in range(1, 11)
        )
    plan = module.ReferencePlan("src", ["block"], ordered, len(ordered))
    attempts = []
    module._download_candidate = lambda cand: (attempts.append(cand) or cand)
    module.align_one = lambda src, blocks, cand: (None, "miss")
    assert plan.next() == (None, None)
    assert len(attempts) == module._TOTAL_DOWNLOAD_BUDGET == 50
    assert [cand["language"] for cand in attempts] == (
        ["he"] * 10 + ["ar"] * 10 + ["hi"] * 10
        + ["es"] * 10 + ["ru"] * 10
    )


def test_active_deadline_excludes_idle_time(module):
    # Derived from the constant rather than hardcoded, so raising the deadline
    # (30s -> 60s, to leave room for depth once round-robin has covered the
    # languages) does not silently invalidate what this is checking: that only
    # ACTIVE download/align time counts, and that the ceiling stops the chain.
    per_attempt = 11.0
    expected = int(module._REFERENCE_DEADLINE_S // per_attempt) + 1
    ordered = [
        ("he", _candidate("he", number))
        for number in range(1, expected + 5)
    ]
    plan = module.ReferencePlan("src", ["block"], ordered, len(ordered))
    attempts = []
    now = [1000.0]  # arbitrary late wall time; idle since plan creation is free

    def download(cand):
        attempts.append(cand)
        now[0] += per_attempt
        return cand

    original_monotonic = module.time.monotonic
    module.time.monotonic = lambda: now[0]
    module._download_candidate = download
    module.align_one = lambda src, blocks, cand: (None, "miss")
    try:
        assert plan.next() == (None, None)
    finally:
        module.time.monotonic = original_monotonic
    assert len(attempts) == expected
    assert plan._active_elapsed == expected * per_attempt
    # ...and it really did stop on the deadline, not on running out of input.
    assert len(attempts) < len(ordered)


def test_long_gemini_idle_does_not_expire_lazy_fallback(module):
    ordered = [
        ("he", _candidate("he", 1)),
        ("ar", _candidate("ar", 1)),
    ]
    plan = module.ReferencePlan("src", ["block"], ordered, len(ordered))
    now = [0.0]
    original_monotonic = module.time.monotonic
    module.time.monotonic = lambda: now[0]
    module._download_candidate = lambda cand: cand
    module.align_one = lambda src, blocks, cand: ({1: "ref"}, "ok")
    try:
        assert plan.next()[0] == "he"
        now[0] += 1000.0  # Gemini work / idle time between lazy fallback pulls
        assert plan.next()[0] == "ar"
    finally:
        module.time.monotonic = original_monotonic
    assert plan._active_elapsed == 0.0


def main():
    module = _load_gender_module()
    assert module._REF_CHAIN == EXPECTED_CHAIN
    assert module._PER_LANG_LIMIT == 10
    assert module._TOTAL_DOWNLOAD_BUDGET == 50
    assert module._REFERENCE_DEADLINE_S == 60.0
    test_embedded_mode_mapping()
    test_direct_embedded_feeds_common_gender_pipeline()
    test_primary_chain_is_round_robin_and_deeper_than_three(module)
    test_next_walks_the_given_order_faithfully(module)
    test_concurrent_fallback_pulls_are_serialized(module)
    test_all_miss_is_globally_bounded(module)
    test_active_deadline_excludes_idle_time(module)
    test_long_gemini_idle_does_not_expire_lazy_fallback(module)
    print(
        "PASS embedded direct-to-gender bridge + mode mapping "
        "+ strict serial gender-reference chain"
    )


if __name__ == "__main__":
    main()
