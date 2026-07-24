"""Regression tests for the Wizard's automatic quick-update delivery path.

The startup module has Kodi side effects at import time, so these tests compile
only the real auto_quick_update() function from its AST and supply small fakes.
"""

import ast
import re
import sys
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


def _function_from_file(path, name, globals_dict):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    node = next(
        item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(globals_dict)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


class FakeConfig:
    BUILDNAME = "Kodi POV IL - FENtastic"

    def __init__(self, note_id="536", dismissed="true"):
        self.QUICK_UPDATE_NOTIFICATION_URL = "https://example.invalid/note"
        self.QUICK_UPDATE_NOTEID = note_id
        self.QUICK_UPDATE_NOTEDISMISS = dismissed
        self.settings = []

    def set_setting(self, key, value):
        self.settings.append((key, value))


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
    LOGERROR = 4


def _run_startup_case(install_result=True, install_error=None,
                      stored="536", remote="537", dismissed="true"):
    config = FakeConfig(stored, dismissed)
    window = FakeWindow(remote)
    logging = FakeLogging()
    events = []

    class FakeWizard:
        def quick_update(self, **kwargs):
            events.append(("install", kwargs, list(config.settings)))
            if install_error is not None:
                raise install_error
            return install_result

        def force_close_kodi_in_5_seconds(self, dialog_header):
            events.append(("close", dialog_header, list(config.settings)))

    resources = types.ModuleType("resources")
    libs = types.ModuleType("resources.libs")
    wizard_module = types.ModuleType("resources.libs.wizard")
    wizard_module.Wizard = FakeWizard
    previous = {
        name: sys.modules.get(name)
        for name in ("resources", "resources.libs", "resources.libs.wizard")
    }
    sys.modules["resources"] = resources
    sys.modules["resources.libs"] = libs
    sys.modules["resources.libs.wizard"] = wizard_module
    try:
        function = _function_from_file(
            STARTUP,
            "auto_quick_update",
            {
                "CONFIG": config,
                "window": window,
                "logging": logging,
                "xbmc": FakeXbmc,
            },
        )
        function()
    finally:
        for name, old in previous.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    return config, window, logging, events


def test_failed_install_does_not_advance():
    config, _window, _logging, events = _run_startup_case(
        install_result=False
    )
    assert config.settings == []
    assert [event[0] for event in events] == ["install"]
    assert events[0][1]["expected_note_id"] == "537"


def test_install_exception_does_not_advance():
    config, _window, _logging, events = _run_startup_case(
        install_error=RuntimeError("network")
    )
    assert config.settings == []
    assert [event[0] for event in events] == ["install"]


def test_success_advances_after_install_then_closes():
    config, _window, _logging, events = _run_startup_case()
    assert events[0][0] == "install"
    assert events[0][2] == []
    assert config.settings == [
        ("quick_update_noteid", "537"),
        ("quick_update_notedismiss", "false"),
    ]
    assert events[1][0] == "close"
    assert events[1][2] == config.settings
    assert config.QUICK_UPDATE_NOTEID == "537"
    assert config.QUICK_UPDATE_NOTEDISMISS == "false"


def test_equal_undismissed_note_only_shows_message():
    config, window, _logging, events = _run_startup_case(
        stored="537", remote="537", dismissed="false"
    )
    assert events == []
    assert config.settings == []
    assert window.shown == [
        ("maintenance", "quick_update_notification")
    ]


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
