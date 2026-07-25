#!/usr/bin/env python3
"""Build and verify the shared Kodi POV IL platform artwork.

The project already has one canonical square logo and one canonical 16:9
splash.  Derive every package-specific bitmap from those files so Android,
Windows and webOS cannot silently drift back to upstream Kodi artwork.

Pillow is intentionally the only dependency.  The release workflow installs
the distro package (python3-pil), so this script never downloads build-time
code from PyPI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image


TV_BANNER_SIZE = (320, 180)
APP_LAUNCH_SIZE = (1920, 1080)
WINDOWS_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
MEDIA_ICON_SIZES = {
    "icon16x16.png": 16,
    "icon32x32.png": 32,
    "icon48x48.png": 48,
    "icon80x80.png": 80,
    "icon120x120.png": 120,
    "icon256x256.png": 256,
    "vendor_icon.png": 128,
}
WEBOS_ROOT_ICONS = {
    "icon.png": 80,
    "largeIcon.png": 130,
}
ANDROID_DENSITIES = ("ldpi", "mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi")


def _resample() -> int:
    return getattr(Image, "Resampling", Image).LANCZOS


def _open_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _open_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def _save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def _pixel_digest(image: Image.Image) -> str:
    rgba = image.convert("RGBA")
    pixels = bytearray(rgba.tobytes())
    # Android's aapt resource cruncher is allowed to discard RGB values from
    # fully transparent pixels.  Those hidden channels do not affect rendered
    # artwork, but hashing them made a byte-for-byte source image fail after a
    # normal apktool/aapt round trip.  Normalize only alpha-zero pixels; every
    # visible or partially visible pixel remains an exact comparison.
    for offset in range(0, len(pixels), 4):
        if pixels[offset + 3] == 0:
            pixels[offset : offset + 3] = b"\0\0\0"
    payload = (
        ("%dx%d:" % rgba.size).encode("ascii")
        + pixels
    )
    return hashlib.sha256(payload).hexdigest()


def _file_pixel_digest(path: Path) -> str:
    with Image.open(path) as image:
        return _pixel_digest(image)


def _bytes_pixel_digest(payload: bytes) -> tuple[tuple[int, int], str]:
    from io import BytesIO

    with Image.open(BytesIO(payload)) as image:
        return image.size, _pixel_digest(image)


def generate(logo_path: Path, splash_path: Path, out_dir: Path) -> dict[str, object]:
    logo = _open_rgba(logo_path)
    splash = _open_rgb(splash_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    tv_banner = splash.resize(TV_BANNER_SIZE, _resample())
    launch = splash.resize(APP_LAUNCH_SIZE, _resample())
    _save_png(tv_banner, out_dir / "android-tv-banner.png")
    _save_png(launch, out_dir / "applaunch_screen.png")

    for name, size in WEBOS_ROOT_ICONS.items():
        _save_png(logo.resize((size, size), _resample()), out_dir / name)
    for name, size in MEDIA_ICON_SIZES.items():
        _save_png(
            logo.resize((size, size), _resample()),
            out_dir / "media" / name,
        )

    ico_path = out_dir / "povil.ico"
    logo.save(
        ico_path,
        format="ICO",
        sizes=[(size, size) for size in WINDOWS_ICON_SIZES],
    )

    generated = {
        "android-tv-banner.png": _file_pixel_digest(out_dir / "android-tv-banner.png"),
        "applaunch_screen.png": _file_pixel_digest(out_dir / "applaunch_screen.png"),
        "icon.png": _file_pixel_digest(out_dir / "icon.png"),
        "largeIcon.png": _file_pixel_digest(out_dir / "largeIcon.png"),
        "media": {
            name: _file_pixel_digest(out_dir / "media" / name)
            for name in sorted(MEDIA_ICON_SIZES)
        },
        "windows_ico_sha256": hashlib.sha256(ico_path.read_bytes()).hexdigest(),
    }
    (out_dir / "branding-manifest.json").write_text(
        json.dumps(generated, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return generated


def _expect_image(
    archive: ZipFile,
    member: str,
    expected_path: Path,
    expected_size: tuple[int, int] | None = None,
) -> None:
    try:
        payload = archive.read(member)
    except KeyError as exc:
        raise AssertionError("missing branded image: %s" % member) from exc
    actual_size, actual_digest = _bytes_pixel_digest(payload)
    expected_digest = _file_pixel_digest(expected_path)
    if expected_size and actual_size != expected_size:
        raise AssertionError(
            "%s has size %r; expected %r" % (member, actual_size, expected_size)
        )
    if actual_digest != expected_digest:
        raise AssertionError(
            "%s pixels do not match %s" % (member, expected_path)
        )


def verify_apk(
    apk_path: Path,
    launcher_dir: Path,
    generated_dir: Path,
    release_label: str,
) -> None:
    with ZipFile(apk_path) as archive:
        for density in ANDROID_DENSITIES:
            _expect_image(
                archive,
                "res/drawable-%s/ic_launcher.png" % density,
                launcher_dir / ("ic_launcher-%s.png" % density),
            )

        banner = generated_dir / "android-tv-banner.png"
        _expect_image(
            archive,
            "res/drawable-xhdpi/banner.png",
            banner,
            TV_BANNER_SIZE,
        )
        _expect_image(
            archive,
            "assets/media/banner.png",
            banner,
            TV_BANNER_SIZE,
        )
        _expect_image(
            archive,
            "assets/media/applaunch_screen.png",
            generated_dir / "applaunch_screen.png",
            APP_LAUNCH_SIZE,
        )

        for name, size in MEDIA_ICON_SIZES.items():
            _expect_image(
                archive,
                "assets/media/%s" % name,
                generated_dir / "media" / name,
                (size, size),
            )

        splash = archive.read("assets/media/splash.jpg")
        source_splash = Path(generated_dir / "source-splash.jpg")
        if source_splash.exists() and splash != source_splash.read_bytes():
            raise AssertionError("assets/media/splash.jpg is not the POV IL splash")

        marker = archive.read("assets/system/povil-release.txt").decode("utf-8")
        if marker != release_label + "\n":
            raise AssertionError(
                "APK release marker is %r; expected %r"
                % (marker, release_label + "\n")
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("generate")
    build.add_argument("--logo", type=Path, required=True)
    build.add_argument("--splash", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)

    verify = sub.add_parser("verify-apk")
    verify.add_argument("--apk", type=Path, required=True)
    verify.add_argument("--launcher-dir", type=Path, required=True)
    verify.add_argument("--generated-dir", type=Path, required=True)
    verify.add_argument("--release-label", required=True)

    args = parser.parse_args(argv)
    if args.command == "generate":
        generate(args.logo, args.splash, args.out)
        # Keep the exact JPEG too.  Kodi loads assets/media/splash.jpg directly,
        # so byte identity is both simpler and stronger than a re-encode.
        (args.out / "source-splash.jpg").write_bytes(args.splash.read_bytes())
    else:
        verify_apk(
            args.apk,
            args.launcher_dir,
            args.generated_dir,
            args.release_label,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError) as exc:
        print("platform branding error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
