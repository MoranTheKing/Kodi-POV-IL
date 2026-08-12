#!/usr/bin/env python3
"""Fast release guards for the Android, Windows and webOS packages."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
WIZARD_ROOT = ROOT / "wizard/source/plugin.program.kodipovilwizard"


def _load_release_version():
    path = WIZARD_ROOT / "resources/libs/common/release_version.py"
    spec = importlib.util.spec_from_file_location("release_version", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load release_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_platform_branding():
    path = ROOT / ".github/scripts/platform_branding.py"
    spec = importlib.util.spec_from_file_location("platform_branding", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load platform_branding.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_apktool_metadata():
    path = ROOT / ".github/scripts/patch_apktool_metadata.py"
    spec = importlib.util.spec_from_file_location("patch_apktool_metadata", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load patch_apktool_metadata.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_android_apk_metadata():
    path = ROOT / ".github/scripts/verify_android_apk_metadata.py"
    spec = importlib.util.spec_from_file_location(
        "verify_android_apk_metadata",
        path,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load verify_android_apk_metadata.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_android_transparent_pixel_normalization() -> None:
    platform_branding = _load_platform_branding()
    image_type = platform_branding.Image

    source = image_type.new("RGBA", (2, 1))
    source.putdata(((3, 2, 1, 0), (20, 40, 60, 255)))
    aapt_roundtrip = image_type.new("RGBA", (2, 1))
    aapt_roundtrip.putdata(((0, 0, 0, 0), (20, 40, 60, 255)))
    visible_change = image_type.new("RGBA", (2, 1))
    visible_change.putdata(((0, 0, 0, 0), (21, 40, 60, 255)))
    partial_alpha_change = image_type.new("RGBA", (2, 1))
    partial_alpha_change.putdata(((0, 0, 0, 0), (20, 40, 60, 254)))

    assert (
        platform_branding._pixel_digest(source)
        == platform_branding._pixel_digest(aapt_roundtrip)
    )
    assert (
        platform_branding._pixel_digest(source)
        != platform_branding._pixel_digest(visible_change)
    )
    assert (
        platform_branding._pixel_digest(source)
        != platform_branding._pixel_digest(partial_alpha_change)
    )


def test_android_version_metadata_helpers() -> None:
    patcher = _load_apktool_metadata()
    verifier = _load_android_apk_metadata()

    with tempfile.TemporaryDirectory(prefix="povil-apktool-metadata-") as temp:
        apktool_yml = Path(temp) / "apktool.yml"
        apktool_yml.write_text(
            "version: 2.9.3\n"
            "versionInfo:\n"
            "  versionCode: 2103000\n"
            "  versionName: 21.3\n"
            "doNotCompress:\n"
            "- png\n",
            encoding="utf-8",
        )
        patcher.patch_apktool_metadata(
            apktool_yml,
            "2103048",
            "21.3-povil.48",
        )
        patched = apktool_yml.read_text(encoding="utf-8")
        assert "  versionCode: 2103048\n" in patched
        assert "  versionName: 21.3-povil.48\n" in patched
        assert "  versionCode: 2103000\n" not in patched

    actual = verifier.parse_badging(
        "package: name='org.xbmc.povi' versionCode='2103048' "
        "versionName='21.3-povil.48' compileSdkVersion='34'\n"
        "application-label:'Kodi POV IL'\n"
        "native-code: 'arm64-v8a'\n"
    )
    verifier.verify_metadata(
        actual,
        package_id="org.xbmc.povi",
        version_code="2103048",
        version_name="21.3-povil.48",
        app_name="Kodi POV IL",
        native_code="arm64-v8a",
    )
    try:
        verifier.verify_metadata(
            actual,
            package_id="org.xbmc.povi",
            version_code="2103000",
            version_name="21.3-povil.48",
            app_name="Kodi POV IL",
            native_code="arm64-v8a",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("wrong Android versionCode passed final verifier")


def test_release_version_rules() -> None:
    release_version = _load_release_version()
    assert release_version.parse_release_label("21.3-povil.48\n") == (21, 3, 48)
    assert (
        release_version.canonical_release_label("021.03-POVIL.048")
        == "21.3-povil.48"
    )
    assert release_version.is_newer_release(
        "21.3-povil.48", "21.3-povil.47"
    )
    assert not release_version.is_newer_release(
        "21.3-povil.48", "21.3-povil.48"
    )
    for invalid in ("21.3", "21.3.48", "21.3-povil", "povil.48", ""):
        try:
            release_version.parse_release_label(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid release label accepted: %r" % invalid)


def test_windows_installer_guards() -> None:
    nsis = (ROOT / "dist/installer/build-windows-installer.nsi").read_text(
        encoding="utf-8"
    )
    assert "Kodi POV IL.portable_data-backup" in nsis
    assert '*S-1-5-32-545:(OI)(CI)M' in nsis
    assert '"$INSTDIR\\portable_data"' in nsis
    assert "povil-release.txt" in nsis
    assert 'Icon "povil.ico"' in nsis
    assert '"$INSTDIR\\povil.ico"' in nsis
    assert "SetShellVarContext all" in nsis
    assert "Existing profile detected; preserving settings" in nsis
    assert 'Exec \'"$INSTDIR\\kodi.exe" -p\'' not in nsis
    assert 'IfFileExists "$INSTDIR\\portable_data" profile_exists' in nsis
    assert "$INSTDIR\\portable_data\\userdata\\*" not in nsis
    assert "Kodi POV IL.portable_data-new" in nsis
    assert 'Rename "$FreshProfileStage" "$INSTDIR\\portable_data"' in nsis
    assert "IfErrors runtime_failure_restore_failed" in nsis
    assert "$FreshProfileStage\\addons\\skin.fentastic\\addon.xml" in nsis
    assert "$FreshProfileStage\\userdata\\guisettings.xml" in nsis
    assert 'StrCmp $6 "1" manifest_ready manifest_structure_failed' in nsis
    assert "manifest_install_rename_failed:" in nsis
    assert 'Rename "$0.kpov-bak" "$0"' in nsis
    assert "The original was left untouched" in nsis


def test_update_checker_guards() -> None:
    wizard = (WIZARD_ROOT / "resources/libs/wizard.py").read_text(
        encoding="utf-8"
    )
    startup = (WIZARD_ROOT / "startup.py").read_text(encoding="utf-8")
    router = (WIZARD_ROOT / "resources/libs/common/router.py").read_text(
        encoding="utf-8"
    )
    uservar = (WIZARD_ROOT / "uservar.py").read_text(encoding="utf-8")
    assert "_marked_platform_release" in wizard
    assert "_installed_platform_release" in wizard
    assert "release_version.is_newer_release" in wizard
    assert "float(tools.open_url(CONFIG.LATEST_APK_VERSION_TEXT_FILE)" not in wizard
    assert "float(tools.open_url(CONFIG.LATEST_WINDOWS_VERSION_TEXT_FILE)" not in wizard
    assert "DIRECT_WINDOWS_DOWNLOAD_URL" not in wizard
    assert "LATEST_WINDOWS_VERSION_NUMBER" not in wizard
    assert "tempfile.gettempdir(), 'Kodi-POV-IL-Updates'" in wizard
    assert 'WINDOWS_INSTALLATION_PATH = "C:\\\\Program Files\\\\Kodi POV IL"' in uservar
    assert (
        "releases/latest/download/Kodi-POV-IL-Setup.exe" in uservar
    )
    assert "kodi_version_update_check()" in startup
    assert "not kodi_version_update_check_manual" in wizard
    assert "_marked_platform_release() is None" in wizard
    assert "action == 'kodi_version_update_check'" in router
    assert "kodi_version_update_check(kodi_version_update_check_manual)" in router


def test_workflow_package_guards() -> None:
    workflow = (ROOT / ".github/workflows/build-apk.yml").read_text(
        encoding="utf-8"
    )
    assert "WIZARD_VERSION: '0.1.44'" in workflow
    assert "default: '21.3-povil.48'" in workflow
    assert "default: '2103048'" in workflow
    assert "EXPECTED_RELEASE: '21.3-povil.48'" in workflow
    assert "EXPECTED_VERSION_CODE: '2103048'" in workflow
    assert "Validate release inputs" in workflow
    assert "            aapt \\" in workflow
    assert "python3-pil" in workflow
    assert "patch_apktool_metadata.py" in workflow
    assert "verify_android_apk_metadata.py" in workflow
    assert 'sed -i \'s/android:versionCode=' not in workflow
    assert "platform_branding.py generate" in workflow
    assert "platform_branding.py verify-apk" in workflow
    assert "build_webos_ipk.py build" in workflow
    assert "b8ac326df8ad7cf0b52e4f816ab7c39c95410254b1bc3b9b3d024035ecec58ff" in workflow
    assert "tar -xzf \"$WORK/data.tar.gz\"" not in workflow
    assert "povil-release.txt" in workflow
    assert "povil.ico" in workflow


def test_wizard_rebuild_from_clean_checkout() -> None:
    """The surgical Wizard release must rebuild after its source is committed."""
    manifest_path = (
        ROOT
        / "wizard/release_manifests/plugin.program.kodipovilwizard-0.1.44.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["replace"]) == {
        "plugin.program.kodipovilwizard/addon.xml",
        "plugin.program.kodipovilwizard/changelog.txt",
        "plugin.program.kodipovilwizard/resources/libs/wizard.py",
    }
    assert manifest["add"] == []
    builder_source = (ROOT / "tools/build_wizard_package.py").read_text(
        encoding="utf-8"
    )
    assert '"git", "diff"' not in builder_source
    assert '"git", "ls-files"' not in builder_source

    with tempfile.TemporaryDirectory(prefix="povil-wizard-clean-") as temp:
        clean = Path(temp)
        (clean / "tools").mkdir()
        (clean / "dist").mkdir()
        (clean / "wizard/release_manifests").mkdir(parents=True)
        shutil.copy2(
            ROOT / "tools/build_wizard_package.py",
            clean / "tools/build_wizard_package.py",
        )
        shutil.copy2(
            ROOT / "dist/plugin.program.kodipovilwizard-0.1.43.zip",
            clean / "dist/plugin.program.kodipovilwizard-0.1.43.zip",
        )
        shutil.copy2(
            manifest_path,
            clean / "wizard/release_manifests" / manifest_path.name,
        )
        shutil.copytree(
            WIZARD_ROOT,
            clean / "wizard/source/plugin.program.kodipovilwizard",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        attributes = ROOT / ".gitattributes"
        if attributes.is_file():
            shutil.copy2(attributes, clean / ".gitattributes")

        def run(*args: str) -> None:
            subprocess.run(
                list(args),
                cwd=clean,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

        run("git", "init", "-q")
        run("git", "config", "user.name", "Wizard Rebuild Test")
        run("git", "config", "user.email", "wizard-test@example.invalid")
        run("git", "add", "--", ".")
        run("git", "commit", "-q", "-m", "clean checkout fixture")
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=clean,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout
        assert status == ""

        run(
            sys.executable,
            "tools/build_wizard_package.py",
            "--previous",
            "dist/plugin.program.kodipovilwizard-0.1.43.zip",
            "--manifest",
            "wizard/release_manifests/"
            "plugin.program.kodipovilwizard-0.1.44.json",
            "--version",
            "0.1.44",
        )
        rebuilt = clean / "dist/plugin.program.kodipovilwizard-0.1.44.zip"
        assert hashlib.sha256(rebuilt.read_bytes()).hexdigest() == (
            manifest["output_sha256"]
        )


def test_phase_one_artifacts() -> None:
    build = (ROOT / "wizard/assets/build.txt").read_text(
        encoding="utf-8"
    ).replace("\r\n", "\n")
    matching_snapshots = []
    for path in (ROOT / "wizard/assets/build_versions").glob("*.txt"):
        if path.read_text(encoding="utf-8").replace("\r\n", "\n") == build:
            matching_snapshots.append(int(path.stem))
    assert matching_snapshots, "build.txt has no immutable build_versions copy"
    snapshot_id = max(matching_snapshots)

    quickfix_match = re.search(r"quickfix-([0-9.]+)\.zip", build)
    assert quickfix_match
    assert (
        ROOT / "dist"
        / ("Kodi-POV-IL-FENtastic-quickfix-%s.zip"
           % quickfix_match.group(1))
    ).is_file()
    assert "kodipovilwizard-0.1.44.zip" in build

    # Accept both legal publication states:
    #   phase 1 -> artifacts/snapshot N are live while note N-1 remains live;
    #   phase 2 -> the one-file note bump makes note N live.
    note = (
        ROOT / "wizard/assets/notification_files/quick_update.txt"
    ).read_text(encoding="utf-8")
    note_id = int(note.split("|||", 1)[0])
    assert note_id in (snapshot_id - 1, snapshot_id)

    # Each release against its OWN predecessor. This pair used to be pinned
    # to a historical one and drifted into asserting a file list that had
    # nothing to do with the version being shipped.
    old_wizard = ROOT / "dist/plugin.program.kodipovilwizard-0.1.43.zip"
    new_wizard = ROOT / "dist/plugin.program.kodipovilwizard-0.1.44.zip"
    latest_wizard = ROOT / "dist/plugin.program.kodipovilwizard-latest.zip"
    assert new_wizard.read_bytes() == latest_wizard.read_bytes()
    page_wizard = ROOT / "wizard/plugin.program.kodipovilwizard-0.1.44.zip"
    page_latest = ROOT / "wizard/plugin.program.kodipovilwizard-latest.zip"
    assert new_wizard.read_bytes() == page_wizard.read_bytes()
    assert new_wizard.read_bytes() == page_latest.read_bytes()
    page_index = (ROOT / "wizard/index.html").read_text(encoding="utf-8")
    for href in re.findall(r'href="([^"]+\.zip)"', page_index):
        assert (ROOT / "wizard" / href).is_file(), (
            "Wizard page points to a missing ZIP: %s" % href
        )
    with ZipFile(old_wizard) as old, ZipFile(new_wizard) as new:
        old_crc = {info.filename: info.CRC for info in old.infolist()}
        new_crc = {info.filename: info.CRC for info in new.infolist()}
        changed = {
            name
            for name in old_crc.keys() & new_crc
            if old_crc[name] != new_crc[name]
        }
        assert changed == {
            "plugin.program.kodipovilwizard/addon.xml",
            "plugin.program.kodipovilwizard/changelog.txt",
            "plugin.program.kodipovilwizard/resources/libs/wizard.py",
        }
        assert not (set(new_crc) - set(old_crc))
        assert not (set(old_crc) - set(new_crc))

    old_quickfix = (
        ROOT / "dist/Kodi-POV-IL-FENtastic-quickfix-0.1.483.zip"
    )
    new_quickfix = (
        ROOT / "dist/Kodi-POV-IL-FENtastic-quickfix-0.1.484.zip"
    )
    wizard_prefix = "addons/plugin.program.kodipovilwizard/"
    pool = "addons/service.subtitles.kodipovilai/resources/lib/pool.py"
    with ZipFile(old_quickfix) as old, ZipFile(new_quickfix) as new:
        old_by = {info.filename: info for info in old.infolist()}
        new_by = {info.filename: info for info in new.infolist()}
        assert old.read(pool) == new.read(pool)
        for name, info in old_by.items():
            if not name.startswith(wizard_prefix):
                assert name in new_by
                assert old.read(info) == new.read(new_by[name])
        qf_changed = {
            name
            for name in old_by.keys() & new_by
            if old_by[name].CRC != new_by[name].CRC
        }
        assert qf_changed == {
            wizard_prefix + "addon.xml",
            wizard_prefix + "changelog.txt",
            wizard_prefix + "resources/libs/wizard.py",
        }
        assert not (set(new_by) - set(old_by))
        assert not (set(old_by) - set(new_by))


def main() -> int:
    test_android_transparent_pixel_normalization()
    test_android_version_metadata_helpers()
    test_release_version_rules()
    test_windows_installer_guards()
    test_update_checker_guards()
    test_workflow_package_guards()
    test_wizard_rebuild_from_clean_checkout()
    test_phase_one_artifacts()
    print("platform package guards: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
