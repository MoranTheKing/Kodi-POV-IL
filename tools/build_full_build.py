#!/usr/bin/env python3
"""Build the next full build from the previous one plus the current quickfix.

WHY THIS EXISTS. Every full build before this was assembled by hand, and the
release notes for 0.1.105 describe the shape without scripting it: "the build
differs from 0.1.104 only in the add-on, the wizard, both build.txt copies and
the seek bar; POV, the skin, the databases and userdata are byte-identical."
That is a surgical rebuild, and doing it by hand on the ONE artifact a fresh
install depends on -- 6,390 members, 62 MB, no way for a user to recover from
a bad one -- is how a build gets shipped that nobody can explain afterwards.

WHAT IT DOES. The quickfix is the update every existing device already
applies: our add-on, the wizard, the FENtastic skin and helper, a handful of
media and keymap files. So the new build is the previous build with exactly
those members replaced by the quickfix's bytes, plus whatever the quickfix has
that the build does not yet. Everything else -- POV, Umbrella, the other
add-ons, the databases, userdata -- is carried over untouched, because those
update through their own channels and always have.

The result is not a new configuration. It is the one every existing device is
already running: the previous build's userdata and third-party add-ons, with
the current quickfix content on top.

REFRESHING A BUNDLED THIRD-PARTY ADD-ON. `--refresh-addon ID=package.zip`
replaces one add-on's whole subtree with an upstream release. It exists
because "carried over untouched" quietly turned into "a year out of date":
the build shipped POV 5.12.04 while every device in the field was already on
6.08.13, because Kodi's own auto-update takes them there within a day of a
fresh install. So the old bundle protected nobody -- it only made a new
install spend its first hour downloading what it should have arrived with,
and ran the add-on patchers against a POV nobody actually uses.

That argument is also the safety case, and it is the same one the paragraph
above makes: shipping the version every existing device already runs is not a
new configuration. It is the one that is already in the field, reached
sooner.

This is the ONE place the tool is allowed to drop a member of the previous
build -- an upstream release removes files, and refusing that would mean
shipping a mix of two versions of somebody else's add-on, which is worse than
either. The permission is scoped to `addons/<id>/` and to nothing else.

WHAT IT REFUSES. Every deviation is named or the build stops:
  * a member the quickfix would add that is not listed with --allow-add;
  * a member that ends up matching neither the quickfix, the wizard package,
    a refresh package, nor the previous build byte-for-byte;
  * a member of the previous build that goes missing, unless it is under a
    refreshed add-on's own directory;
  * a refresh package whose top-level directory is not the id it claims, or
    that carries no addon.xml, or whose id the quickfix or wizard package
    also contains -- ours are not refreshed from upstream, and a silent
    precedence fight over one is exactly the bug this refuses to have;
  * a result that is not a valid ZIP, or whose add-on/wizard versions do not
    match what was asked for.
There is no flag to weaken any of them.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_XML = "addons/service.subtitles.kodipovilai/addon.xml"
WIZARD_XML = "addons/plugin.program.kodipovilwizard/addon.xml"
WIZARD_PREFIX = "plugin.program.kodipovilwizard/"

# THE WIZARD COMES FROM ITS OWN PACKAGE, NOT FROM THE QUICKFIX. The quickfix
# carries a copy of the wizard, and it is always one release behind: it is
# built by copying the previous quickfix and replacing the add-on subtree, so
# the wizard inside it only moves when somebody puts it there.
#
# An earlier version of this comment called that stale copy "harmless on a
# device -- the wizard excludes its own id when it extracts a quickfix". THAT
# WAS WRONG, and wrong in the direction that costs users.
#
# THE CLAIM IS `grep -c EXCLUDES extract.py` == 0. Nothing else. Three review
# rounds each corrected a different sentence that tried to say more -- first
# which files read CONFIG.EXCLUDES (four named, eight exist), then what those
# files do with it ("the paths that DELETE"; three of the four named do not
# delete), then what the three do instead ("filter a listing"; menu.py:582 does
# not filter, it relabels [PROTECTED] vs [REMOVE]). Every draft was closer and
# still wrong, because a hand-kept census of call sites rots and the conclusion
# never needed one. EXCLUDES cannot govern extraction if extraction never reads
# it, and extraction never reads it. Run the grep. extract.all()
# takes `excludes = []`; wizard.py's quick_update() calls it as
# `extract.all(lib, CONFIG.HOME, ignore=True, title=title)`, and ignore=True
# also bypasses the self-skip on the wizard's own id at extract.py:249. So a
# quick update lays its bundled wizard straight over the installed one, and
# since uservar.AUTOUPDATE is 'No' (the device log says so in as many words:
# "[Auto Update Wizard] Not Enabled") the quickfix is not merely ONE way the
# wizard reaches a device, it is the ONLY one.
#
# Which turns the staleness into a shipped defect rather than a cosmetic lag:
# quickfix 0.1.537 shipped add-on 0.2.492, whose home tile opens a wizard route
# that only 0.1.46 has, alongside wizard 0.1.45 -- so the tile landed dead on
# every device that took the update, and would have stayed dead until some
# later quickfix happened to carry a newer wizard. The fix is not in this file:
# every quickfix must now be run through build_wizard_quickfix.py as well, and
# test_quickfix_package_scope.py fails the release if it did not.
#
# AND THIS TOOL'S OUTPUT IS GATED THERE TOO, because the same review that
# corrected the paragraph above found the full build was the worse half of it:
# 0.1.105, the build every fresh install got until this release, bundled wizard
# 0.1.36 against a worktree at 0.1.46, and add-on 0.2.462 against 0.2.493 --
# the numbers, not a rounded count of releases, which drifts -- while
# startup.py's fresh-install branch recorded the newest note as already applied.
# The verify at the end of this file could not catch that and still cannot: it
# checks the result against the versions typed on the command line, and a build
# is self-consistent with a wrong answer just as happily as with a right one.
# Freshness needs the worktree to compare against, so it lives in the test.
#
# For the full build the rule was always this one, and it holds unchanged: take
# the wizard from its own package. Verified by the version check at the end --
# the first run of this tool built a 0.1.106 carrying wizard 0.1.45 and said so.


def _members(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return {info.filename: info for info in zf.infolist()}


def _wizard_map(wizard_zip):
    """The wizard package's members, under the paths a build uses.

    The ZipInfo is REBUILT with the build's path, not reused as it comes. Its
    own filename is the package's -- `plugin.program.kodipovilwizard/...`,
    with no `addons/` -- and writestr takes the name from the ZipInfo, not
    from the key you looked it up under. Reusing it wrote all 144 wizard files
    one directory too high and dropped the ones the build already had; the
    verify below said "LOST 144 member(s)" and named them.
    """
    if wizard_zip is None:
        return {}
    out = {}
    for name, info in _members(wizard_zip).items():
        if not name.startswith(WIZARD_PREFIX):
            continue
        moved = zipfile.ZipInfo(filename="addons/" + name,
                                date_time=info.date_time)
        for attr in ("compress_type", "create_system", "create_version",
                     "extract_version", "flag_bits", "internal_attr",
                     "external_attr", "volume"):
            setattr(moved, attr, getattr(info, attr))
        out["addons/" + name] = moved
    return out


def _unsafe_member(name):
    """True when a ZIP member name may not be trusted to stay where it says.

    The rules, each one paid for:

      * a backslash ANYWHERE. The ZIP spec makes `/` the one separator, so a
        backslash is either a Windows-authored bug or somebody routing around
        a `/`-only check. A review did exactly that and reached the artifact.
      * an absolute path, in either the POSIX (`/x`) or the Windows (`C:/x`,
        `\\\\server\\share`) spelling.
      * any `..` or `.` segment, which is the classic escape.
      * an empty interior segment (`a//b`), which normalises differently in
        different extractors.
      * a NUL or other control character, which truncates a path in C.

    A trailing empty segment is fine and is how a directory entry is spelt.
    """
    if not name or not name.strip("/"):
        return False                      # empty / bare-slash: skipped by caller
    if "\\" in name:
        return True
    if name.startswith("/"):
        return True
    if len(name) > 1 and name[1] == ":":
        return True
    if any(ch < " " or ch == "\x7f" for ch in name):
        return True
    # NORMALISED BEFORE COMPARING, because the segment does not have to be
    # spelt `..` to BE `..`. Windows strips trailing dots and spaces from an
    # unqualified path component, so a member named `dir/.. /outside.txt`
    # extracts as `dir/../outside.txt` there -- and `".. " == ".."` is False,
    # so it passed this check, the top-level check, build() AND verify(). A
    # review built that zip and found the member in the finished artifact.
    # Third escape found in this one function; the answer is to stop comparing
    # raw segments.
    for part in name.rstrip("/").split("/"):
        stripped = part.strip().rstrip(". ")
        if part.strip() in ("..", ".", ""):
            return True
        # `...` and `.. .` and friends: anything that is only dots and spaces
        # is a traversal on some filesystem and is never a real filename.
        if part and not stripped and set(part) <= set(". \t"):
            return True
        if part != part.strip() or part != part.rstrip("."):
            return True          # a name Windows would silently rewrite
    return False


def _is_symlink(zinfo):
    """True for a member the archive marks as a Unix symbolic link.

    This build's own extractor uses stdlib zipfile, which writes the LINK
    TARGET into an ordinary file rather than creating a link -- so today such
    a member is inert rather than dangerous. That is a property of somebody
    else's extractor, maintained for a different reason, and the same argument
    that made the `..` guard necessary applies here: refuse it in the tool
    that makes the promise.
    """
    try:
        # NOT GATED ON create_system. That field is whatever the writer put
        # there, and a review set it to 0 (FAT) while leaving Unix symlink
        # mode bits in external_attr -- which sailed through. The mode bits
        # are the thing being asked about; if they say symlink, refuse,
        # whoever claims to have written the file.
        return (zinfo.external_attr >> 16) & 0o170000 == 0o120000
    except Exception:
        return False


def _refresh_map(specs):
    """{'addons/<id>/<path>': (ZipInfo under the build's path, id)} for every
    member of every refresh package, plus {id: (Path, declared version)}.

    Like _wizard_map, the ZipInfo is REBUILT rather than reused: writestr takes
    the member name from the ZipInfo, and a package's own names have no
    `addons/` prefix. Reusing them writes the whole add-on one directory too
    high, which the verify would catch as 144 lost members -- it did once, for
    the wizard, and the note on _wizard_map records it.
    """
    members, info = {}, {}
    for addon_id, path in specs:
        try:
            zf = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as err:
            # Every other refusal in this tool is one line that names the
            # problem; this one used to be a Python traceback, because the
            # flag checked only that the path was a file.
            raise SystemExit("%s is not a readable zip: %s" % (path, err))
        with zf:
            names = zf.namelist()
            # ONE NAME PER MEMBER. _members below is a dict keyed by filename,
            # so a package with two entries at the same path silently keeps
            # the last. Whichever one that is, an input we cannot describe is
            # not one to build a release from.
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                raise SystemExit(
                    "%s has %d duplicated member name(s), so which bytes it "
                    "means is ambiguous:\n  %s"
                    % (path, len(dupes), "\n  ".join(dupes[:10])))
            # NOT `n.split("/")[0]`. That reads the FIRST segment and nothing
            # else, so `plugin.video.pov/../../userdata/guisettings.xml`
            # passed it -- first segment `plugin.video.pov` -- and was carried
            # verbatim into the one artifact a fresh install depends on. The
            # prefix checks downstream then agreed it was "inside
            # addons/plugin.video.pov/", because they compare the same
            # un-normalised string. A review built that package and watched
            # both build() and verify() accept it.
            #
            # The wizard's extractor happens to strip `..` on the way to disk,
            # which is why this was not already a disaster. That is somebody
            # else's guard, maintained for a different reason, and this tool
            # does not get to lean on it to keep its own promise.
            # AND NOT `name.split("/")` EITHER, which is where the second
            # review got in. A ZIP member name uses `/` and only `/` -- the
            # spec says so -- so `plugin.video.pov/evil\\..\\..\\..\\outside.txt`
            # is ONE segment to a `/` split, contains no segment equal to
            # `..`, and sailed through this check, the `tops` check below, and
            # both build() and verify(). A review built that zip and found the
            # member in the output artifact. On Android and Linux a backslash
            # is an ordinary filename character and the member is inert; the
            # Windows installer is built from this same artifact, and there it
            # is a live path separator and a real escape.
            #
            # So: a backslash anywhere in a member name is refused outright.
            # Nothing this build ships legitimately has one, and "refuse what
            # we do not understand" is the only rule that survives the next
            # separator somebody thinks of.
            escaped = [n for n in names if _unsafe_member(n)]
            if escaped:
                raise SystemExit(
                    "%s has %d member(s) whose path escapes its own "
                    "directory:\n  %s"
                    % (path, len(escaped), "\n  ".join(sorted(escaped)[:10])))
            folded = {}
            for n in names:
                folded.setdefault(n.lower(), []).append(n)
            clashes = sorted(v for v in folded.values() if len(v) > 1)
            if clashes:
                raise SystemExit(
                    "%s has %d member name(s) that differ only by case, which "
                    "silently shadow each other on Windows and macOS:\n  %s"
                    % (path, len(clashes),
                       "\n  ".join(" vs ".join(c) for c in clashes[:10])))
            tops = {n.split("/")[0] for n in names if n.strip("/")}
            links = sorted(n for n, zi in _members(path).items()
                           if _is_symlink(zi))
            if links:
                raise SystemExit(
                    "%s has %d symlink member(s), which this tool will not "
                    "carry into a build:\n  %s"
                    % (path, len(links), "\n  ".join(links[:10])))
            if tops != {addon_id}:
                raise SystemExit(
                    "%s does not contain exactly one top-level directory "
                    "named %s (found %s)"
                    % (path, addon_id, ", ".join(sorted(tops)) or "nothing"))
            xml = "%s/addon.xml" % addon_id
            if xml not in names:
                raise SystemExit("%s has no %s" % (path, xml))
            raw = zf.read(xml).decode("utf-8", "replace")
            at = raw.find("<addon")
            match = re.search(r'\bversion="([^"]+)"', raw[at if at >= 0 else 0:])
            if not match:
                raise SystemExit("%s: cannot read a version out of %s"
                                 % (path, xml))
            info[addon_id] = (path, match.group(1))
            for name, zinfo in _members(path).items():
                moved = zipfile.ZipInfo(filename="addons/" + name,
                                        date_time=zinfo.date_time)
                for attr in ("compress_type", "create_system", "create_version",
                             "extract_version", "flag_bits", "internal_attr",
                             "external_attr", "volume"):
                    setattr(moved, attr, getattr(zinfo, attr))
                members["addons/" + name] = (moved, addon_id)
    return members, info


def _refresh_prefixes(info):
    return tuple("addons/%s/" % addon_id for addon_id in info)


def build(previous: Path, quickfix: Path, output: Path, allow_add: set,
          wizard_zip=None, refresh=()) -> None:
    prev_by = _members(previous)
    qf_by = _members(quickfix)
    wiz_by = _wizard_map(wizard_zip)
    ref_by, ref_info = _refresh_map(refresh)
    prefixes = _refresh_prefixes(ref_info)

    # REFRESH REPLACES; IT DOES NOT INTRODUCE. Every new FILE under a
    # refreshed add-on is exempt from --allow-add, which is right for an
    # upstream release that added a module and wrong as a way to add a whole
    # add-on the build has never carried -- hundreds of files, none of them
    # reviewed, through a flag whose entire purpose elsewhere is to make each
    # one deliberate.
    unknown = sorted(addon_id for addon_id in ref_info
                     if not any(n.startswith("addons/%s/" % addon_id)
                                for n in prev_by))
    if unknown:
        raise SystemExit(
            "refusing to refresh %d add-on(s) the previous build does not "
            "contain: %s. Refresh replaces a bundled add-on; adding a new one "
            "goes through --allow-add, file by file."
            % (len(unknown), ", ".join(unknown)))

    # OURS ARE NOT REFRESHED FROM UPSTREAM. If a refreshed id also appears in
    # the quickfix or the wizard package, two sources claim the same bytes and
    # whichever this function happens to consult first wins silently. Refuse
    # instead of picking.
    clash = sorted(n for n in ref_by if n in qf_by or n in wiz_by)
    if clash:
        raise SystemExit(
            "refusing to refresh %d member(s) the quickfix or wizard package "
            "also carries -- this build's own add-ons come from there, not "
            "from upstream:\n  %s" % (len(clash), "\n  ".join(clash[:10])))

    # The wizard package wins over the quickfix's stale copy of the same file.
    qf_by = {n: i for n, i in qf_by.items() if n not in wiz_by}

    added = (set(qf_by) | set(wiz_by) | set(ref_by)) - set(prev_by)
    # Directory entries carry no bytes and no risk; a FILE appearing in the
    # build for the first time is a decision somebody has to make on purpose.
    # A file inside a REFRESHED add-on is exempt: naming every file an upstream
    # release added would be a --allow-add list hundreds long that nobody could
    # read, and the decision was already made by choosing to refresh that id.
    added_files = {n for n in added
                   if not n.endswith("/") and not n.startswith(prefixes)}
    unlisted = added_files - allow_add
    if unlisted:
        raise SystemExit(
            "refusing to add %d member(s) the previous build did not have "
            "without naming them with --allow-add:\n  %s"
            % (len(unlisted), "\n  ".join(sorted(unlisted)))
        )

    # THE ONE PLACE A MEMBER IS ALLOWED TO DISAPPEAR, and only here: an
    # upstream release deletes files, and carrying its predecessor's leftovers
    # alongside it ships a mixture of two versions of somebody else's add-on.
    dropped = {n for n in prev_by
               if n.startswith(prefixes) and n not in ref_by}

    replaced, carried, new, refreshed = 0, 0, 0, 0
    wiz = zipfile.ZipFile(wizard_zip) if wizard_zip is not None else None
    ref_zips = {addon_id: zipfile.ZipFile(path)
                for addon_id, (path, _v) in ref_info.items()}
    try:
        with zipfile.ZipFile(previous) as old, zipfile.ZipFile(quickfix) as qf:
            def source(name):
                """Where a member's bytes come from, most authoritative first."""
                if name in ref_by:
                    info, addon_id = ref_by[name]
                    return info, ref_zips[addon_id].read(name[len("addons/"):])
                if name in wiz_by:
                    return wiz_by[name], wiz.read(name[len("addons/"):])
                return qf_by[name], qf.read(name)

            def dir_info(name):
                if name in ref_by:
                    return ref_by[name][0]
                return (wiz_by if name in wiz_by else qf_by)[name]

            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
                # Previous-build order first, so a member that existed keeps
                # its place; anything genuinely new lands at the end, sorted.
                for name, info in prev_by.items():
                    if name in dropped:
                        continue
                    if name in ref_by and not name.endswith("/"):
                        i, data = source(name)
                        out.writestr(i, data)
                        refreshed += 1
                    elif (name in qf_by or name in wiz_by) and not name.endswith("/"):
                        i, data = source(name)
                        out.writestr(i, data)
                        replaced += 1
                    else:
                        out.writestr(info, old.read(name))
                        carried += 1
                for name in sorted(added):
                    if name.endswith("/"):
                        out.writestr(dir_info(name), b"")
                        new += 1
                        continue
                    i, data = source(name)
                    out.writestr(i, data)
                    if name in ref_by:
                        refreshed += 1
                    else:
                        new += 1
    finally:
        if wiz is not None:
            wiz.close()
        for zf in ref_zips.values():
            zf.close()
    # THE PROMISE, CHECKED WHERE IT IS MADE. Every gate above guards one
    # INPUT, and each was added after a review got past the previous one -- a
    # `..` segment, then a backslash, then a trailing space after `..`. This
    # checks the OUTPUT: whatever ROUTE a member took to get here -- refresh
    # package, quickfix, wizard zip, or a path nobody has thought of -- the
    # finished artifact is asked the same question.
    #
    # WHAT IT DOES NOT DO, said plainly because an earlier version of this
    # comment claimed otherwise and a review was right to call it out: it
    # calls the same _unsafe_member and _is_symlink the input gates call, so a
    # blind spot in those is a blind spot here too. It closes the ROUTE
    # problem, not the ENCODING problem. Every new encoding still has to be
    # taught to _unsafe_member -- three have been so far.
    with zipfile.ZipFile(output) as done:
        bad = sorted(n for n in done.namelist() if _unsafe_member(n))
        links = sorted(n for n in done.infolist() if _is_symlink(n))
    if bad or links:
        try:
            output.unlink(missing_ok=True)
            left = ""
        except OSError as e:
            # An antivirus lock or a permission race here used to crash with
            # the OSError instead of the intended refusal, leaving the unsafe
            # artifact on disk AND losing the message that says why.
            left = ("\n  THE UNSAFE ARTIFACT IS STILL ON DISK -- could not "
                    "delete it: %s. Delete %s by hand before shipping."
                    % (e, output))
        raise SystemExit(
            "REFUSING THE ARTIFACT and deleting it: %d unsafe name(s) and %d "
            "symlink(s) reached the output.\n  %s"
            % (len(bad), len(links),
               "\n  ".join((bad + [i.filename for i in links])[:10])) + left)

    print("wrote %s" % output)
    print("  %d replaced from the quickfix, %d carried from the previous "
          "build, %d new, %d refreshed" % (replaced, carried, new, refreshed))
    for addon_id, (path, version) in sorted(ref_info.items()):
        print("  refreshed %s -> %s (%s)" % (addon_id, version, path.name))
    if dropped:
        print("  dropped %d member(s) the refreshed release no longer has"
              % len(dropped))


def verify(previous: Path, quickfix: Path, output: Path,
           addon_version: str, wizard_version: str, wizard_zip=None,
           refresh=()) -> None:
    """Prove the result member by member. Nothing here trusts build()."""
    prev_by, qf_by, out_by = (_members(previous), _members(quickfix),
                              _members(output))
    # FIRST, AND NOT TRUSTING build()'S OWN GATE. Two reviews in a row reached
    # the artifact through an input check, and each time verify() agreed the
    # result was fine because it compared the same un-normalised strings the
    # build did. This asks the artifact directly, before anything else.
    unsafe = sorted(n for n in out_by if _unsafe_member(n))
    with zipfile.ZipFile(output) as _out:
        linked = sorted(i.filename for i in _out.infolist() if _is_symlink(i))
    if unsafe or linked:
        raise SystemExit(
            "the new build contains %d unsafe name(s) and %d symlink(s):\n  %s"
            % (len(unsafe), len(linked), "\n  ".join((unsafe + linked)[:10])))
    wiz_by = _wizard_map(wizard_zip)
    ref_by, ref_info = _refresh_map(refresh)
    prefixes = _refresh_prefixes(ref_info)
    qf_by = {n: i for n, i in qf_by.items() if n not in wiz_by}

    # A member may vanish ONLY from inside a refreshed add-on. Everywhere else
    # a disappearance is the failure this check exists to catch.
    missing = {n for n in set(prev_by) - set(out_by)
               if not n.startswith(prefixes)}
    if missing:
        raise SystemExit("the new build LOST %d member(s): %s"
                         % (len(missing), sorted(missing)[:10]))
    # ...and inside one, what survives has to be what the release has, not a
    # leftover of its predecessor.
    stale = {n for n in out_by if n.startswith(prefixes) and n not in ref_by}
    if stale:
        raise SystemExit(
            "the new build carries %d member(s) of a refreshed add-on that "
            "the release does not have: %s" % (len(stale), sorted(stale)[:10]))

    expected = ((set(prev_by) - {n for n in prev_by
                                 if n.startswith(prefixes)})
                | set(qf_by) | set(wiz_by) | set(ref_by))
    extra = set(out_by) - expected
    if extra:
        raise SystemExit("the new build has %d member(s) from nowhere: %s"
                         % (len(extra), sorted(extra)[:10]))
    if set(out_by) != expected:
        raise SystemExit(
            "member set is not previous | quickfix | wizard | refresh; "
            "%d expected member(s) are absent: %s"
            % (len(expected - set(out_by)), sorted(expected - set(out_by))[:10]))

    from_qf, from_prev, from_wiz, from_ref = 0, 0, 0, 0
    wiz = zipfile.ZipFile(wizard_zip) if wizard_zip is not None else None
    ref_zips = {addon_id: zipfile.ZipFile(path)
                for addon_id, (path, _v) in ref_info.items()}
    with zipfile.ZipFile(previous) as old, zipfile.ZipFile(quickfix) as qf, \
            zipfile.ZipFile(output) as out:
        for name in sorted(out_by):
            if name.endswith("/"):
                continue
            got = out.read(name)
            if name in ref_by:
                addon_id = ref_by[name][1]
                if got != ref_zips[addon_id].read(name[len("addons/"):]):
                    raise SystemExit(
                        "%s is in the refresh package for %s but the build "
                        "does not match it byte for byte" % (name, addon_id))
                from_ref += 1
            elif name in wiz_by:
                if got != wiz.read(name[len("addons/"):]):
                    raise SystemExit(
                        "%s is in the wizard package but the build does not "
                        "match it byte for byte" % name)
                from_wiz += 1
            elif name in qf_by:
                if got != qf.read(name):
                    raise SystemExit(
                        "%s is in the quickfix but the build does not match "
                        "it byte for byte" % name)
                from_qf += 1
            else:
                if got != old.read(name):
                    raise SystemExit(
                        "%s is not in the quickfix and yet changed from the "
                        "previous build" % name)
                from_prev += 1
        # ...and the two things a wrong build would show first.
        addon_xml = out.read(ADDON_XML).decode("utf-8")
        if 'version="%s"' % addon_version not in addon_xml:
            raise SystemExit("the add-on inside the build is not %s"
                             % addon_version)
        wizard_xml = out.read(WIZARD_XML).decode("utf-8")
        if 'version="%s"' % wizard_version not in wizard_xml:
            raise SystemExit("the wizard inside the build is not %s"
                             % wizard_version)
        # ...and each refreshed add-on carries the version its package
        # declared, read out of the BUILD rather than out of the package, so a
        # subtree that half-landed is caught here and not by a user.
        for addon_id, (_path, version) in sorted(ref_info.items()):
            xml = out.read("addons/%s/addon.xml" % addon_id).decode(
                "utf-8", "replace")
            if 'version="%s"' % version not in xml:
                raise SystemExit(
                    "%s inside the build is not %s" % (addon_id, version))

    bad = zipfile.ZipFile(output).testzip()
    if bad is not None:
        raise SystemExit("the new build has a corrupt member: %s" % bad)

    if wiz is not None:
        wiz.close()
    for zf in ref_zips.values():
        zf.close()
    print("verified %d member(s): %d byte-identical to the quickfix, %d to "
          "the wizard package, %d to a refresh package, %d to the previous "
          "build; add-on %s, wizard %s"
          % (from_qf + from_prev + from_wiz + from_ref, from_qf, from_wiz,
             from_ref, from_prev, addon_version, wizard_version))
    for addon_id, (_path, version) in sorted(ref_info.items()):
        print("  refreshed %s -> %s" % (addon_id, version))
    print("  sha256 %s" % hashlib.sha256(output.read_bytes()).hexdigest())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--previous", required=True)
    ap.add_argument("--quickfix", required=True)
    ap.add_argument("--wizard-zip", required=True,
                    help="the wizard release package; its copy of the wizard "
                         "wins over the quickfix's, which used to lag by a "
                         "release. Whether THIS build's copy is current is not "
                         "checked here -- see test_quickfix_package_scope.py")
    ap.add_argument("--output", required=True)
    ap.add_argument("--addon-version", required=True,
                    help="version the add-on inside the result must carry")
    ap.add_argument("--wizard-version", required=True,
                    help="version the wizard inside the result must carry")
    ap.add_argument("--allow-add", action="append", default=[], metavar="MEMBER",
                    help="a member the quickfix adds that the previous build "
                         "did not have (repeatable); anything unlisted aborts")
    ap.add_argument("--refresh-addon", action="append", default=[],
                    metavar="ID=PACKAGE.ZIP",
                    help="replace a bundled third-party add-on's whole "
                         "subtree with an upstream release (repeatable). The "
                         "package's single top-level directory must be ID. "
                         "This is the only way a member of the previous build "
                         "is allowed to disappear, and only inside "
                         "addons/ID/.")
    args = ap.parse_args()

    refresh = []
    for spec in args.refresh_addon:
        if "=" not in spec:
            raise SystemExit("--refresh-addon wants ID=PACKAGE.ZIP, got %r"
                             % spec)
        addon_id, _, pkg = spec.partition("=")
        addon_id = addon_id.strip()
        path = Path(pkg.strip())
        if not addon_id:
            raise SystemExit(
                "--refresh-addon %r: the add-on id before the = is empty"
                % spec)
        if not path.is_file():
            raise SystemExit("--refresh-addon %r: no such package" % spec)
        refresh.append((addon_id, path))
    seen_ids = [i for i, _p in refresh]
    if len(set(seen_ids)) != len(seen_ids):
        raise SystemExit("--refresh-addon names the same id more than once: %s"
                         % sorted(seen_ids))

    previous, quickfix = Path(args.previous), Path(args.quickfix)
    output = Path(args.output)
    if output.exists():
        raise SystemExit("%s already exists; refusing to overwrite a build"
                         % output)
    wizard_zip = Path(args.wizard_zip)
    build(previous, quickfix, output, set(args.allow_add), wizard_zip,
          refresh)
    verify(previous, quickfix, output, args.addon_version,
           args.wizard_version, wizard_zip, refresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
