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

import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

# Add-ons this build produces and is therefore entitled to overwrite.
OWNED_ADDONS = {
    "service.subtitles.kodipovilai",
    "plugin.program.kodipovilwizard",
    "skin.fentastic",
    "skin.povil.nox",
    "script.fentastic.helper",
    "service.subtitles.All_Subs",
}


def _latest_quickfix():
    packages = sorted(
        DIST.glob("Kodi-POV-IL-FENtastic-quickfix-*.zip"),
        key=lambda p: [int(part) for part in p.stem.rsplit("-", 1)[1].split(".")],
    )
    if not packages:
        raise AssertionError("no quickfix package found in dist/")
    return packages[-1]


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
    for test in tests:
        test()
        print("ok - {0}".format(test.__name__))
    print("ALL TESTS PASSED")
