"""Regression tests for the Wizard's automatic quick-update delivery path.

The startup module has Kodi side effects at import time, so these tests compile
only the real auto_quick_update() function from its AST and supply small fakes.
"""

import ast
import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STARTUP = ROOT / "wizard/source/plugin.program.kodipovilwizard/startup.py"
CHECK = (
    ROOT
    / "wizard/source/plugin.program.kodipovilwizard/resources/libs/check.py"
)
WIZARD = (
    ROOT
    / "wizard/source/plugin.program.kodipovilwizard/resources/libs/wizard.py"
)


def _namespace_from_file(path, names, globals_dict, assignments=()):
    """Compile the named module-level functions (and any named module-level
    assignments) from `path` into ONE shared namespace, so they call each other
    exactly as they do in the real module.

    Pulling out a single function used to be enough. It stopped being enough
    when auto_quick_update() grew helpers: extracting only the entry point left
    every helper undefined, and the test failed for a reason that had nothing to
    do with the behaviour it was guarding. Worse, the alternative -- passing
    stubs for the helpers -- would have made the test pass while exercising none
    of the record-keeping the loop fix lives in."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = set(names)
    wanted_names = set(assignments)
    body = []
    for item in tree.body:
        if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name in wanted):
            body.append(item)
        elif isinstance(item, ast.Assign) and wanted_names:
            targets = {t.id for t in item.targets if isinstance(t, ast.Name)}
            if targets & wanted_names:
                body.append(item)
    missing = wanted - {n.name for n in body
                        if isinstance(n, (ast.FunctionDef,
                                          ast.AsyncFunctionDef))}
    if missing:
        raise AssertionError(
            "{0} does not define {1}".format(path, sorted(missing)))
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(globals_dict)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def _function_from_file(path, name, globals_dict):
    return _namespace_from_file(path, [name], globals_dict)[name]


class FakeConfig:
    BUILDNAME = "Kodi POV IL - FENtastic"
    ADDON_ID = "plugin.program.kodipovilwizard"

    def __init__(self, note_id="536", dismissed="true"):
        self.QUICK_UPDATE_NOTIFICATION_URL = "https://example.invalid/note"
        self.QUICK_UPDATE_NOTEID = note_id
        self.QUICK_UPDATE_NOTEDISMISS = dismissed
        self.settings = []
        self.stored = {"quick_update_noteid": note_id}
        self.writable = True

    def set_setting(self, key, value):
        self.settings.append((key, value))
        if self.writable:
            self.stored[key] = value

    def get_setting(self, key):
        return self.stored.get(key, "")


class FakeWindow:
    def __init__(self, remote_id="537"):
        self.remote_id = remote_id
        self.shown = []

    def split_notify(self, _url):
        return self.remote_id, "maintenance"

    def show_notification(self, msg, source=None):
        self.shown.append((msg, source))


class FakeLogging:
    def __init__(self):
        self.lines = []

    def log(self, message, level=None):
        self.lines.append((message, level))


class FakeXbmc:
    # Kodi's real log levels, not just the one the first version of this test
    # happened to need. A stub that carries only what today's code path uses
    # turns tomorrow's log line into a test failure that says nothing about
    # the change -- which is exactly what happened when the hot reload started
    # logging at WARNING.
    LOGDEBUG = 0
    LOGINFO = 1
    LOGWARNING = 3
    LOGERROR = 4
    LOGFATAL = 6
    LOGNONE = 7


# The functions auto_quick_update() actually calls. They are compiled from the
# real startup.py alongside it -- see _namespace_from_file.
QUICK_UPDATE_HELPERS = [
    "auto_quick_update",
    "quick_update_applied_id",
    "record_quick_update_applied",
    "_quick_update_state",
    "_quick_update_state_path",
    "_write_quick_update_state",
    "_quick_update_tries_stored",
    "_count_quick_update_try",
]


def _run_startup_case(install_result=True, install_error=None,
                      stored="536", remote="537", dismissed="true",
                      profile=None, config=None):
    config = config if config is not None else FakeConfig(stored, dismissed)
    window = FakeWindow(remote)
    logging = FakeLogging()
    events = []
    own_profile = profile is None
    profile = profile or tempfile.mkdtemp(prefix="qu-state-")

    class FakeWizard:
        def quick_update(self, **kwargs):
            events.append(("install", kwargs, list(config.settings)))
            if install_error is not None:
                raise install_error
            return install_result

        def force_close_kodi_in_5_seconds(self, dialog_header,
                                          graceful=False):
            events.append(("close", dialog_header, list(config.settings),
                           graceful))

    resources = types.ModuleType("resources")
    libs = types.ModuleType("resources.libs")
    wizard_module = types.ModuleType("resources.libs.wizard")
    wizard_module.Wizard = FakeWizard
    xbmcvfs_module = types.ModuleType("xbmcvfs")

    def translate_path(path):
        # The record lives under the wizard's own addon_data; point that at a
        # throwaway directory so the test writes a REAL file and the read-back
        # the fix depends on is a real read-back.
        prefix = "special://profile/"
        return os.path.join(profile, path[len(prefix):]) \
            if path.startswith(prefix) else path

    xbmcvfs_module.translatePath = translate_path
    previous = {
        name: sys.modules.get(name)
        for name in ("resources", "resources.libs", "resources.libs.wizard",
                     "xbmcvfs")
    }
    sys.modules["resources"] = resources
    sys.modules["resources.libs"] = libs
    sys.modules["resources.libs.wizard"] = wizard_module
    sys.modules["xbmcvfs"] = xbmcvfs_module
    try:
        namespace = _namespace_from_file(
            STARTUP,
            QUICK_UPDATE_HELPERS,
            {
                "CONFIG": config,
                "window": window,
                "logging": logging,
                "xbmc": FakeXbmc,
                "os": os,
            },
            assignments=("QUICK_UPDATE_MAX_TRIES",),
        )
        assert "QUICK_UPDATE_MAX_TRIES" in namespace, (
            "startup.py no longer caps quick-update attempts")
        namespace["auto_quick_update"]()
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
        if own_profile:
            shutil.rmtree(profile, ignore_errors=True)
    return config, window, logging, events


def _applied_settings(config):
    """Just the delivery-state writes -- the attempt counter is bookkeeping and
    is asserted on separately."""
    return [pair for pair in config.settings
            if pair[0] != "quick_update_tries"]


def test_failed_install_does_not_advance():
    config, _window, _logging, events = _run_startup_case(
        install_result=False
    )
    assert _applied_settings(config) == []
    assert [event[0] for event in events] == ["install"]
    assert events[0][1]["expected_note_id"] == "537"


def test_install_exception_does_not_advance():
    config, _window, _logging, events = _run_startup_case(
        install_error=RuntimeError("network")
    )
    assert _applied_settings(config) == []
    assert [event[0] for event in events] == ["install"]


def test_success_advances_after_install_then_closes():
    config, _window, _logging, events = _run_startup_case()
    assert events[0][0] == "install"
    assert _applied_settings(config) == [
        ("quick_update_noteid", "537"),
        ("quick_update_notedismiss", "false"),
    ]
    assert events[1][0] == "close"
    # A GRACEFUL CLOSE, NOT A KILL. The quickfix zip carries addons/, media/,
    # userdata/keymaps/ and the wizard -- no guisettings.xml and no .db -- so
    # there is nothing here that Kodi's shutdown save could overwrite, and
    # everything the user changed since Kodi started is lost without it. The
    # hard kill belongs to the build install and the skin switch, which DO
    # write those files under a running Kodi.
    assert events[1][3] is True, (
        "the quick update force-killed Kodi; every setting the user touched "
        "this session (audio passthrough is the one that got reported) is "
        "discarded unsaved"
    )
    assert config.QUICK_UPDATE_NOTEID == "537"
    assert config.QUICK_UPDATE_NOTEDISMISS == "false"
    # The attempt counter is only cleared once the record is proven to have
    # stuck -- clearing it earlier is a fresh first attempt on every startup.
    assert ("quick_update_tries", "") in config.settings
    assert config.settings.index(("quick_update_tries", "")) > \
        config.settings.index(("quick_update_noteid", "537"))


def test_equal_undismissed_note_only_shows_message():
    config, window, _logging, events = _run_startup_case(
        stored="537", remote="537", dismissed="false"
    )
    assert events == []
    assert config.settings == []
    assert window.shown == [
        ("maintenance", "quick_update_notification")
    ]


def test_repeated_failure_stops_driving_the_update():
    """The loop users hit: an update that installs, force-closes Kodi, and is
    never recorded as done gets attempted again on the next startup, for ever.
    After the cap it must stop attempting and just show the notification."""
    profile = tempfile.mkdtemp(prefix="qu-state-")
    try:
        config = FakeConfig("536", "true")
        attempts = []
        for _ in range(4):
            config.settings = []
            # Nothing is ever recorded: the install "succeeds" but the process
            # is killed before record_quick_update_applied() -- modelled here as
            # an install that reports failure, which leaves the state untouched
            # in exactly the same way.
            _cfg, window, _logging, events = _run_startup_case(
                install_result=False, profile=profile, config=config)
            attempts.append([event[0] for event in events])
        assert attempts[0] == ["install"], attempts
        assert attempts[1] == ["install"], attempts
        assert attempts[2] == [], attempts
        assert attempts[3] == [], attempts
        assert window.shown == [("maintenance", "quick_update_notification")]
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def test_unrecordable_state_never_starts_the_update():
    """If neither store can be written, the update must not run at all: it
    would install, force-close Kodi, and be found waiting again next start."""
    profile = os.path.join(tempfile.mkdtemp(prefix="qu-state-"), "nope")
    config = FakeConfig("536", "true")
    config.writable = False          # setting writes are silently dropped
    open(profile, "w").close()       # a FILE where the folder must go
    try:
        _cfg, window, _logging, events = _run_startup_case(
            profile=profile, config=config)
        assert events == [], events
        assert window.shown == [("maintenance", "quick_update_notification")]
    finally:
        shutil.rmtree(os.path.dirname(profile), ignore_errors=True)


def test_file_record_alone_is_enough_to_advance():
    """The setting store is the one that gets lost when the update replaces the
    wizard's own files mid-run. The file record must carry it on its own."""
    profile = tempfile.mkdtemp(prefix="qu-state-")
    try:
        config = FakeConfig("536", "true")
        config.writable = False
        _cfg, _window, _logging, events = _run_startup_case(
            profile=profile, config=config)
        assert [event[0] for event in events] == ["install", "close"], events
        # ...and the next startup must NOT run it again.
        config2 = FakeConfig("536", "true")
        config2.writable = False
        _cfg, window2, _logging, events2 = _run_startup_case(
            profile=profile, config=config2)
        assert events2 == [], events2
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def test_versioned_manifest_path():
    seen = []

    class Config:
        BUILDFILE = "https://example.invalid/build.txt"

    class Response:
        text = (
            'name="Kodi POV IL - FENtastic" version="0.1.101" '
            'url="https://example.invalid/full.zip" minor="https://" '
            'gui="https://example.invalid/qf.zip" kodi="21.0" '
            'theme="http://" icon="i" fanart="f" preview="http://" '
            'adult="no" info="http://" description="d"'
        )

    tools_module = types.ModuleType("resources.libs.common.tools")

    def open_url(url):
        seen.append(url)
        return Response()

    tools_module.open_url = open_url
    resources = types.ModuleType("resources")
    libs = types.ModuleType("resources.libs")
    common = types.ModuleType("resources.libs.common")
    common.tools = tools_module
    previous = {
        name: sys.modules.get(name)
        for name in (
            "resources",
            "resources.libs",
            "resources.libs.common",
            "resources.libs.common.tools",
        )
    }
    sys.modules["resources"] = resources
    sys.modules["resources.libs"] = libs
    sys.modules["resources.libs.common"] = common
    sys.modules["resources.libs.common.tools"] = tools_module
    try:
        function = _function_from_file(
            CHECK, "check_build", {"CONFIG": Config, "re": re}
        )
        assert (
            function(
                "Kodi POV IL - FENtastic", "gui", release_id="537"
            )
            == "https://example.invalid/qf.zip"
        )
        assert (
            function(
                "Kodi POV IL - FENtastic", "gui", release_id="../537"
            )
            is False
        )
        assert (
            function(
                "Kodi POV IL - FENtastic", "gui", release_id="٥٣٧"
            )
            is False
        )
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    assert seen == [
        "https://example.invalid/build_versions/537.txt"
    ]


def test_extraction_result_guard():
    function = _function_from_file(
        WIZARD, "_quick_update_extract_ok", {}
    )
    assert function((100, 0, "")) is True
    assert function((99, 0, "")) is False
    assert function((100, 1, "one failed member")) is False
    assert function((0, 1, "bad zip")) is False
    assert function(None) is False


def test_wizard_forwards_expected_note_id():
    tree = ast.parse(WIZARD.read_text(encoding="utf-8"), filename=str(WIZARD))
    wizard_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Wizard"
    )
    method = next(
        node
        for node in wizard_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "quick_update"
    )
    calls = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "check_build"
    ]
    assert len(calls) == 2  # gui URL + build version after extraction
    gui_call = calls[0]
    keywords = {item.arg: item.value for item in gui_call.keywords}
    assert "release_id" in keywords
    assert isinstance(keywords["release_id"], ast.Name)
    assert keywords["release_id"].id == "expected_note_id"
    guard_calls = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_quick_update_extract_ok"
    ]
    assert len(guard_calls) == 1


def test_application_package_update_marker_gate():
    """Legacy auto checks stay quiet; manual and marked checks remain active."""
    startup_source = STARTUP.read_text(encoding="utf-8")
    startup_tree = ast.parse(startup_source, filename=str(STARTUP))
    startup_calls = [
        node
        for node in ast.walk(startup_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "kodi_version_update_check"
    ]
    assert len(startup_calls) == 1

    router = (
        ROOT
        / "wizard/source/plugin.program.kodipovilwizard/"
        "resources/libs/common/router.py"
    )
    router_source = router.read_text(encoding="utf-8")
    assert "action == 'kodi_version_update_check'" in router_source
    assert "kodi_version_update_check(kodi_version_update_check_manual)" in (
        router_source
    )

    wizard_tree = ast.parse(
        WIZARD.read_text(encoding="utf-8"),
        filename=str(WIZARD),
    )
    functions = {
        node.name
        for node in ast.walk(wizard_tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert {
        "kodi_version_update_check",
        "kodi_apk_update_check",
        "kodi_windows_update_check",
    } <= functions

    class Config:
        ADDONTITLE = "Kodi POV IL"
        APK_PACKAGE_IDS = ("il.co.povil",)
        WINDOWS_INSTALLATION_PATH = r"C:\Program Files\Kodi POV IL"

    class Tools:
        @staticmethod
        def platform():
            return "android"

    class XbmcGui:
        class Dialog:
            def ok(self, *_args, **_kwargs):
                raise AssertionError("unexpected dialog")

    class Xbmc:
        LOGINFO = 1

    def run_case(manual, marker):
        events = []

        def marked_release():
            events.append(("marker", marker))
            return marker

        def custom_check(package):
            events.append(("custom", package))
            return True

        def apk_check(is_manual, label):
            events.append(("apk", is_manual, label))

        function = _function_from_file(
            WIZARD,
            "kodi_version_update_check",
            {
                "CONFIG": Config,
                "tools": Tools,
                "xbmcgui": XbmcGui,
                "xbmc": Xbmc,
                "logging": FakeLogging(),
                "_marked_platform_release": marked_release,
                "check_if_running_custom_kodi": custom_check,
                "kodi_apk_update_check": apk_check,
            },
        )
        function(manual)
        return events

    assert run_case("false", None) == [("marker", None)]
    assert run_case("true", None) == [
        ("custom", "il.co.povil"),
        ("apk", True, "Android"),
    ]
    assert run_case("false", "21.3-povil.48") == [
        ("marker", "21.3-povil.48"),
        ("custom", "il.co.povil"),
        ("apk", False, "Android"),
    ]


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
