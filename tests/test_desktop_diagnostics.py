"""Desktop diagnostics reveal availability, never user data or control apps."""
import sys
from types import ModuleType, SimpleNamespace

import check_desktop


def test_windows_diagnostic_reads_session_identity_and_redacts_failures(monkeypatch, capsys):
    monkeypatch.setattr(check_desktop.platform, "system", lambda: "Windows")
    monkeypatch.setattr(check_desktop.platform, "python_version", lambda: "3.12.10")
    monkeypatch.setattr(check_desktop, "struct", SimpleNamespace(calcsize=lambda code: 8))
    monkeypatch.setattr(sys, "coinit_flags", 0, raising=False)
    apartment_calls = []
    runtime = SimpleNamespace(
        ApartmentType=SimpleNamespace(MULTI_THREADED=0),
        init_apartment=lambda kind: apartment_calls.append("init"),
        uninit_apartment=lambda: apartment_calls.append("uninit"),
    )
    winrt = ModuleType("winrt")
    winrt.runtime = runtime
    control = ModuleType("winrt.windows.media.control")

    async def manager():
        # Supplying only identities makes metadata/control access fail loudly.
        return SimpleNamespace(get_sessions=lambda: [
            SimpleNamespace(source_app_user_model_id="not-spotify.exe"),
            SimpleNamespace(source_app_user_model_id="SpotifyAB.SpotifyMusic_example!Spotify"),
        ])

    control.GlobalSystemMediaTransportControlsSessionManager = SimpleNamespace(request_async=manager)
    monkeypatch.setitem(sys.modules, "winrt", winrt)
    monkeypatch.setitem(sys.modules, "winrt.windows.media.control", control)

    class PrivateError(OSError):
        winerror = 5

    def inaccessible_uia():
        raise PrivateError("Private window title; API token=do-not-print; C:/Private/User")

    monkeypatch.setattr(check_desktop, "_native_uia_available", inaccessible_uia)
    monkeypatch.setattr(check_desktop, "_chrome_installed", lambda: True)
    monkeypatch.setattr(check_desktop, "_spotify_running", lambda: True)
    assert check_desktop.main() == 1
    output = capsys.readouterr().out
    assert "Python: 3.12.10 (64-bit)" in output
    assert "PrivateError, winerror=0x00000005" in output
    assert "Google Chrome installation: available" in output
    assert "Spotify desktop process: available" in output
    assert "Spotify Windows media session: available" in output
    assert "Private window" not in output and "do-not-print" not in output and "C:/Private" not in output
    assert apartment_calls == ["init", "uninit"]


def test_linux_branch_explains_windows_requirement_without_desktop_probes(monkeypatch, capsys):
    monkeypatch.setattr(check_desktop.platform, "system", lambda: "Linux")

    def must_not_run():
        raise AssertionError("Windows probe attempted on Linux")

    for name in ("_native_uia_available", "_chrome_installed", "_spotify_running",
                 "_spotify_media_session_available"):
        monkeypatch.setattr(check_desktop, name, must_not_run)
    assert check_desktop.main() == 2
    assert "require Windows 10 or 11" in capsys.readouterr().out


def test_wrapped_native_error_retains_hresult_without_private_payload():
    class NativeError(Exception):
        hresult = -2147024770

    native = NativeError("private native window title; token=native-secret")
    wrapped = RuntimeError("private wrapper path C:/Private/User; token=wrapper-secret")
    wrapped.__cause__ = native
    result = check_desktop._safe_error(wrapped)
    assert result == "RuntimeError caused by NativeError, hresult=0x8007007E"
    assert not any(value in result for value in (
        "private", "native-secret", "wrapper-secret", "C:/Private/User",
    ))


def test_error_cause_inspection_is_bounded_and_handles_cycles():
    root = RuntimeError("private payload")
    current = root
    for _ in range(8):
        current.__cause__ = RuntimeError("more private payload")
        current = current.__cause__
    assert check_desktop._safe_error(root) == " caused by ".join(["RuntimeError"] * 4)
    current.__cause__ = root
    assert check_desktop._safe_error(current) == " caused by ".join(["RuntimeError"] * 4)
    root.__cause__ = root
    assert check_desktop._safe_error(root) == "RuntimeError"
