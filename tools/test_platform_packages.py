#!/usr/bin/env python3
"""Fast release guards for the Android, Windows and webOS packages."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import zipfile
import os
import re
import shutil
import subprocess
import types
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


def test_no_auto_app_prompt_targets() -> None:
    """The automatic app-update dialog must stay suppressible, and only that.

    That dialog fires from startup.py on EVERY start and its "later" button
    records nothing, so a package nobody needs is a prompt at every boot until
    the user hand-reinstalls the application. NO_AUTO_APP_PROMPT_TARGETS names
    the releases nobody should be prompted for -- by TARGET, so it expires on
    its own rather than muting a population that then has to be remembered.

    Both halves are load-bearing and both are checked here by RUNNING the real
    guard against the real release_version and the real uservar list, not by
    grepping for it: it must suppress what it names, and it must fail towards
    ASKING for everything else, because the other direction is a device never
    told about an update it needs.
    """
    wizard_src = (WIZARD_ROOT / "resources/libs/wizard.py").read_text(
        encoding="utf-8"
    )
    uservar_src = (WIZARD_ROOT / "uservar.py").read_text(encoding="utf-8")
    config_src = (
        WIZARD_ROOT / "resources/libs/common/config.py"
    ).read_text(encoding="utf-8")

    # Both platforms call it, and both do so BEFORE their dialog.
    for call in (
        "if is_new_version_available and _auto_prompt_suppressed(\n"
        "                latest_release, kodi_version_update_check_manual):",
    ):
        assert wizard_src.count(call) == 2, (
            "both kodi_apk_update_check and kodi_windows_update_check must "
            "consult the guard before raising their dialog"
        )
    # Surfaced with a default, so an older uservar.py cannot stop the wizard
    # loading, and read through CONFIG rather than importing uservar directly.
    assert "NO_AUTO_APP_PROMPT_TARGETS" in uservar_src
    assert "getattr(\n            uservar, 'NO_AUTO_APP_PROMPT_TARGETS', [])" in config_src

    match = re.search(
        r"^def _auto_prompt_suppressed\(latest_release, manual\):"
        r"[\s\S]*?\n\n\n",
        wizard_src,
        re.M,
    )
    assert match, "cannot isolate _auto_prompt_suppressed"

    shipped = re.search(
        r"^NO_AUTO_APP_PROMPT_TARGETS = (\[[^\]]*\])", uservar_src, re.M
    )
    assert shipped, "NO_AUTO_APP_PROMPT_TARGETS must be a plain list literal"
    targets = ast.literal_eval(shipped.group(1))

    def suppressed(latest, manual, listed=targets):
        namespace = {
            "release_version": _load_release_version(),
            "logging": types.SimpleNamespace(log=lambda *a, **k: None),
            "xbmc": types.SimpleNamespace(LOGINFO=1),
            "CONFIG": types.SimpleNamespace(
                NO_AUTO_APP_PROMPT_TARGETS=listed
            ),
        }
        exec(compile(match.group(0), "guard", "exec"), namespace)
        return namespace["_auto_prompt_suppressed"](latest, manual)

    if targets:
        named = targets[0]
        assert suppressed(named, False) is True
        # Asking is always answered. A suppression that also hid the release
        # from somebody who went looking for it would be a lie, not a mute.
        assert suppressed(named, True) is False
        # Pointer files end in a newline; canonicalisation has to survive it.
        assert suppressed(named + "\n", False) is True
    # Everything not named is prompted for -- this is what makes the list
    # expire by itself when the next package actually matters.
    assert suppressed("21.3-povil.9999", False) is False
    # ...and every way the list can be malformed still asks.
    for broken in ([], None, [None, 42], "21.3-povil.49"):
        assert suppressed("21.3-povil.9999", False, broken) is False


def test_workflow_package_guards() -> None:
    workflow = (ROOT / ".github/workflows/build-apk.yml").read_text(
        encoding="utf-8"
    )
    # THE TWO ARTIFACT NAMES THE PACKAGE IS BUILT FROM, derived rather than
    # typed. The wizard's was a literal here -- correct on the day it was
    # written and needing a hand edit every release since.
    #
    # The build zip's staleness is ALREADY watched, by
    # tools/test_installer_pins_current.py, which greps the filename out of
    # this workflow and compares it with build.txt. That guard exists because
    # the pin really did rot, twice. What it cannot see is WHERE the name
    # lives: it was three copies inlined in three shell steps, so a release
    # could correct one and leave two. So this adds the half that guard has
    # no opinion about -- the name is in the env block, once, and nowhere
    # below it -- and derives both names from the same build.txt, which is
    # what a device actually reads.
    served = {}
    for line in (ROOT / "wizard/assets/build.txt").read_text(
            encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if value.strip().startswith('"'):
            served.setdefault(key.strip(), value.strip().strip('"'))
    build_zip = served["url"].rsplit("/", 1)[-1]
    wizard_zip = served["zip"].rsplit("/", 1)[-1]
    wizard_version = wizard_zip[len("plugin.program.kodipovilwizard-"):-len(".zip")]
    assert "WIZARD_VERSION: '%s'" % wizard_version in workflow, (
        "the workflow builds against a wizard build.txt does not serve; "
        "build.txt says %s" % wizard_version
    )
    assert "BUILD_ZIP: '%s'" % build_zip in workflow, (
        "the workflow builds against a full build build.txt does not serve; "
        "build.txt says %s" % build_zip
    )
    # ...and nowhere else may name one, or the single point stops being one.
    #
    # COUNTED, NOT SPLIT. This was `"...-test-" not in workflow.split(
    # "BUILD_ZIP:", 1)[1]`, and the split point sits MID-LINE: the tail begins
    # with the rest of the BUILD_ZIP assignment, whose value is a build-zip
    # filename. So the assertion searched for the very thing it had just
    # included and failed unconditionally -- masked only because the check
    # above it fails first whenever build.txt is stale. A review isolated it
    # and it raises every time. What the rule actually means is "the name
    # appears once", so count it.
    inlined = workflow.count("Kodi-POV-IL-FENtastic-test-")
    assert inlined == 1, (
        "a build-zip filename should appear exactly once, in the BUILD_ZIP "
        "env assignment; found it %d time(s)" % inlined
    )
    assert "BUILD_ZIP: '%s'" % build_zip in workflow
    assert "default: '21.3-povil.49'" in workflow
    assert "default: '2103049'" in workflow
    assert "EXPECTED_RELEASE: '21.3-povil.49'" in workflow
    assert "EXPECTED_VERSION_CODE: '2103049'" in workflow
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


def _wizard_version() -> str:
    """The version the worktree's wizard source actually declares."""
    raw = (WIZARD_ROOT / "addon.xml").read_text(encoding="utf-8")
    at = raw.find("<addon")
    match = re.search(r'\bversion="([^"]+)"', raw[at if at >= 0 else 0:])
    assert match, "no version in the wizard addon.xml"
    return match.group(1)


def test_wizard_rebuild_from_clean_checkout() -> None:
    """The surgical Wizard release must rebuild after its source is committed.

    DERIVED, NOT DECLARED. This named 0.1.46 and 0.1.47 in five places and
    rebuilt 0.1.47 out of a checkout of the CURRENT source -- so it passed
    only while the worktree still WAS 0.1.47, and failed on every release
    that bumps the wizard, with a message about a version mismatch that has
    nothing to do with what the test is for. It rebuilds whatever version the
    source declares, from whatever the manifest names as its predecessor.
    """
    version = _wizard_version()
    manifest_path = (
        ROOT
        / ("wizard/release_manifests/plugin.program.kodipovilwizard-%s.json"
           % version)
    )
    assert manifest_path.is_file(), (
        "wizard source is %s but there is no release manifest for it" % version
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous = manifest["previous_version"]
    previous_zip = (
        ROOT / ("dist/plugin.program.kodipovilwizard-%s.zip" % previous)
    )
    assert previous_zip.is_file(), "no %s to build %s from" % (previous,
                                                              version)
    # The replace list must name every source file that really differs from
    # the previous release and nothing else -- an over-broad list is how an
    # unreviewed file ships, and a short one is how a reviewed one does not.
    # Computed against the previous ZIP rather than pinned to a literal set,
    # so it cannot go stale into a false pass.
    with zipfile.ZipFile(previous_zip) as prev:
        prev_by = {i.filename: prev.read(i.filename)
                   for i in prev.infolist() if not i.filename.endswith("/")}
    changed, absent = set(), set()
    for path in sorted(WIZARD_ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        member = "plugin.program.kodipovilwizard/" + str(
            path.relative_to(WIZARD_ROOT)
        ).replace(os.sep, "/")
        if member not in prev_by:
            absent.add(member)
        elif prev_by[member] != path.read_bytes():
            changed.add(member)
    assert set(manifest["replace"]) == changed, (
        "manifest replace list does not match what actually changed;\n"
        "  missing from the manifest: %s\n"
        "  listed but unchanged:      %s"
        % (sorted(changed - set(manifest["replace"])),
           sorted(set(manifest["replace"]) - changed))
    )
    assert set(manifest["add"]) == absent, (
        "manifest add list does not match the new files: %s vs %s"
        % (sorted(manifest["add"]), sorted(absent))
    )
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
        shutil.copy2(previous_zip, clean / "dist" / previous_zip.name)
        shutil.copy2(
            ROOT / "tools/build_full_build.py",
            clean / "tools/build_full_build.py",
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
            "dist/" + previous_zip.name,
            "--manifest",
            "wizard/release_manifests/" + manifest_path.name,
            "--version",
            version,
        )
        rebuilt = (
            clean / ("dist/plugin.program.kodipovilwizard-%s.zip" % version)
        )
        assert hashlib.sha256(rebuilt.read_bytes()).hexdigest() == (
            manifest["output_sha256"]
        )


def test_pages_sync_follows_a_release() -> None:
    """The download page must refresh when the packages are rebuilt.

    deploy-pages.yml republishes the latest release's unversioned APKs into
    downloads/, and it used to wake ONLY on a push to main. build-apk.yml does
    not push to main when it rebuilds an EXISTING version -- its pointer-file
    step sees the version already recorded and exits without committing -- so
    a rebuild landed on the GitHub Release and the download page went on
    serving the previous APKs with nothing scheduled to replace them. Measured
    on 2026-08-23: packages rebuilt at 02:49 carrying build 0.1.119, and the
    live page still served the bytes from the previous build afterwards.
    """
    pages = (ROOT / ".github/workflows/deploy-pages.yml").read_text(
        encoding="utf-8"
    )
    triggers = pages.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "release:" in triggers, (
        "deploy-pages must wake on a published release, or a package rebuild "
        "that does not also push to main never reaches the download page"
    )
    assert "published" in triggers
    # and it must still do the thing that makes that matter
    assert "gh release download" in pages
    assert "Kodi-POV-IL-64bit.apk" in pages
    # the build workflow's own pointer step is what makes the gap possible --
    # pinned so that if it ever starts pushing unconditionally, whoever
    # changes it sees why this trigger exists.
    build = (ROOT / ".github/workflows/build-apk.yml").read_text(
        encoding="utf-8"
    )
    assert "Version pointer files already up to date." in build, (
        "build-apk no longer short-circuits its pointer commit; re-derive "
        "whether deploy-pages still needs the release trigger"
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
    wizard_match = re.search(r"kodipovilwizard-([0-9.]+)\.zip", build)
    assert wizard_match, "build.txt names no wizard zip"
    wizard_version = wizard_match.group(1)
    assert wizard_version == _wizard_version(), (
        "build.txt serves wizard %s but the source declares %s"
        % (wizard_version, _wizard_version())
    )

    # Accept both legal publication states:
    #   phase 1 -> artifacts/snapshot N are live while note N-1 remains live;
    #   phase 2 -> the one-file note bump makes note N live.
    note = (
        ROOT / "wizard/assets/notification_files/quick_update.txt"
    ).read_text(encoding="utf-8")
    note_id = int(note.split("|||", 1)[0])
    assert note_id in (snapshot_id - 1, snapshot_id)

    # Each release against its OWN predecessor -- DERIVED, not named. The
    # comment here already said this pair "used to be pinned to a historical
    # one and drifted"; it was then pinned to a newer one, and drifted again
    # the moment the wizard was bumped. The versions come from build.txt and
    # from the manifest's own previous_version now, so there is nothing left
    # to go stale.
    _manifest = json.loads((
        ROOT / ("wizard/release_manifests/"
                "plugin.program.kodipovilwizard-%s.json" % wizard_version)
    ).read_text(encoding="utf-8"))
    old_wizard = ROOT / ("dist/plugin.program.kodipovilwizard-%s.zip"
                         % _manifest["previous_version"])
    new_wizard = ROOT / ("dist/plugin.program.kodipovilwizard-%s.zip"
                         % wizard_version)
    latest_wizard = ROOT / "dist/plugin.program.kodipovilwizard-latest.zip"
    assert new_wizard.read_bytes() == latest_wizard.read_bytes()
    page_wizard = ROOT / ("wizard/plugin.program.kodipovilwizard-%s.zip"
                          % wizard_version)
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
        # Exactly what the manifest declared, proven from the two ZIPs rather
        # than from the manifest that asked for it. Not circular: the rebuild
        # test above proves the manifest matches the SOURCE, and this proves
        # the shipped bytes match the manifest -- source to manifest to zip,
        # with no literal in the middle to go stale on the next bump.
        assert changed == set(_manifest["replace"]), (
            "the package changed %s but the manifest declared %s"
            % (sorted(changed), sorted(_manifest["replace"]))
        )
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
    test_no_auto_app_prompt_targets()
    test_workflow_package_guards()
    test_wizard_rebuild_from_clean_checkout()
    test_pages_sync_follows_a_release()
    test_phase_one_artifacts()
    print("platform package guards: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
