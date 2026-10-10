import ctypes
import sys
import threading
from contextlib import nullcontext
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import jarvis.chrome as chrome


class FakeUI:
    def __init__(self):
        self.events = []
        self.text = ""
        self.focused = True
        self.token = object()

    def focus(self):
        self.events.append("focus")
        return self.token

    def write(self, token, text):
        assert token is self.token
        if not self.focused:
            raise RuntimeError("lost focus")
        self.text = text
        self.events.append(("write", text))

    def read(self, token):
        assert token is self.token
        if not self.focused:
            raise RuntimeError("lost focus")
        self.events.append("read")
        return self.text

    def submit(self, token):
        assert token is self.token
        if not self.focused:
            raise RuntimeError("lost focus")
        self.events.append("submit")


@pytest.fixture
def browser(monkeypatch):
    monkeypatch.setattr(chrome, "IS_WINDOWS", True)
    monkeypatch.setattr(chrome, "_com_apartment", nullcontext)
    browser = chrome.Chrome(SimpleNamespace())
    browser._backend = FakeUI()
    browser.launched = []
    monkeypatch.setattr(chrome, "_chrome_executable", lambda apps: "C:/Chrome/chrome.exe")
    monkeypatch.setattr(chrome.subprocess, "Popen",
                        lambda args, **kwargs: browser.launched.append((args, kwargs)))
    return browser


def test_search_launches_unicode_literal_query_in_real_chrome_without_typing(browser):
    text = "café 東京 🐱 {ENTER} ^l + % (test)"
    assert text in browser.search(text)
    assert not browser._backend.events
    args, options = browser.launched[0]
    assert args[0] == "C:/Chrome/chrome.exe"
    url = urlsplit(args[1])
    assert url.scheme == "https" and url.netloc == "www.google.com"
    assert url.path == "/search" and parse_qs(url.query) == {"q": [text]}
    assert len(args) == 2 and not options.get("shell")


def test_standalone_search_does_not_load_automation_or_winrt(browser, monkeypatch):
    browser._backend = None

    def unavailable():
        raise AssertionError("UI Automation must not load for a URL launch")

    monkeypatch.setattr(chrome, "_com_apartment", unavailable)
    monkeypatch.setattr(browser, "_ui", unavailable)
    browser.search("https://example.com/?private=true&other=false")
    assert len(browser.launched) == 1
    assert parse_qs(urlsplit(browser.launched[0][0][1]).query) == {
        "q": ["https://example.com/?private=true&other=false"],
    }


def test_standalone_query_cannot_inject_flags_or_shell_commands(browser):
    text = '--incognito "hello" & calc.exe | powershell $(whoami)'
    browser.search(text)
    args = browser.launched[0][0]
    assert len(args) == 2
    assert parse_qs(urlsplit(args[1]).query) == {"q": [text]}


def test_direct_chrome_launch_failure_is_actionable(browser, monkeypatch):
    def launch(*args, **kwargs):
        raise OSError("executable unavailable")

    monkeypatch.setattr(chrome.subprocess, "Popen", launch)
    with pytest.raises(RuntimeError, match="couldn't launch Google Chrome"):
        browser.search("weather")
    assert not browser._backend.events


def test_dictation_is_raw_and_does_not_submit(browser):
    text = "weather in Sydney"
    browser.type_search(text)
    assert browser._backend.events == ["focus", ("write", text), "read"]
    browser.submit_search()
    assert browser._backend.events[-4:] == ["read", ("write", "? " + text), "read", "submit"]
    with pytest.raises(RuntimeError, match="first"):
        browser.submit_search()


def test_searching_dictated_query_submits_same_omnibox_without_refocusing(browser):
    text = "Café 東京 {ENTER}"
    browser.type_search(text)
    assert text in browser.search(text)
    assert browser._backend.events == [
        "focus", ("write", text), "read", "read", ("write", "? " + text),
        "read", "submit",
    ]
    with pytest.raises(RuntimeError, match="first"):
        browser.submit_search()


def test_matching_query_does_not_overwrite_user_edits(browser):
    browser.type_search("original query")
    browser._backend.text = "the user's replacement"
    with pytest.raises(RuntimeError, match="changed"):
        browser.search("original query")
    assert browser._backend.text == "the user's replacement"
    assert browser._backend.events.count("focus") == 1
    assert "submit" not in browser._backend.events
    with pytest.raises(RuntimeError, match="first"):
        browser.submit_search()


def test_matching_query_cannot_refocus_after_user_switches_apps(browser):
    browser.type_search("original query")
    browser._backend.focused = False
    with pytest.raises(RuntimeError, match="focus"):
        browser.search("original query")
    assert browser._backend.events.count("focus") == 1
    assert "submit" not in browser._backend.events


def test_different_query_starts_a_new_chrome_search(browser):
    browser.type_search("first query")
    browser.search("second query")
    assert browser._backend.events.count("focus") == 1
    assert browser._backend.text == "first query"
    assert parse_qs(urlsplit(browser.launched[0][0][1]).query) == {"q": ["second query"]}
    with pytest.raises(RuntimeError, match="first"):
        browser.submit_search()


def test_web_address_is_searched_instead_of_navigated(browser):
    browser.type_search("https://example.com/private")
    browser.submit_search()
    assert browser._backend.text == "? https://example.com/private"


@pytest.mark.parametrize("text", ["", "  ", "one\ntwo", "\ntext", "text\n", "text\tvalue",
                                  "text\0", "text\x7f", "text\u2028value", "x" * 1001,
                                  "javascript:alert(1)", "chrome://settings", "file:///secret",
                                  "data:text/html,hi", "shell:AppsFolder", "spotify:track:123",
                                  "\ud800", None])
def test_invalid_text_does_not_touch_desktop(browser, text):
    with pytest.raises(ValueError):
        browser.search(text)
    assert not browser._backend.events
    assert not browser.launched


def test_changed_text_is_not_submitted(browser):
    browser.type_search("original query")
    browser._backend.text = "different query"
    with pytest.raises(RuntimeError, match="changed"):
        browser.submit_search()
    assert "submit" not in browser._backend.events
    with pytest.raises(RuntimeError, match="first"):
        browser.submit_search()


def test_focus_loss_is_not_reactivated_for_pending_submit(browser):
    browser.type_search("original query")
    browser._backend.focused = False
    with pytest.raises(RuntimeError, match="focus"):
        browser.submit_search()
    assert browser._backend.events.count("focus") == 1
    assert "submit" not in browser._backend.events


def test_incomplete_typing_is_not_submitted(browser, monkeypatch):
    monkeypatch.setattr(browser._backend, "read", lambda token: "partial")
    with pytest.raises(RuntimeError, match="complete"):
        browser.type_search("the entire query")
    assert "submit" not in browser._backend.events
    with pytest.raises(RuntimeError, match="first"):
        browser.submit_search()


def test_delayed_chrome_event_processing_is_polled_after_dictation(browser, monkeypatch):
    values = iter(["old URL", "wea", "weather"])
    reads = []

    def read(token):
        value = next(values)
        reads.append(value)
        return value

    monkeypatch.setattr(browser._backend, "read", read)
    monkeypatch.setattr(chrome.time, "sleep", lambda seconds: None)
    browser.type_search("weather")
    assert reads == ["old URL", "wea", "weather"]
    assert "submit" not in browser._backend.events


def test_transient_address_bar_value_failure_is_retried_after_typing(browser, monkeypatch):
    original_read = browser._backend.read
    attempts = []

    def read(token):
        attempts.append(True)
        if len(attempts) == 1:
            raise chrome._AddressBarUnavailable("Value pattern not ready")
        return original_read(token)

    monkeypatch.setattr(browser._backend, "read", read)
    monkeypatch.setattr(chrome.time, "sleep", lambda seconds: None)
    browser.type_search("weather")
    assert len(attempts) == 2
    assert "submit" not in browser._backend.events
    browser.submit_search()
    assert browser._backend.events[-1] == "submit"


def test_transient_pending_value_failure_does_not_trigger_refocus(browser, monkeypatch):
    browser.type_search("weather")
    original_read = browser._backend.read
    attempts = []

    def read(token):
        attempts.append(True)
        if len(attempts) == 1:
            raise chrome._AddressBarUnavailable("Value pattern not ready")
        return original_read(token)

    monkeypatch.setattr(browser._backend, "read", read)
    monkeypatch.setattr(chrome.time, "sleep", lambda seconds: None)
    browser.submit_search()
    assert browser._backend.events.count("focus") == 1
    assert browser._backend.events[-1] == "submit"


def test_value_read_retry_does_not_hide_focus_loss(browser, monkeypatch):
    browser.type_search("weather")
    attempts = []

    def read(token):
        attempts.append(True)
        if len(attempts) == 1:
            raise chrome._AddressBarUnavailable("Value pattern not ready")
        raise RuntimeError("Chrome lost focus")

    monkeypatch.setattr(browser._backend, "read", read)
    monkeypatch.setattr(chrome.time, "sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="lost focus"):
        browser.submit_search()
    assert len(attempts) == 2
    assert browser._backend.events.count("focus") == 1
    assert "submit" not in browser._backend.events


def test_invalid_new_dictation_clears_previous_pending_text(browser):
    browser.type_search("old query")
    with pytest.raises(ValueError):
        browser.type_search("invalid\nquery")
    with pytest.raises(RuntimeError, match="first"):
        browser.submit_search()


def test_invalid_follow_up_search_clears_previous_pending_text(browser):
    browser.type_search("old query")
    with pytest.raises(ValueError):
        browser.search("javascript:alert(1)")
    assert "submit" not in browser._backend.events
    with pytest.raises(RuntimeError, match="first"):
        browser.submit_search()


def test_chrome_consumed_search_marker_is_supported(browser, monkeypatch):
    browser.type_search("weather")
    monkeypatch.setattr(browser._backend, "read", lambda token: browser._backend.text.removeprefix("? "))
    browser.submit_search()
    assert browser._backend.events[-1] == "submit"


def test_non_windows_fails_without_launching(browser, monkeypatch):
    monkeypatch.setattr(chrome, "IS_WINDOWS", False)
    with pytest.raises(RuntimeError, match="Windows"):
        browser.search("weather")
    assert not browser._backend.events
    assert not browser.launched


def element(control="Edit", name="Address and search bar", class_name="", parent=None):
    info = SimpleNamespace(control_type=control, name=name, class_name=class_name,
                           automation_id="", process_id=100)
    return SimpleNamespace(element_info=info, parent=lambda: parent)


def test_omnibox_requires_browser_ancestry_and_rejects_web_form():
    window = element(control="Pane", class_name="Chrome_WidgetWin_1")
    toolbar = element(control="ToolBar", parent=window)
    assert chrome._WindowsChrome._is_omnibox(element(parent=toolbar))
    document = element(control="Document", parent=window)
    assert not chrome._WindowsChrome._is_omnibox(element(parent=document))
    assert not chrome._WindowsChrome._is_omnibox(element(name="Password", parent=toolbar))
    assert not chrome._WindowsChrome._is_omnibox(element())


def test_omnibox_class_marker_supports_non_english_chrome():
    window = element(control="Window", class_name="Chrome_WidgetWin_1")
    toolbar = element(control="ToolBar", parent=window)
    assert chrome._WindowsChrome._is_omnibox(
        element(name="Adress- und Suchleiste", class_name="OmniboxViewViews", parent=toolbar))
    document = element(control="Document", parent=window)
    assert not chrome._WindowsChrome._is_omnibox(
        element(name="Adress- und Suchleiste", class_name="OmniboxViewViews", parent=document))


def test_window_guard_rejects_another_foreground_app(monkeypatch):
    ui = object.__new__(chrome._WindowsChrome)
    ui.keyboard = SimpleNamespace(user32=SimpleNamespace(GetForegroundWindow=lambda: 456))
    token = chrome._Omnibox(100, 123, (1,))
    with pytest.raises(RuntimeError, match="lost focus"):
        ui._require_window(token)


def test_omnibox_guard_checks_process_and_runtime_identity(monkeypatch):
    ui = object.__new__(chrome._WindowsChrome)
    monkeypatch.setattr(ui, "_require_window", lambda token: None)
    current = element(parent=element(control="Window"))
    monkeypatch.setattr(ui, "_focused_edit", lambda: current)
    monkeypatch.setattr(ui, "_identity", lambda edit: (1,))
    token = chrome._Omnibox(100, 123, (2,))
    with pytest.raises(RuntimeError, match="address bar lost focus"):
        ui._require_omnibox(token)
    current.element_info.process_id = 200
    token = chrome._Omnibox(100, 123, (1,))
    with pytest.raises(RuntimeError, match="address bar lost focus"):
        ui._require_omnibox(token)


def test_native_omnibox_read_error_is_retryable_without_restoring_focus(monkeypatch):
    class NativeCOMError(Exception):
        pass

    ui = object.__new__(chrome._WindowsChrome)
    ui._uia_errors = (NativeCOMError, chrome._AddressBarUnavailable)
    guards = []
    monkeypatch.setattr(ui, "_require_window", lambda token: guards.append(token))

    def unavailable():
        raise NativeCOMError("provider busy")

    monkeypatch.setattr(ui, "_focused_edit", unavailable)
    token = chrome._Omnibox(100, 123, (1,))
    with pytest.raises(chrome._AddressBarUnavailable):
        ui.read(token)
    assert guards == [token]


def test_shortcut_resolves_only_chrome_executable(tmp_path, monkeypatch):
    executable = tmp_path / "chrome.exe"
    executable.write_text("")
    shortcut = tmp_path / "Google Chrome.lnk"
    shortcut.write_text("")
    ui = object.__new__(chrome._WindowsChrome)
    ui.apps = SimpleNamespace(lock=threading.RLock(), entries={"google chrome": str(shortcut)})
    calls = []

    def resolve(script, input_text, timeout):
        calls.append(input_text)
        assert str(shortcut) not in script
        return str(executable)

    monkeypatch.setattr(chrome, "powershell", resolve)
    assert ui._executable() == str(executable)
    assert calls == [str(shortcut)]


def test_executable_discovery_checks_both_windows_registry_views(tmp_path, monkeypatch):
    executable = tmp_path / "chrome.exe"
    executable.write_text("")
    reads = []

    def open_key(hive, path, reserved, access):
        reads.append((hive, access))
        if hive == "machine" and access == 5:
            return nullcontext("registered Chrome")
        raise OSError("not registered in this view")

    registry = SimpleNamespace(
        HKEY_CURRENT_USER="user", HKEY_LOCAL_MACHINE="machine",
        KEY_READ=1, KEY_WOW64_64KEY=2, KEY_WOW64_32KEY=4,
        OpenKey=open_key, QueryValue=lambda key, name: str(executable),
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(chrome.psutil, "process_iter", lambda attrs: [])
    apps = SimpleNamespace(lock=threading.RLock(), entries={})
    assert chrome._chrome_executable(apps) == str(executable)
    assert reads == [("user", 3), ("user", 5), ("machine", 3), ("machine", 5)]


def test_running_portable_chrome_is_discovered(tmp_path, monkeypatch):
    executable = tmp_path / "chrome.exe"
    executable.write_text("")
    monkeypatch.setattr(chrome.psutil, "process_iter", lambda attrs: [
        SimpleNamespace(info={"name": "other.exe", "exe": str(executable)}),
        SimpleNamespace(info={"name": "chrome.exe", "exe": str(executable)}),
    ])
    apps = SimpleNamespace(lock=threading.RLock(), entries={})
    assert chrome._chrome_executable(apps) == str(executable)


def test_chrome_discovery_never_accepts_other_executable_shortcut(tmp_path, monkeypatch):
    executable = tmp_path / "powershell.exe"
    executable.write_text("")
    shortcut = tmp_path / "Google Chrome.lnk"
    shortcut.write_text("")
    monkeypatch.setattr(chrome, "powershell", lambda *args, **kwargs: str(executable))
    monkeypatch.setattr(chrome.psutil, "process_iter", lambda attrs: [])
    monkeypatch.setattr(chrome.shutil, "which", lambda name: None)
    apps = SimpleNamespace(lock=threading.RLock(), entries={"google chrome": str(shortcut)})
    with pytest.raises(RuntimeError, match="couldn't find Google Chrome"):
        chrome._chrome_executable(apps)


def test_native_chrome_focus_waits_for_activation_and_accessibility(monkeypatch):
    ui = object.__new__(chrome._WindowsChrome)
    ui._uia_errors = (chrome._AddressBarUnavailable,)
    foreground = [999]
    sleeps = []
    keys = []
    ui.keyboard = SimpleNamespace(user32=SimpleNamespace(GetForegroundWindow=lambda: foreground[0]))
    window = SimpleNamespace(handle=123, process_id=lambda: 100, set_focus=lambda: None)
    monkeypatch.setattr(ui, "_find_window", lambda: window)
    monkeypatch.setattr(chrome.psutil, "Process", lambda pid: SimpleNamespace(exe=lambda: "chrome.exe"))
    current = element(class_name="OmniboxViewViews", parent=element(control="Window"))
    current.element_info.element = SimpleNamespace(GetRuntimeId=lambda: (1, 2))
    attempts = []

    def focused():
        attempts.append(True)
        if len(attempts) == 1:
            raise chrome._AddressBarUnavailable("Ctrl+L still processing")
        return current

    def sleep(seconds):
        sleeps.append(seconds)
        foreground[0] = 123

    def hotkey(sequence, guard):
        guard()
        keys.append(sequence)

    ui.keyboard.hotkey = hotkey
    monkeypatch.setattr(ui, "_focused_edit", focused)
    monkeypatch.setattr(chrome.time, "sleep", sleep)
    assert ui.focus() == chrome._Omnibox(100, 123, (1, 2))
    assert keys == [[0x11, 0x4C]]
    assert len(sleeps) == 2 and len(attempts) == 2


def test_native_focus_denial_never_sends_global_keys(monkeypatch):
    ui = object.__new__(chrome._WindowsChrome)
    calls = []
    ui.keyboard = SimpleNamespace(
        user32=SimpleNamespace(GetForegroundWindow=lambda: 999),
        hotkey=lambda *args: calls.append(args),
    )
    window = SimpleNamespace(handle=123, process_id=lambda: 100, set_focus=lambda: None)
    monkeypatch.setattr(ui, "_find_window", lambda: window)
    times = iter([0, .5, 1, 2])
    monkeypatch.setattr(chrome.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(chrome.time, "sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="active window"):
        ui.focus()
    assert not calls


def test_automation_import_failure_reports_actual_native_error(browser, monkeypatch):
    browser._backend = None

    def unavailable(apps):
        raise ImportError("missing native automation DLL")

    monkeypatch.setattr(chrome, "_WindowsChrome", unavailable)
    with pytest.raises(RuntimeError, match="missing native automation DLL"):
        browser.type_search("weather")
    assert not browser.launched
    browser.search("weather")
    assert len(browser.launched) == 1


def test_enter_guard_rechecks_literal_text_immediately_before_input(monkeypatch):
    ui = object.__new__(chrome._WindowsChrome)
    token = chrome._Omnibox(100, 123, (1,))
    ui._written = ((1,), "? weather")
    current = SimpleNamespace(iface_value=SimpleNamespace(CurrentValue="javascript:alert(1)"))
    monkeypatch.setattr(ui, "_require_omnibox", lambda token: current)
    keys = []

    def hotkey(sequence, guard):
        guard()
        keys.extend(sequence)

    ui.keyboard = SimpleNamespace(hotkey=hotkey)
    with pytest.raises(RuntimeError, match="changed"):
        ui.submit(token)
    assert not keys


def test_com_apartment_initialization_is_balanced_on_error(monkeypatch):
    calls = []
    runtime = SimpleNamespace(
        ApartmentType=SimpleNamespace(MULTI_THREADED="MTA"),
        init_apartment=lambda mode: calls.append(("init", mode)),
        uninit_apartment=lambda: calls.append("uninit"),
    )
    monkeypatch.setitem(sys.modules, "winrt.runtime", runtime)
    monkeypatch.setattr(chrome, "IS_WINDOWS", True)
    with pytest.raises(RuntimeError, match="action failed"):
        with chrome._com_apartment():
            calls.append("action")
            raise RuntimeError("action failed")
    assert calls == [("init", "MTA"), "action", "uninit"]


def test_com_apartment_does_not_uninitialize_when_initialization_fails(monkeypatch):
    calls = []

    def initialize(mode):
        raise RuntimeError("incompatible apartment")

    runtime = SimpleNamespace(
        ApartmentType=SimpleNamespace(MULTI_THREADED="MTA"),
        init_apartment=initialize,
        uninit_apartment=lambda: calls.append("uninit"),
    )
    monkeypatch.setitem(sys.modules, "winrt.runtime", runtime)
    monkeypatch.setattr(chrome, "IS_WINDOWS", True)
    with pytest.raises(RuntimeError, match="incompatible"):
        with chrome._com_apartment():
            pytest.fail("action should not run")
    assert not calls


def test_native_unicode_input_never_interprets_key_metacharacters():
    keyboard = object.__new__(chrome._NativeKeyboard)
    sent = []
    guards = []

    def send(count, inputs, size):
        assert size == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        for item in inputs:
            value = item.payload.keyboard
            sent.append((value.vk, value.scan, value.flags))
        return count

    keyboard.user32 = SimpleNamespace(SendInput=send)
    text = "{ENTER} ^+% 東京 🐱"
    keyboard.type_text(text, lambda: guards.append(True))
    assert guards == [True]
    assert all(key == 0 and flags in {4, 6} for key, scan, flags in sent)
    received = b"".join(scan.to_bytes(2, "little") for key, scan, flags in sent if flags == 4)
    assert received.decode("utf-16-le") == text


def test_native_input_does_not_send_when_focus_guard_fails():
    keyboard = object.__new__(chrome._NativeKeyboard)
    calls = []
    keyboard.user32 = SimpleNamespace(SendInput=lambda *args: calls.append(args))

    def guard():
        raise RuntimeError("lost focus")

    with pytest.raises(RuntimeError, match="focus"):
        keyboard.type_text("hello", guard)
    assert not calls


def test_partial_native_hotkey_releases_modifier_and_reports_failure():
    keyboard = object.__new__(chrome._NativeKeyboard)
    batches = []

    def send(count, inputs, size):
        batches.append([(item.payload.keyboard.vk, item.payload.keyboard.flags) for item in inputs])
        return 1 if len(batches) == 1 else count

    keyboard.user32 = SimpleNamespace(SendInput=send)
    with pytest.raises(RuntimeError, match="could not type"):
        keyboard.hotkey([0x11, 0x4C], lambda: None)
    assert batches[1] == [(0x11, 2)]
