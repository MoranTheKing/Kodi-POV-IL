#!/usr/bin/env python3
"""A fresh install must survive the wizard's own startup script.

THE OUTAGE THIS EXISTS FOR. The hot-reload heal pass was placed at the top of
startup.py, before tools.ensure_folders(), so that nothing could need a
disabled add-on before it was switched back on. Importing
resources.libs.wizard pulls in extract -> custom_save_data_config, which logs
one line at IMPORT time, and logging.log opens the wizard log with 'w+'. On a
fresh install userdata/addon_data/plugin.program.kodipovilwizard does not
exist yet, so that open raised FileNotFoundError out of an import statement --
and the except handler logged too, and raised again. startup.py died before it
reached a single line of work. Nobody could install the build.

Two things have to stay true, and neither is visible by reading the diff of a
later change, which is why they are asserted here.
"""

import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / "wizard/source/plugin.program.kodipovilwizard"


def test_folders_are_created_before_the_wizard_module_is_imported():
    """Order, in the file, not in a comment."""
    body = (WIZARD / "startup.py").read_text(encoding="utf-8")
    ensure = body.index("\ntools.ensure_folders()")
    heal_import = body.index("from resources.libs.wizard import Wizard as "
                             "_HealWizard")
    assert ensure < heal_import, (
        "startup.py imports resources.libs.wizard before creating the wizard's "
        "addon_data folder. That import logs, logging writes a file in that "
        "folder, and on a fresh install the folder does not exist yet -- which "
        "is the crash that stopped every new installation."
    )


def test_the_heal_fallback_does_not_log_through_the_file_logger():
    """The handler for "the log file could not be written" must not write it."""
    body = (WIZARD / "startup.py").read_text(encoding="utf-8")
    start = body.index("from resources.libs.wizard import Wizard as "
                        "_HealWizard")
    lines = body[start:].splitlines()
    handler_lines = []
    inside = False
    for line in lines:
        if line.startswith("except Exception as _heal_err"):
            inside = True
            continue
        if inside:
            # The block ends at the first line back at column zero.
            if line.strip() and not line[:1].isspace():
                break
            handler_lines.append(line)
    # Code only: the block's own comment says the words "logging.log" while
    # explaining why it must not call it.
    handler = "\n".join(line for line in handler_lines
                        if not line.lstrip().startswith("#"))
    assert handler.strip(), "could not find the heal fallback handler"
    assert "logging.log" not in handler, (
        "the heal pass falls back to logging.log, which is the very thing that "
        "can raise here; it must use xbmc.log"
    )


def test_log_survives_a_missing_addon_data_folder(tmp=None):
    """The logger creates its folder and never raises at the caller."""
    import tempfile

    workdir = tempfile.mkdtemp()
    missing = os.path.join(workdir, "addon_data",
                           "plugin.program.kodipovilwizard")
    assert not os.path.isdir(missing)

    logged = []

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING = 0, 1, 2
    xbmc.LOGERROR, xbmc.LOGFATAL, xbmc.LOGNONE = 3, 4, 5
    xbmc.log = lambda msg, level=0: logged.append(msg)
    xbmcgui = types.ModuleType("xbmcgui")
    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda p: p
    saved = {name: sys.modules.get(name)
             for name in ("xbmc", "xbmcgui", "xbmcvfs")}
    sys.modules.update({"xbmc": xbmc, "xbmcgui": xbmcgui, "xbmcvfs": xbmcvfs})

    try:
        source = (WIZARD / "resources/libs/common/logging.py").read_text(
            encoding="utf-8")
        body = source[source.index("def log(msg"):]
        body = body[:body.index("\ndef check_log")]
        namespace = {
            "xbmc": xbmc,
            "os": os,
            "time": __import__("time"),
            "CONFIG": types.SimpleNamespace(
                DEBUGLEVEL="1", ADDONTITLE="t", ENABLEWIZLOG="true",
                CLEANWIZLOG="false", NEXTCLEANDATE=0,
                WIZLOG=os.path.join(missing, "wizard.log")),
            "tools": types.SimpleNamespace(
                get_date=lambda formatted=False, days=0: (
                    "2026-01-01 00:00:00" if formatted else 0),
                write_to_file=lambda path, line, mode="w": open(
                    path, mode, encoding="utf-8").write(line)),
        }
        exec(compile(body, "logging.py", "exec"), namespace)
        namespace["log"]("hello", level=1)          # must not raise
        assert os.path.isfile(os.path.join(missing, "wizard.log")), (
            "log() did not create its own folder"
        )
        assert any("hello" in m for m in logged), "the Kodi log line was lost"
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


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
