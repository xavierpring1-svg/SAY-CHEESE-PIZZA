import ast
import ctypes
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from jarvis import uia


class NativeElement:
    def __init__(self, *, name="", kind=50026, pid=17, runtime=(1, 2), handle=0,
                 visible=True, enabled=True, children=()):
        self.CurrentName, self.CurrentControlType = name, kind
        self.CurrentProcessId, self.CurrentNativeWindowHandle = pid, handle
        self.CurrentClassName, self.CurrentAutomationId = "", ""
        self.CurrentIsOffscreen, self.CurrentIsEnabled = not visible, enabled
        self.runtime, self.children, self.parent = runtime, list(children), None
        self.patterns, self.focuses = {}, 0
        for child in self.children:
            child.parent = self

    def GetRuntimeId(self):
        return self.runtime

    def FindAll(self, scope, condition):
        found = []

        def visit(parent):
            for child in parent.children:
                if condition(child):
                    found.append(child)
                if scope == 4:
                    visit(child)

        visit(self)
        return SimpleNamespace(Length=len(found), GetElement=lambda index: found[index])

    def GetCurrentPattern(self, number):
        pattern = self.patterns.get(number)
        if isinstance(pattern, Exception):
            raise pattern
        return SimpleNamespace(QueryInterface=lambda interface: pattern) if pattern else None

    def SetFocus(self):
        self.focuses += 1


def automation(root, focused=None):
    dll = SimpleNamespace(TreeScope_Children=2, TreeScope_Descendants=4,
                          UIA_ClassNamePropertyId=30012, UIA_ControlTypePropertyId=30003,
                          UIA_ValuePatternId=10002, IUIAutomationValuePattern="value",
                          UIA_InvokePatternId=10000, IUIAutomationInvokePattern="invoke",
                          UIA_LegacyIAccessiblePatternId=10018,
                          IUIAutomationLegacyIAccessiblePattern="legacy")

    def property_condition(number, value):
        field = "CurrentClassName" if number == 30012 else "CurrentControlType"
        return lambda element: getattr(element, field) == value

    client = SimpleNamespace(
        GetRootElement=lambda: root, GetFocusedElement=lambda: focused,
        CreateTrueCondition=lambda: lambda element: True,
        CreatePropertyCondition=property_condition,
        CreateAndCondition=lambda first, second: lambda element: first(element) and second(element),
        RawViewWalker=SimpleNamespace(GetParentElement=lambda element: element.parent),
    )
    return uia._Automation(dll, client)


def test_browser_address_bar_properties_pattern_and_ancestry_are_live(monkeypatch):
    edit = NativeElement(name="Address and search bar", kind=50004, runtime=(1, 3))
    window = NativeElement(name="Chrome", kind=50032, handle=123, children=[edit])
    window.CurrentClassName = "Chrome_WidgetWin_1"
    edit.CurrentClassName, edit.CurrentAutomationId = "OmniboxViewViews", "omnibox"
    edit.patterns[10002] = SimpleNamespace(CurrentValue="pizza")
    client = automation(NativeElement(children=[window]), edit)
    monkeypatch.setattr(uia, "IUIA", lambda: client)
    wrapped = uia.focused_element()
    assert wrapped.element_info.control_type == "Edit"
    assert wrapped.element_info.class_name == "OmniboxViewViews"
    assert wrapped.element_info.automation_id == "omnibox"
    assert wrapped.element_info.process_id == 17
    assert wrapped.iface_value.CurrentValue == "pizza"
    assert wrapped.parent().handle == 123
    edit.patterns[10002].CurrentValue = "user replacement"
    assert wrapped.iface_value.CurrentValue == "user replacement"
    assert uia.Desktop().windows(class_name="Chrome_WidgetWin_1", visible_only=True) == [wrapped.parent()]


def test_window_filter_and_song_descendants_preserve_exact_controls(monkeypatch):
    play = NativeElement(name="Play My Song", kind=50000)
    title = NativeElement(name="My Song", kind=50020)
    row = NativeElement(children=[play, title])
    spotify = NativeElement(kind=50032, children=[row])
    hidden = NativeElement(kind=50032, visible=False)
    client = automation(NativeElement(children=[spotify, hidden]))
    monkeypatch.setattr(uia, "IUIA", lambda: client)
    assert len(uia.Desktop().windows()) == 2
    assert len(uia.Desktop().windows(visible_only=True)) == 1
    song = client.wrap(spotify)
    assert [element.window_text() for element in song.descendants(control_type="Button")] == ["Play My Song"]
    assert len(song.descendants()) == 3
    with pytest.raises(ValueError, match="Unknown"):
        song.descendants(control_type="invented")


def test_element_identity_requires_runtime_id_and_process():
    client = automation(NativeElement())
    first = client.wrap(NativeElement(runtime=(9, 2), pid=20))
    same = client.wrap(NativeElement(runtime=(9, 2), pid=20))
    other_process = client.wrap(NativeElement(runtime=(9, 2), pid=21))
    assert first == same
    assert first != other_process
    assert first != client.wrap(NativeElement(runtime=(9, 3), pid=20))
    assert client.wrap(NativeElement(runtime=())) != client.wrap(NativeElement(runtime=()))


def test_invoke_targets_pattern_and_never_retries_partially_completed_action():
    calls = []

    def failing_invoke():
        calls.append("invoke")
        raise OSError("provider error after sending action")

    native = NativeElement(kind=50000)
    native.patterns[10000] = SimpleNamespace(Invoke=failing_invoke)
    native.patterns[10018] = SimpleNamespace(CurrentDefaultAction="Play", DoDefaultAction=lambda: calls.append("legacy"))
    wrapped = automation(native).wrap(native)
    with pytest.raises(OSError, match="provider error"):
        wrapped.invoke()
    assert calls == ["invoke"]


def test_legacy_default_action_is_targeted_and_requires_nonempty_action():
    calls = []
    native = NativeElement(kind=50029)
    legacy = SimpleNamespace(CurrentDefaultAction="Play", DoDefaultAction=lambda: calls.append("play"))
    native.patterns[10018] = legacy
    wrapped = automation(native).wrap(native)
    wrapped.invoke()
    assert calls == ["play"]
    legacy.CurrentDefaultAction = ""
    with pytest.raises(RuntimeError, match="default action"):
        wrapped.invoke()
    assert calls == ["play"]
    native.CurrentIsEnabled = False
    with pytest.raises(RuntimeError, match="visible and enabled"):
        wrapped.invoke()


def test_focus_restores_exact_ancestor_window_before_uia_focus(monkeypatch):
    native = NativeElement()
    window = NativeElement(handle=2**40 + 17, children=[native])
    wrapped = automation(window).wrap(native)
    handles = []
    monkeypatch.setattr(uia, "_foreground_window", handles.append)
    wrapped.set_focus()
    assert handles == [2**40 + 17]
    assert native.focuses == 1


def test_foreground_failure_does_not_call_provider_focus(monkeypatch):
    native = NativeElement(handle=17)
    wrapped = automation(native).wrap(native)

    def refuse(handle):
        raise RuntimeError("focus refused")

    monkeypatch.setattr(uia, "_foreground_window", refuse)
    with pytest.raises(RuntimeError, match="refused"):
        wrapped.set_focus()
    assert native.focuses == 0


def test_native_window_focus_does_not_depend_on_chromium_provider_setfocus(monkeypatch):
    native = NativeElement(kind=50032, handle=17)
    wrapped = automation(native).wrap(native)
    handles = []
    monkeypatch.setattr(uia, "_foreground_window", handles.append)
    wrapped.set_focus()
    assert handles == [17]
    assert native.focuses == 0


class NativeFunction:
    def __init__(self, function):
        self.function = function

    def __call__(self, *arguments):
        return self.function(*arguments)


def test_native_focus_preserves_64bit_hwnd_restores_and_detaches_queues(monkeypatch):
    handle = 2**40 + 17
    events, foreground = [], [99]
    focus_calls = []

    def set_foreground(value):
        focus_calls.append(value)
        if len(focus_calls) > 1:
            foreground[0] = value
        return 1

    user32 = SimpleNamespace(
        GetForegroundWindow=NativeFunction(lambda: foreground[0]),
        IsIconic=NativeFunction(lambda value: value == handle),
        ShowWindow=NativeFunction(lambda value, command: events.append(("restore", value, command))),
        SetForegroundWindow=NativeFunction(set_foreground),
        GetWindowThreadProcessId=NativeFunction(lambda value, pointer: 20 if value == handle else 30),
        AttachThreadInput=NativeFunction(lambda first, second, attach: events.append(("attach", first, second, attach)) or 1),
        PeekMessageW=NativeFunction(lambda *arguments: events.append(("queue",)) or 0),
    )
    kernel32 = SimpleNamespace(GetCurrentThreadId=NativeFunction(lambda: 10))
    monkeypatch.setattr(uia, "IS_WINDOWS", True)
    monkeypatch.setattr(uia.ctypes, "WinDLL", lambda name, **kwargs: user32 if name == "user32" else kernel32, raising=False)
    uia._foreground_window(handle)
    assert focus_calls == [handle, handle]
    assert events[0] == ("restore", handle, 9)
    assert ("queue",) in events
    for target in (20, 30):
        assert ("attach", 10, target, True) in events
        assert ("attach", 10, target, False) in events
    assert user32.SetForegroundWindow.argtypes == [ctypes.c_void_p]
    assert user32.GetForegroundWindow.restype is ctypes.c_void_p


def test_native_client_creation_uses_system_typelib_and_exact_interface(monkeypatch):
    calls = []
    dll = SimpleNamespace(CUIAutomation=SimpleNamespace(_reg_clsid_="uia-clsid"),
                          IUIAutomation=object())
    comtypes = ModuleType("comtypes")
    comtypes.COMError = type("COMError", (Exception,), {})
    comtypes.CLSCTX_INPROC_SERVER = 1
    comtypes.CoCreateInstance = lambda clsid, **kwargs: calls.append((clsid, kwargs)) or "native"
    client = ModuleType("comtypes.client")
    client.GetModule = lambda path: calls.append(path) or dll
    comtypes.client = client
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)
    monkeypatch.setattr(uia, "IS_WINDOWS", True)
    result = uia._create_automation()
    assert result.iuia == "native"
    assert calls == ["UIAutomationCore.dll", ("uia-clsid", {"interface": dll.IUIAutomation, "clsctx": 1})]


def test_com_clients_are_thread_local(monkeypatch):
    created = []

    def create():
        client = object()
        created.append(client)
        return client

    monkeypatch.setattr(uia, "_threads", threading.local())
    monkeypatch.setattr(uia, "_create_automation", create)
    main_client = uia.IUIA()
    assert uia.IUIA() is main_client
    worker_clients = []
    worker = threading.Thread(target=lambda: worker_clients.extend([uia.IUIA(), uia.IUIA()]))
    worker.start()
    worker.join()
    assert worker_clients[0] is worker_clients[1]
    assert worker_clients[0] is not main_client
    assert len(created) == 2


def test_native_adapter_does_not_import_mfc_dependent_automation():
    source = Path(uia.__file__).read_text()
    imports = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith(("pywinauto", "win32ui", "pythoncom")) for name in imports)


def test_native_create_automation_is_lazy_and_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(uia, "IS_WINDOWS", False)
    with pytest.raises(RuntimeError, match="Windows"):
        uia._create_automation()
