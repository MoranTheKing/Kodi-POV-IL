"""Kodi POV IL application-release version helpers.

Kodi's core version (for example 21.3) is not enough to distinguish two POV IL
packages built from the same upstream Kodi release.  Platform packages therefore
carry a marker such as ``21.3-povil.48`` and the public pointer files use the
same format.

This module deliberately has no Kodi imports so the comparison rules can be
tested outside Kodi and reused by every platform update check.
"""

import re


_RELEASE_PATTERN = re.compile(
    r"^\s*([0-9]+)\.([0-9]+)-povil\.([0-9]+)\s*$",
    re.IGNORECASE,
)


def parse_release_label(value):
    """Return ``(Kodi major, Kodi minor, POV release)`` for a release label."""
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    match = _RELEASE_PATTERN.fullmatch(str(value))
    if not match:
        raise ValueError("invalid Kodi POV IL release label: {!r}".format(value))
    return tuple(int(part) for part in match.groups())


def canonical_release_label(value):
    """Validate and normalize a release label."""
    major, minor, release = parse_release_label(value)
    return "{}.{}-povil.{}".format(major, minor, release)


def is_newer_release(latest, installed):
    """Return whether *latest* is strictly newer than *installed*."""
    return parse_release_label(latest) > parse_release_label(installed)
