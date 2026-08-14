"""The quick-update package must only ever contain add-ons this build owns.

Kodi extracts a quickfix straight over the add-ons folder. Anything in the
package therefore OVERWRITES whatever is on the device -- and for an add-on
that updates itself on its own schedule, like plugin.video.pov, that means
every one of our releases silently reverts part of it to whatever copy we
happened to bundle.

That is not hypothetical. Every quickfix from at least 0.1.480 to 0.1.492
carried two of POV's files:

    addons/plugin.video.pov/resources/lib/debrids/torbox_api.py
    addons/plugin.video.pov/resources/lib/debrids/torbox.py

copies from June, put back over POV's own on every quick update. It cost
nothing for weeks. Then POV 6.07.92 began reading api.defaults_to_cloud, which
the June copy does not define, and every TorBox source resolved and was then
thrown away one line later -- so choosing a source made POV run through the
whole list and finish with "no results", on every title, with nothing in the
log pointing at a file we had replaced.

So this test does not check for those two files by name. It checks the rule
they broke: the package may contain add-ons we build and nothing else.
"""

import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD_TXT = ROOT / "wizard/assets/build.txt"
WIZARD_XML_IN_TREE = (
    ROOT / "wizard/source/plugin.program.kodipovilwizard/addon.xml"
)
ADDON_XML_IN_TREE = ROOT / "addons/service.subtitles.kodipovilai/addon.xml"
WIZARD_XML_IN_PACKAGE = "addons/plugin.program.kodipovilwizard/addon.xml"
ADDON_XML_IN_PACKAGE = "addons/service.subtitles.kodipovilai/addon.xml"

# Add-ons this build produces and is therefore entitled to overwrite.
OWNED_ADDONS = {
    "service.subtitles.kodipovilai",
    "plugin.program.kodipovilwizard",
    "skin.fentastic",
    "skin.povil.nox",
    "script.fentastic.helper",
    "service.subtitles.All_Subs",
}


def _pointed_at(key):
    """The dist/ file that build.txt's `<key>=` line sends a device to.

    These used to be "the highest-numbered matching name in dist/", which is
    not the same question. dist/ accumulates: a hand-built zip, an aborted
    release, a scratch file someone forgot -- any of them with a bigger number
    than the artifact actually being shipped, and the guard would then be
    inspecting a file no device will ever download while the real one goes
    unchecked. build.txt is what the wizard fetches, so build.txt is the
    authority on which file is the release.

    It also removes the version-parsing sort, which raised ValueError on any
    name that did not end in dotted digits -- a crash mode dist/ is exactly
    untidy enough to reach."""
    text = BUILD_TXT.read_text(encoding="utf-8")
    found = re.findall(r'^%s="([^"]+)"' % re.escape(key), text, re.M)
    assert found, "build.txt has no %s= line" % key
    # findall, not search, because build.txt legitimately repeats a key: it
    # carries `version=` twice, once for the wizard block and once for the
    # build block. `gui` and `url` appear once each today, and a silent
    # first-match-wins would be the wrong answer the day that stops being
    # true -- for a key whose whole job is to name which file ships.
    assert len(found) == 1, (
        "build.txt has {0} {1}= lines; which one names the release is not a "
        "question this should answer by guessing".format(len(found), key)
    )
    name = found[0].rsplit("/", 1)[-1]
    package = DIST / name
    assert package.is_file(), (
        "build.txt sends devices to {0}, which is not in dist/. Either the "
        "artifact was never built or the pointer was flipped ahead of "
        "it.".format(name)
    )
    return package


def _latest_quickfix():
    return _pointed_at("gui")


def _shipped_full_build():
    return _pointed_at("url")


def _addon_version(xml):
    """The <addon> element's version, never the XML declaration's.

    `version="1.0"` sits in the <?xml ?> prologue of every one of these files,
    so the obvious search for `version="..."` finds it first and reports every
    package as 1.0 -- equal to itself and to everything else, which is a
    comparison that can never fail and therefore a guard that never guards."""
    match = re.search(r"<addon\b[^>]*\bversion=\"([0-9][0-9.]*)\"", xml, re.S)
    if match is None:
        raise AssertionError("no <addon version=...> found")
    return tuple(int(part) for part in match.group(1).split("."))


def _shown(version):
    return ".".join(str(part) for part in version)


def _bundled_version(package, member):
    """The version of an add-on inside a shipped package.

    Reads through an assertion rather than letting ZipFile raise: a package
    with the member missing is the most alarming answer this function has, and
    a bare KeyError does not say so. It also aborts the __main__ runner's loop
    below, which would take the other three tests in this file down with it --
    a malformed package would then reduce coverage instead of failing it."""
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert member in names, (
            "{0} does not contain {1}. A package that ships no copy of this "
            "add-on at all cannot be checked for a stale one, and is a bigger "
            "problem than the staleness.".format(package.name, member)
        )
        return _addon_version(archive.read(member).decode("utf-8"))


def test_quickfix_carries_the_current_wizard():
    """The newest quickfix must not bundle a wizard older than the worktree's.

    THIS IS THE GATE FOR A DEFECT THAT SHIPPED. A quick update is laid straight
    over the add-ons folder and nothing on that path consults CONFIG.EXCLUDES --
    extract.all() takes `excludes = []`. With uservar.AUTOUPDATE set to 'No',
    the wizard has no other way onto a device at all, so the copy inside the
    quickfix IS the wizard every user runs.

    The quickfix, though, is built by copying the previous one and replacing the
    add-on subtree, so its wizard only moves when somebody remembers to run
    build_wizard_quickfix.py too. Nobody did for 0.1.537: it shipped add-on
    0.2.492, whose home tile opens a wizard route that exists only in 0.1.46,
    next to wizard 0.1.45. The tile installed itself on every device and could
    not be opened on any of them.

    Like test_platform_packages.py, this is red between a version bump and the
    packaging commit that answers it, and that is the point -- the red is the
    reminder, and it clears when the quickfix is rebuilt with the wizard in it.
    """
    package = _latest_quickfix()
    in_tree = _addon_version(WIZARD_XML_IN_TREE.read_text(encoding="utf-8"))
    shipped = _bundled_version(package, WIZARD_XML_IN_PACKAGE)
    assert shipped >= in_tree, (
        "{0} bundles wizard {1} but the worktree is at {2}. A quick update "
        "overwrites the installed wizard with this copy and the wizard has no "
        "self-update, so shipping it would put every user back on {1}. Rebuild "
        "the quickfix through build_wizard_quickfix.py before "
        "releasing.".format(package.name, _shown(shipped), _shown(in_tree))
    )


def test_the_full_build_carries_the_current_addons():
    """The same rule for the artifact a FRESH install gets, and for both
    add-ons in it rather than just the wizard.

    The quickfix guard above closes the door existing devices come through.
    This is the other door, and it was standing wider open. A fresh install
    extracts the full build and then, at startup.py's fresh-install branch,
    calls record_quick_update_applied() with the CURRENT note id -- stamping
    the newest update as already applied. The comment there explains why: "A
    fresh install already carries the current package."

    It did not. Build 0.1.105, the one build.txt sent every new installation to
    until this release, bundled wizard 0.1.36 and add-on 0.2.462 -- ten and
    thirty releases behind. So a new user got a months-old build AND a record
    saying they were up to date, which suppressed the quick update that is the
    only thing that would have repaired it, until the note id next moved.

    Nothing detected that, because build_full_build.py's own verify only checks
    the result against the versions the operator typed on the command line: a
    build is self-consistent with a wrong answer just as happily as with a
    right one. Freshness is not a property a package can check about itself --
    it needs the worktree to compare against, which is what this test has.
    """
    package = _shipped_full_build()
    stale = []
    for label, in_tree_xml, member, tool in (
        ("wizard", WIZARD_XML_IN_TREE, WIZARD_XML_IN_PACKAGE,
         "build_wizard_package.py"),
        ("add-on", ADDON_XML_IN_TREE, ADDON_XML_IN_PACKAGE,
         "build_ai_subtitles_packages.py"),
    ):
        in_tree = _addon_version(in_tree_xml.read_text(encoding="utf-8"))
        shipped = _bundled_version(package, member)
        # Collected, not asserted one at a time. Both went stale together in
        # 0.1.105 and asserting on the first would have reported the wizard
        # and hidden the add-on -- the same serial reveal the runner below was
        # fixed for, one level down.
        if shipped < in_tree:
            stale.append("{0} {1} (worktree {2}; rebuild via {3})".format(
                label, _shown(shipped), _shown(in_tree), tool))
    assert not stale, (
        "{0} is stale: {1}. Every fresh install would get these versions AND "
        "be recorded as already up to date, so nothing would repair "
        "them.".format(package.name, "; ".join(stale))
    )


def test_quickfix_contains_only_our_addons():
    package = _latest_quickfix()
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
    found = set()
    for name in names:
        parts = name.split("/")
        if len(parts) > 2 and parts[0] == "addons" and parts[1]:
            found.add(parts[1])
    foreign = sorted(found - OWNED_ADDONS)
    assert not foreign, (
        "{0} ships add-ons the build does not own: {1}. A quick update is laid "
        "straight over the add-ons folder, so every one of these files "
        "overwrites whatever the device already had -- including newer copies "
        "the add-on installed for itself.".format(package.name, foreign)
    )


def test_quickfix_never_ships_plugin_video_pov():
    """The specific case that broke playback, kept as its own failure message
    so a regression names itself."""
    package = _latest_quickfix()
    with zipfile.ZipFile(package) as archive:
        pov = [name for name in archive.namelist() if "plugin.video.pov" in name]
    assert not pov, (
        "{0} contains plugin.video.pov members: {1}. POV updates itself; "
        "shipping any of its files reverts part of it on every quick "
        "update.".format(package.name, pov[:5])
    )


def test_the_repair_ships_povs_own_torbox_client():
    """Devices already overwritten are repaired by the add-on, so the repair
    asset has to be POV's file and not another copy of the old one."""
    asset = (
        ROOT
        / "addons/service.subtitles.kodipovilai/resources/lib"
        / "pov_repair/torbox_api.py"
    )
    assert asset.is_file(), "the TorBox repair asset is missing"
    body = asset.read_text(encoding="utf-8")
    assert "defaults_to_cloud" in body, (
        "the repair asset does not define defaults_to_cloud, so restoring it "
        "would leave the failure exactly where it was"
    )
    assert "class TorBoxAPI" in body


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    # Run every test even after one fails. The loop used to stop at the first
    # failure, so a release with two things wrong reported one, got fixed, and
    # reported the next -- a serial reveal of a set that was always knowable at
    # once. It matters most for exactly the case these guards exist for: the
    # quickfix and the full build go stale for the same reason, in the same
    # release, and seeing only the first hides half the work.
    #
    # Catch Exception, not AssertionError. The first version caught only
    # assertions, which left the guarantee true for every failure the tests
    # write themselves and false for every failure the world hands them: a
    # truncated download raises BadZipFile, a missing build.txt raises
    # FileNotFoundError, a mis-encoded addon.xml raises UnicodeDecodeError.
    # Each of those aborted the run and took the remaining tests with it --
    # the exact behaviour this loop was written to stop, reachable by exactly
    # the inputs a release goes wrong on.
    failures = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append((test.__name__, exc))
            print("FAIL - {0}\n    {1}: {2}".format(
                test.__name__, type(exc).__name__, exc))
        else:
            print("ok - {0}".format(test.__name__))
    if failures:
        print("\n{0} FAILURE(S): {1}".format(
            len(failures), ", ".join(name for name, _ in failures)))
        sys.exit(1)
    print("ALL TESTS PASSED")
