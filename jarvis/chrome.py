"""Chrome omnibox commands, with literal text and explicit focus checks.

Windows UI Automation is imported only when a desktop action is requested, so
the rest of JARVIS (and command tests) also works on non-Windows machines.
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import psutil

from .windows import IS_WINDOWS, NO_WINDOW, powershell


@contextmanager
def _com_apartment():
    if not IS_WINDOWS:
        raise RuntimeError("Chrome desktop commands require Windows 10 or 11.")
    from winrt.runtime import ApartmentType, init_apartment, uninit_apartment
    # Every dictation operation initializes its calling thread even if UIA
    # was imported previously on another thread. Own only this reference;
    # Spotify and the Assistant worker may hold their own MTA references.
    init_apartment(ApartmentType.MULTI_THREADED)
    try:
        yield
    finally:
        uninit_apartment()


def _validated_text(value):
    if not isinstance(value, str):
        raise ValueError("Tell me what to put in Chrome's search bar.")
    if any(ord(char) < 32 or 127 <= ord(char) < 160 or char in "\u2028\u2029"
           for char in value):
        raise ValueError("Chrome searches must be a single line of text.")
    value = value.strip()
    if not value:
        raise ValueError("Tell me what to put in Chrome's search bar.")
    if len(value) > 1000:
        raise ValueError("Please keep Chrome searches under 1,000 characters.")
    # These are desktop/code schemes rather than ordinary search queries. Web
    # addresses are allowed, but search() still submits them as search text.
    scheme = re.match(r"^([a-z][a-z0-9+.-]*)\s*:", value, re.I)
    if scheme and scheme.group(1).lower() not in {"http", "https"}:
        raise ValueError("Use ordinary search text, not a browser or application command URL.")
    # Invalid lone surrogates cannot be sent as a Unicode keyboard sequence.
    try:
        value.encode("utf-16-le")
    except UnicodeEncodeError as error:
        raise ValueError("That search contains invalid Unicode text.") from error
    return value


def _chrome_executable(apps):
    """Find Chrome without importing UI Automation or WinRT components."""
    with apps.lock:
        entries = apps.entries.copy()
    candidates = [target for name, target in entries.items()
                  if name.lower() in {"chrome", "google chrome"}]
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            # Portable Python may use a different registry view from Chrome.
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                                        0, winreg.KEY_READ | view) as key:
                        candidates.append(winreg.QueryValue(key, None))
                except OSError:
                    pass
    except ImportError:
        pass
    for variable in ("LOCALAPPDATA", "PROGRAMW6432", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.getenv(variable)
        if base:
            candidates.append(str(Path(base) / "Google/Chrome/Application/chrome.exe"))
    candidates.append(shutil.which("chrome.exe"))
    # A running portable/custom installation can be absent from both the
    # Start menu and App Paths registry. Inspect names and paths only.
    for process in psutil.process_iter(["name", "exe"]):
        try:
            if (process.info.get("name") or "").lower() == "chrome.exe":
                candidates.append(process.info.get("exe"))
        except (psutil.Error, OSError):
            continue
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        path = Path(os.path.expandvars(candidate.strip().strip('"')))
        if path.suffix.lower() == ".lnk" and path.is_file():
            try:
                target = powershell(
                    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                    "$link=[Console]::In.ReadToEnd(); "
                    "(New-Object -ComObject WScript.Shell).CreateShortcut($link).TargetPath",
                    input_text=str(path), timeout=8)
                # Shortcut arguments are deliberately excluded from actions.
                path = Path(os.path.expandvars(target.strip().strip('"')))
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                continue
        if path.name.lower() == "chrome.exe" and path.is_file():
            return str(path)
    raise RuntimeError("I couldn't find Google Chrome. Install it or add its app shortcut in Settings.")


class _AddressBarUnavailable(RuntimeError):
    """A temporary UIA read failure; never permission to submit unchecked text."""


@dataclass(frozen=True)
class _Omnibox:
    process_id: int
    handle: int
    identity: tuple


class _NativeKeyboard:
    """SendInput avoids keyboard-layout changes and send_keys metacharacters."""
    def __init__(self):
        if not IS_WINDOWS:
            raise RuntimeError("Chrome desktop commands require Windows 10 or 11.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.user32.SendInput.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        self.user32.SendInput.restype = ctypes.c_uint32

    @staticmethod
    def _structures():
        # Explicit widths also keep mock tests independent of the host OS's C
        # long size. Windows ULONG_PTR has the width of a native pointer.
        class KeyboardInput(ctypes.Structure):
            _fields_ = [("vk", ctypes.c_uint16), ("scan", ctypes.c_uint16),
                        ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                        ("extra", ctypes.c_size_t)]

        class MouseInput(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32),
                        ("data", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                        ("time", ctypes.c_uint32), ("extra", ctypes.c_size_t)]

        class Payload(ctypes.Union):
            _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]

        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_uint32), ("payload", Payload)]
        return Input, KeyboardInput

    def _send(self, events, guard):
        guard()
        Input, KeyboardInput = self._structures()
        inputs = (Input * len(events))()
        for index, (virtual_key, scan, flags) in enumerate(events):
            inputs[index].type = 1  # INPUT_KEYBOARD
            inputs[index].payload.keyboard = KeyboardInput(virtual_key, scan, flags, 0, 0)
        count = self.user32.SendInput(len(inputs), inputs, ctypes.sizeof(Input))
        if count != len(inputs):
            # Release our held virtual modifiers after a partial hotkey send.
            # This emits only key-up events, never typed characters or Enter.
            releases = [(key, 0, 2) for key, _, flag in events
                        if key and flag == 0 and key in {0x10, 0x11, 0x12}]
            if releases:
                cleanup = (Input * len(releases))()
                for index, (key, scan, flags) in enumerate(releases):
                    cleanup[index].type = 1
                    cleanup[index].payload.keyboard = KeyboardInput(key, scan, flags, 0, 0)
                self.user32.SendInput(len(cleanup), cleanup, ctypes.sizeof(Input))
            raise RuntimeError("Windows could not type in Chrome. Keep Chrome open and try again.")

    def hotkey(self, keys, guard):
        self._send([(key, 0, 0) for key in keys]
                   + [(key, 0, 2) for key in reversed(keys)], guard)

    def type_text(self, text, guard):
        encoded = text.encode("utf-16-le")
        events = []
        for index in range(0, len(encoded), 2):
            scan = int.from_bytes(encoded[index:index + 2], "little")
            events.extend([(0, scan, 4), (0, scan, 6)])  # UNICODE + KEYUP
        self._send(events, guard)


class _WindowsChrome:
    def __init__(self, apps):
        # Load the actual automation stack here, where Chrome._ui can report
        # missing/incompatible native components, rather than later in focus.
        from .uia import Desktop
        from comtypes import COMError
        self.apps = apps
        self._desktop = Desktop
        self._uia_errors = (COMError, _AddressBarUnavailable)
        self.keyboard = _NativeKeyboard()

    def _executable(self):
        return _chrome_executable(self.apps)

    def _find_window(self):
        # The native adapter activates the actual HWND; merely calling UIA
        # SetFocus doesn't establish ownership of global keyboard input.
        windows = self._desktop(backend="uia").windows(class_name="Chrome_WidgetWin_1", visible_only=True)
        foreground = self.keyboard.user32.GetForegroundWindow()
        windows.sort(key=lambda window: window.handle != foreground)
        for window in windows:
            try:
                if Path(psutil.Process(window.process_id()).exe()).name.lower() == "chrome.exe":
                    return window
            except (psutil.Error, OSError, RuntimeError):
                continue
        return None

    @staticmethod
    def _focused_edit():
        from .uia import focused_element
        edit = focused_element()
        if edit is None:
            raise _AddressBarUnavailable("Chrome hasn't exposed the focused address bar yet.")
        return edit

    @staticmethod
    def _identity(edit):
        return tuple(edit.element_info.element.GetRuntimeId())

    @staticmethod
    def _is_omnibox(edit):
        info = edit.element_info
        if info.control_type != "Edit":
            return False
        marked = ((info.class_name or "").lower() == "omniboxviewviews"
                  or (info.automation_id or "").lower() in {"addresseditbox", "omnibox"}
                  or (info.name or "").lower() in {
                      "address and search bar", "search or type a url",
                      "search or enter address", "address bar"})
        if not marked:
            return False
        # A website can give its form field the same accessible name. Require
        # browser chrome ancestry and reject every field inside web content.
        ancestor = edit
        for _ in range(16):
            ancestor = ancestor.parent()
            if ancestor is None:
                return False
            control_type = ancestor.element_info.control_type
            if control_type == "Document":
                return False
            if (control_type == "Window"
                    or ancestor.element_info.class_name == "Chrome_WidgetWin_1"):
                return True
        return False

    def _require_window(self, token):
        if self.keyboard.user32.GetForegroundWindow() != token.handle:
            raise RuntimeError("Chrome lost focus. Click Chrome's address bar and try again.")
        try:
            process = psutil.Process(token.process_id)
            if Path(process.exe()).name.lower() != "chrome.exe":
                raise RuntimeError("The selected window is no longer Google Chrome.")
        except psutil.Error as error:
            raise RuntimeError("Chrome closed before I could finish. Try again.") from error

    def _require_omnibox(self, token):
        self._require_window(token)
        try:
            edit = self._focused_edit()
            if (edit.element_info.process_id != token.process_id
                    or not self._is_omnibox(edit)
                    or self._identity(edit) != token.identity):
                raise RuntimeError("Chrome's address bar lost focus. I haven't submitted anything.")
        except getattr(self, "_uia_errors", ()):
            # Only native read failures are temporary. A different process,
            # field, runtime ID, or foreground window fails immediately.
            raise _AddressBarUnavailable("Chrome's address-bar accessibility information isn't ready yet.")
        return edit

    def focus(self):
        window = self._find_window()
        if window is None:
            subprocess.Popen([self._executable(), "--new-window", "about:blank"],
                             creationflags=NO_WINDOW)
            deadline = time.monotonic() + 10
            while window is None and time.monotonic() < deadline:
                time.sleep(.2)
                window = self._find_window()
        if window is None:
            raise RuntimeError("Chrome did not open a desktop window. Open it and try again.")
        window.set_focus()
        token = _Omnibox(window.process_id(), window.handle, ())
        deadline = time.monotonic() + 1.5
        while self.keyboard.user32.GetForegroundWindow() != token.handle:
            if time.monotonic() >= deadline:
                raise RuntimeError("Chrome couldn't become the active window. Click Chrome, then try again.")
            time.sleep(.05)
        self.keyboard.hotkey([0x11, 0x4C], lambda: self._require_window(token))  # Ctrl+L
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            self._require_window(token)
            try:
                edit = self._focused_edit()
                if edit.element_info.process_id == token.process_id and self._is_omnibox(edit):
                    return _Omnibox(token.process_id, token.handle, self._identity(edit))
            except self._uia_errors:
                # Ctrl+L and Chrome's accessibility update are asynchronous.
                # This retry sends no keys and never restores lost focus.
                pass
            time.sleep(.05)
        raise RuntimeError("I couldn't identify Chrome's address bar. Open a normal Chrome window and try again.")

    def write(self, token, text):
        guard = lambda: self._require_omnibox(token)
        self.keyboard.hotkey([0x11, 0x41], guard)  # Ctrl+A
        self.keyboard.type_text(text, guard)
        self._written = (token.identity, text)

    def read(self, token):
        edit = self._require_omnibox(token)
        try:
            return edit.iface_value.CurrentValue
        except Exception as error:
            raise _AddressBarUnavailable("Chrome did not expose its address-bar text. I haven't submitted it.") from error

    def submit(self, token):
        def guard():
            edit = self._require_omnibox(token)
            identity, expected = getattr(self, "_written", (None, ""))
            if (identity != token.identity
                    or edit.iface_value.CurrentValue not in {expected, expected.removeprefix("? ")}):
                raise RuntimeError("Chrome's search text changed. I haven't submitted anything.")
        self.keyboard.hotkey([0x0D], guard)


class Chrome:
    """Search Chrome or dictate into its omnibox; never type into web forms."""
    def __init__(self, apps):
        self.apps = apps
        self._backend = None
        self._pending = None
        self._lock = threading.RLock()

    def _ui(self):
        if not IS_WINDOWS:
            raise RuntimeError("Chrome desktop commands require Windows 10 or 11.")
        if self._backend is None:
            try:
                self._backend = _WindowsChrome(self.apps)
            except (ImportError, OSError) as error:
                raise RuntimeError(f"Chrome dictation couldn't load its Windows automation components: {error}. "
                                   "Install the updated JARVIS release. Direct Chrome searches still work.") from error
        return self._backend

    @staticmethod
    def _read_ready(ui, token):
        deadline = time.monotonic() + 1.2
        while True:
            try:
                return ui.read(token)
            except _AddressBarUnavailable:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.04)

    @staticmethod
    def _wait_for_text(ui, token, expected):
        # SendInput queues key events; Chrome may not have processed them by
        # the time it returns. Poll with the same focus/identity guard used by
        # read(), then fail without Enter if the exact text never appears.
        deadline = time.monotonic() + 1.2
        while True:
            try:
                if ui.read(token) in expected:
                    return
            except _AddressBarUnavailable:
                # Retry unavailable Value patterns, never focus/identity loss.
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Chrome did not receive the complete text. I haven't submitted anything.")
            time.sleep(.04)

    def type_search(self, text):
        with self._lock:
            self._pending = None
            text = _validated_text(text)
            with _com_apartment():
                ui = self._ui()
                token = ui.focus()
                ui.write(token, text)
                self._wait_for_text(ui, token, {text})
                self._pending = (token, text)
        return f"I've typed {text} in Chrome's search bar. Say search that to search it."

    def search(self, query):
        with self._lock:
            pending, self._pending = self._pending, None
            query = _validated_text(query)
            if pending is not None and pending[1] == query:
                # A follow-up "search up <what I just dictated>" must use the
                # same, unchanged address bar. Refocusing here would conceal
                # a tab/window switch or overwrite text the user has edited.
                return self._submit_pending(pending)
            if not IS_WINDOWS:
                raise RuntimeError("Chrome desktop commands require Windows 10 or 11.")
            # A standalone search is a URL launch, not desktop dictation. This
            # works even when Chrome's accessibility/native components fail to
            # load, without sending global keystrokes to another application.
            url = "https://www.google.com/search?" + urlencode({"q": query})
            try:
                subprocess.Popen([_chrome_executable(self.apps), url], creationflags=NO_WINDOW)
            except OSError as error:
                raise RuntimeError("I couldn't launch Google Chrome. Check its App shortcut in Settings and try again.") from error
        return f"Searching Chrome for {query}, boss."

    def submit_search(self):
        with self._lock:
            pending, self._pending = self._pending, None
            if pending is None:
                raise RuntimeError("Tell me what to type in Chrome first, then say search that.")
            return self._submit_pending(pending)

    def _submit_pending(self, pending):
        # The caller holds _lock and consumes the pending command before any
        # desktop operation, so a failed or repeated submit cannot be retried
        # on a different field accidentally.
        token, text = pending
        with _com_apartment():
            ui = self._ui()
            if self._read_ready(ui, token) != text:
                raise RuntimeError("Chrome's search text changed. Dictate it again before searching.")
            # Submit only the saved, still-focused omnibox text, as a search;
            # URLs and text cannot become navigation or JavaScript commands.
            ui.write(token, "? " + text)
            self._wait_for_text(ui, token, {"? " + text, text})
            ui.submit(token)
        return f"Searching Chrome for {text}, boss."
