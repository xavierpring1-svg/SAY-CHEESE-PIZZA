"""The small Windows UI Automation surface used by Chrome and Spotify.

This adapter talks directly to UIAutomationCore through the bundled comtypes
library. It does not import pywinauto's unrelated win32ui/MFC functionality.
Callers initialize their worker's COM apartment before using these objects;
automation interfaces are kept per thread rather than passed between workers.
"""
from __future__ import annotations

import ctypes
import threading
import time

from .windows import IS_WINDOWS


_threads = threading.local()
_type_library_lock = threading.Lock()
_CONTROL_TYPES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "ComboBox",
    50004: "Edit", 50005: "Hyperlink", 50006: "Image", 50007: "ListItem",
    50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
    50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar", 50015: "Slider",
    50016: "Spinner", 50017: "StatusBar", 50018: "Tab", 50019: "TabItem",
    50020: "Text", 50021: "ToolBar", 50022: "ToolTip", 50023: "Tree",
    50024: "TreeItem", 50025: "Custom", 50026: "Group", 50027: "Thumb",
    50028: "DataGrid", 50029: "DataItem", 50030: "Document", 50031: "SplitButton",
    50032: "Window", 50033: "Pane", 50034: "Header", 50035: "HeaderItem",
    50036: "Table", 50037: "TitleBar", 50038: "Separator", 50039: "SemanticZoom",
    50040: "AppBar",
}


def _create_automation():
    if not IS_WINDOWS:
        raise RuntimeError("Desktop automation requires Windows 10 or 11.")
    try:
        import comtypes
        import comtypes.client
    except ImportError as error:
        raise RuntimeError("Windows automation couldn't load its bundled component. Re-extract the complete JARVIS folder and run Check Desktop Controls.cmd.") from error

    # comtypes may generate Python wrappers on first use. Serialize that file
    # generation, then create the COM interface on this calling worker thread.
    try:
        with _type_library_lock:
            dll = comtypes.client.GetModule("UIAutomationCore.dll")
        automation = comtypes.CoCreateInstance(
            dll.CUIAutomation._reg_clsid_, interface=dll.IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
    except (OSError, comtypes.COMError) as error:
        raise RuntimeError("Windows UI Automation couldn't initialize. Run Check Desktop Controls.cmd in the extracted JARVIS folder for details.") from error
    return _Automation(dll, automation)


def IUIA():
    """Return this thread's native UIA client, with ``iuia`` and ``dll`` fields."""
    client = getattr(_threads, "automation", None)
    if client is None:
        client = _threads.automation = _create_automation()
    return client


class _Automation:
    def __init__(self, dll, automation):
        self.dll, self.iuia = dll, automation

    def wrap(self, element):
        return Element(element, self) if element else None

    def condition(self, *, class_name=None, control_type=None):
        conditions = []
        if class_name is not None:
            conditions.append(self.iuia.CreatePropertyCondition(
                self.dll.UIA_ClassNamePropertyId, class_name))
        if control_type is not None:
            number = next((number for number, name in _CONTROL_TYPES.items()
                           if name == control_type), None)
            if number is None:
                raise ValueError(f"Unknown UI Automation control type: {control_type}")
            conditions.append(self.iuia.CreatePropertyCondition(
                self.dll.UIA_ControlTypePropertyId, number))
        if not conditions:
            return self.iuia.CreateTrueCondition()
        if len(conditions) == 1:
            return conditions[0]
        return self.iuia.CreateAndCondition(*conditions)

    def find(self, element, scope, condition):
        found = element.FindAll(scope, condition)
        if not found:
            return []
        return [self.wrap(found.GetElement(index)) for index in range(found.Length)]


class _ElementInfo:
    def __init__(self, element):
        self.element = element

    @property
    def process_id(self):
        return int(self.element.CurrentProcessId)

    @property
    def class_name(self):
        return self.element.CurrentClassName or ""

    @property
    def automation_id(self):
        return self.element.CurrentAutomationId or ""

    @property
    def name(self):
        return self.element.CurrentName or ""

    @property
    def control_type(self):
        return _CONTROL_TYPES.get(int(self.element.CurrentControlType), "Custom")


class Element:
    """A live native UIA element; properties are reread before guarded actions."""
    def __init__(self, element, automation):
        self.element_info = _ElementInfo(element)
        self._automation = automation

    @property
    def handle(self):
        value = self.element_info.element.CurrentNativeWindowHandle
        return int(getattr(value, "value", value) or 0)

    def process_id(self):
        return self.element_info.process_id

    def window_text(self):
        return self.element_info.name

    def parent(self):
        parent = self._automation.iuia.RawViewWalker.GetParentElement(self.element_info.element)
        return self._automation.wrap(parent)

    def descendants(self, control_type=None):
        return self._automation.find(
            self.element_info.element, self._automation.dll.TreeScope_Descendants,
            self._automation.condition(control_type=control_type),
        )

    def is_visible(self):
        return not bool(self.element_info.element.CurrentIsOffscreen)

    def is_enabled(self):
        return bool(self.element_info.element.CurrentIsEnabled)

    def _pattern(self, number, interface):
        pattern = self.element_info.element.GetCurrentPattern(number)
        if not pattern:
            raise RuntimeError("This control does not expose the required accessibility action.")
        return pattern.QueryInterface(interface)

    @property
    def iface_value(self):
        dll = self._automation.dll
        return self._pattern(dll.UIA_ValuePatternId, dll.IUIAutomationValuePattern)

    def invoke(self):
        if not self.is_visible() or not self.is_enabled():
            raise RuntimeError("This control is no longer visible and enabled.")
        dll = self._automation.dll
        # Fallback only when a pattern is unavailable, never after Invoke has
        # run: an action that partly completed must not be invoked twice.
        try:
            action = self._pattern(dll.UIA_InvokePatternId, dll.IUIAutomationInvokePattern)
        except Exception:
            try:
                legacy = self._pattern(dll.UIA_LegacyIAccessiblePatternId,
                                       dll.IUIAutomationLegacyIAccessiblePattern)
            except Exception as error:
                raise RuntimeError("This control does not expose an accessible action.") from error
            if not (legacy.CurrentDefaultAction or "").strip():
                raise RuntimeError("This control has no accessible default action.")
            legacy.DoDefaultAction()
        else:
            action.Invoke()

    def set_focus(self):
        if not self.is_enabled():
            raise RuntimeError("The requested window is not enabled.")
        ancestor = self
        own_handle = handle = ancestor.handle
        for _ in range(32):
            if handle:
                break
            ancestor = ancestor.parent()
            if ancestor is None:
                break
            handle = ancestor.handle
        if not handle:
            raise RuntimeError("The requested control has no desktop window to focus.")
        _foreground_window(handle)
        # Some Chromium window providers reject UIA SetFocus even after Win32
        # has activated their HWND. Chrome/Spotify need that confirmed window;
        # focus of an actual child control still requires its provider below.
        if own_handle and self.element_info.control_type in {"Window", "Pane"}:
            return
        self.element_info.element.SetFocus()

    def __eq__(self, other):
        if not isinstance(other, Element):
            return NotImplemented
        if self.element_info.element is other.element_info.element:
            return True
        left = tuple(self.element_info.element.GetRuntimeId() or ())
        right = tuple(other.element_info.element.GetRuntimeId() or ())
        return bool(left and right and left == right
                    and self.process_id() == other.process_id())


class Desktop:
    def __init__(self, backend="uia"):
        if backend != "uia":
            raise ValueError("JARVIS uses the native UI Automation backend.")
        self._automation = IUIA()

    def windows(self, *, class_name=None, visible_only=False):
        automation = self._automation
        windows = automation.find(
            automation.iuia.GetRootElement(), automation.dll.TreeScope_Children,
            automation.condition(class_name=class_name),
        )
        return [window for window in windows if window.is_visible()] if visible_only else windows


def focused_element():
    automation = IUIA()
    return automation.wrap(automation.iuia.GetFocusedElement())


def _foreground_window(handle):
    """Restore and activate the exact HWND, then require Windows to confirm it."""
    if not IS_WINDOWS:
        raise RuntimeError("Desktop focus requires Windows 10 or 11.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.IsIconic.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_int
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_uint32
    user32.AttachThreadInput.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int]
    user32.AttachThreadInput.restype = ctypes.c_int
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = ctypes.c_uint32
    if user32.IsIconic(handle):
        user32.ShowWindow(handle, 9)  # SW_RESTORE
    user32.SetForegroundWindow(handle)
    if user32.GetForegroundWindow() == handle:
        return
    # Foreground restrictions can apply to a voice-command worker. Attach only
    # while activating this requested window; always detach before any typing.
    current = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    targets = {user32.GetWindowThreadProcessId(handle, None)}
    if foreground:
        targets.add(user32.GetWindowThreadProcessId(foreground, None))
    # AttachThreadInput requires a Win32 message queue on the voice worker.
    # PeekMessage creates one without removing or sending any messages.
    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]

    class Message(ctypes.Structure):
        _fields_ = [("window", ctypes.c_void_p), ("message", ctypes.c_uint32),
                    ("wparam", ctypes.c_size_t), ("lparam", ctypes.c_ssize_t),
                    ("time", ctypes.c_uint32), ("point", Point), ("private", ctypes.c_uint32)]

    user32.PeekMessageW.argtypes = [ctypes.POINTER(Message), ctypes.c_void_p,
                                   ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    user32.PeekMessageW.restype = ctypes.c_int
    message = Message()
    user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
    attached = []
    try:
        for target in targets - {current, 0}:
            if user32.AttachThreadInput(current, target, True):
                attached.append(target)
        user32.SetForegroundWindow(handle)
    finally:
        for target in reversed(attached):
            user32.AttachThreadInput(current, target, False)
    deadline = time.monotonic() + .5
    while user32.GetForegroundWindow() != handle and time.monotonic() < deadline:
        time.sleep(.025)
    if user32.GetForegroundWindow() != handle:
        raise RuntimeError("Windows couldn't bring the requested app forward. Click its window and try again.")
