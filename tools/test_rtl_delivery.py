#!/usr/bin/env python3
"""Regression checks for Hebrew RTL delivery and immutable pool sources."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "service.subtitles.kodipovilai"
sys.path.insert(0, str(ADDON))

from resources.lib import pool, srt, subs_engine_bridge, translate  # noqa: E402


HE = "\u05e9\u05dc\u05d5\u05dd"
MORE = "\u05db\u05dc \u05de\u05d4 \u05e9\u05e6\u05e8\u05d9\u05da"
RLE = "\u202b"
PDF = "\u202c"


def _wrapped(logical: str) -> str:
    return RLE + logical + PDF


def test_rtl_shapes() -> None:
    assert srt.fix_rtl_punctuation(
        f"- {HE}?", mode="rtl_base") == _wrapped(f"- {HE}?")
    assert srt.fix_rtl_punctuation(
        f"{HE}...", mode="rtl_base") == _wrapped(f"{HE}...")

    # Exact old-engine field shapes.
    assert srt.fix_rtl_punctuation(
        f"? {HE}-", mode="rtl_base",
        legacy_engine=True) == _wrapped(f"- {HE}?")
    assert srt.fix_rtl_punctuation(
        f"...{MORE}", mode="rtl_base",
        legacy_engine=True) == _wrapped(f"{MORE}...")
    assert srt.fix_rtl_punctuation(
        f"\u2026{MORE}", mode="rtl_base",
        legacy_engine=True) == _wrapped(f"{MORE}\u2026")

    # A genuine leading continuation stays leading outside known legacy text.
    assert srt.fix_rtl_punctuation(
        f"...{MORE}", mode="rtl_base") == _wrapped(f"...{MORE}")
    # A genuine interruption dash has no displaced-punctuation prefix.
    assert srt.fix_rtl_punctuation(
        f"{HE}-", mode="rtl_base",
        legacy_engine=True) == _wrapped(f"{HE}-")
    assert srt.fix_rtl_punctuation(
        f"{HE} -", mode="rtl_base",
        legacy_engine=True) == _wrapped(f"{HE} -")


def test_auto_detection_and_idempotence() -> None:
    legacy = (
        "1\n00:00:01,000 --> 00:00:02,000\n"
        f"? {HE}-\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n"
        f"...{MORE}\n"
    )
    fixed = srt.fix_rtl_punctuation(
        legacy, mode="rtl_base", legacy_engine="auto")
    assert _wrapped(f"- {HE}?") in fixed
    assert _wrapped(f"{MORE}...") in fixed
    assert srt.fix_rtl_punctuation(
        fixed, mode="rtl_base", legacy_engine=True) == fixed

    ambiguous_only = (
        "1\n00:00:01,000 --> 00:00:02,000\n"
        f"...{MORE}\n"
    )
    safe = srt.fix_rtl_punctuation(
        ambiguous_only, mode="rtl_base", legacy_engine="auto")
    assert _wrapped(f"...{MORE}") in safe

    # An old-engine byte stream cannot distinguish a genuine leading
    # continuation from a trailing ellipsis that was moved there: both are
    # literally "...body". The compatibility mode intentionally repairs all
    # such lines only for positively legacy-tagged files. Fresh/logical files
    # above preserve the same genuine leading form.
    mixed_legacy = (
        "1\n00:00:01,000 --> 00:00:02,000\n"
        f"? {HE}-\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n"
        f"...{MORE}\n"
    )
    mixed_fixed = srt.fix_rtl_punctuation(
        mixed_legacy, mode="rtl_base", legacy_engine=True)
    assert _wrapped(f"- {HE}?") in mixed_fixed
    assert _wrapped(f"{MORE}...") in mixed_fixed


def test_display_copy_keeps_source_and_share_marker() -> None:
    content = (
        "1\n00:00:01,000 --> 00:00:02,000\n"
        f"? {HE}-\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n"
        f"...{MORE}\n"
    )
    with tempfile.TemporaryDirectory() as td:
        source = Path(td) / "ktuvit_cached.srt"
        source.write_text(content, encoding="utf-8")
        shared = Path(str(source) + ".shared")
        shared.write_text("1", encoding="ascii")
        before = source.read_bytes()

        rendered = Path(subs_engine_bridge._render_hebrew_rtl_copy(
            str(source), legacy_engine=True))
        assert rendered != source
        assert rendered.is_file()
        assert source.read_bytes() == before
        assert shared.read_text(encoding="ascii") == "1"
        assert subs_engine_bridge.source_path_for_delivery(
            str(rendered)) == str(source)
        text = rendered.read_text(encoding="utf-8")
        assert _wrapped(f"- {HE}?") in text
        assert _wrapped(f"{MORE}...") in text


def test_release_dedup_and_format_tag() -> None:
    body = {
        "kind": "ktuvit",
        "release": "Show.S01E01.1080p.WEB-DL-GROUP.srt",
        "tmdb_id": "1",
        "imdb_id": "",
        "type": "episode",
        "season": "1",
        "episode": "1",
        "lang": "he",
    }
    original = pool._lookup_raw
    try:
        pool._lookup_raw = lambda _p: {
            "variants": [{
                "kind": "ktuvit",
                "release": "Show S01E01 1080p WEB DL GROUP",
                "hash": "different-bytes",
            }]
        }
        assert pool._pool_has_ktuvit_release(body)
        assert pool.KTUVIT_LOGICAL_SOURCE_TAG == "he-logical-v1"
        assert translate._ktuvit_release_key(
            body["release"]) == translate._ktuvit_release_key(
                "Show S01E01 1080p WEB DL GROUP")
    finally:
        pool._lookup_raw = original

    # The durable Ktuvit queue drains through _post_sync (not _post). Prove a
    # release match exits before any /contribute path.
    hebrew_text = "\n\n".join(
        "{0}\n00:00:{1:02d},000 --> 00:00:{2:02d},000\n{3}".format(
            i, i, i + 1, HE * 20)
        for i in range(1, 16)
    )
    queued = dict(body, srt=hebrew_text, source_hash="different-bytes")
    old_hash_check = pool._pool_has_hash
    old_release_check = pool._pool_has_ktuvit_release
    old_urlreq = pool._urlreq
    network_calls = []

    class NoNetwork:
        @staticmethod
        def Request(*args, **kwargs):
            network_calls.append(("Request", args, kwargs))
            raise AssertionError("release dedup reached /contribute")

        @staticmethod
        def urlopen(*args, **kwargs):
            network_calls.append(("urlopen", args, kwargs))
            raise AssertionError("release dedup reached network")

    try:
        pool._pool_has_hash = lambda _body, _hash: False
        pool._pool_has_ktuvit_release = lambda _body: True
        pool._urlreq = NoNetwork
        assert pool._post_sync(queued) == "ok"
        assert network_calls == []
    finally:
        pool._pool_has_hash = old_hash_check
        pool._pool_has_ktuvit_release = old_release_check
        pool._urlreq = old_urlreq

    captured = []
    old_build = pool._build_body
    old_enqueue = pool.enqueue
    try:
        def fake_build(_info, _hash, source_lang, _text, **_kwargs):
            captured.append(source_lang)
            return {"source_lang": source_lang}

        pool._build_body = fake_build
        pool.enqueue = lambda _body, marker_path=None: None
        pool.contribute_ktuvit({}, "x", logical_source=False)
        pool.contribute_ktuvit({}, "x", logical_source=True)
        assert captured == ["he", pool.KTUVIT_LOGICAL_SOURCE_TAG]
    finally:
        pool._build_body = old_build
        pool.enqueue = old_enqueue


def test_pool_source_is_fetched_once() -> None:
    with tempfile.TemporaryDirectory() as td:
        old_fetch = pool.fetch
        old_cache_dir = translate.kodi_utils.cache_dir
        calls = []
        try:
            pool.fetch = lambda _info, source_hash=None: (
                calls.append(source_hash) or
                "1\n00:00:01,000 --> 00:00:02,000\n" + HE + "\n")
            translate.kodi_utils.cache_dir = lambda: td
            h = "12345678abcdef00"
            first, sid1 = translate._pool_source_text({}, h)
            second, sid2 = translate._pool_source_text({}, h)
            assert first == second
            assert sid1 == sid2 == h
            assert calls == [h]
            assert (Path(td) / f"pool_{h}.source.srt").is_file()
        finally:
            pool.fetch = old_fetch
            translate.kodi_utils.cache_dir = old_cache_dir


def test_visual_positions_with_python_bidi() -> None:
    try:
        from bidi.algorithm import get_display
    except ImportError as exc:
        if "--require-bidi" in sys.argv:
            raise AssertionError(
                "python-bidi is required for release verification") from exc
        print("SKIP python-bidi visual reference (use --require-bidi for release)")
        return
    dash = srt.fix_rtl_punctuation(
        f"? {HE}-", mode="rtl_base", legacy_engine=True)
    ellipsis = srt.fix_rtl_punctuation(
        f"...{MORE}", mode="rtl_base", legacy_engine=True)
    dash_visual = get_display(dash)
    ellipsis_visual = get_display(ellipsis)
    # get_display returns the left-to-right screen order: end punctuation is at
    # index 0 (left), while the leading dialogue dash is at the right edge.
    assert dash_visual.startswith("?")
    assert dash_visual.endswith("-")
    assert ellipsis_visual.startswith("...")


def main() -> None:
    test_rtl_shapes()
    test_auto_detection_and_idempotence()
    test_display_copy_keeps_source_and_share_marker()
    test_release_dedup_and_format_tag()
    test_pool_source_is_fetched_once()
    test_visual_positions_with_python_bidi()
    print("PASS RTL delivery, immutable source, and request-safe Ktuvit dedup")


if __name__ == "__main__":
    main()
