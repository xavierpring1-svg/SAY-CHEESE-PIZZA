"""Read-only Windows desktop checks without opening or controlling applications.

Reports component availability only. Window titles, song metadata, file paths,
environment values, credentials, and arbitrary exception messages are omitted.
"""
from __future__ import annotations

import asyncio
import platform
import struct
import sys
import threading
from types import SimpleNamespace


def _safe_error(error: Exception) -> str:
    """Keep useful Windows error codes without revealing exception payloads."""
    names, seen = [], set()
    current = error
    # Native UIA initialization wraps its original COM/OSError in RuntimeError.
    # Follow only explicit causes, bounded even for malformed or cyclic chains.
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        names.append(type(current).__name__)
        for attribute in ("hresult", "winerror", "errno"):
            code = getattr(current, attribute, None)
            if isinstance(code, int) and not isinstance(code, bool):
                return f"{' caused by '.join(names)}, {attribute}=0x{code & 0xFFFFFFFF:08X}"
        current = current.__cause__
    return " caused by ".join(names)


def _native_uia_available() -> bool:
    import comtypes
    from jarvis.uia import IUIA

    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    try:
        return IUIA().iuia.GetRootElement() is not None
    finally:
        comtypes.CoUninitialize()


def _chrome_installed() -> bool:
    from jarvis.chrome import _chrome_executable

    # Discovery reads the registry, standard install locations, and process
    # paths. Empty entries avoid shortcut resolution or app discovery scripts.
    apps = SimpleNamespace(lock=threading.RLock(), entries={})
    try:
        _chrome_executable(apps)
    except RuntimeError:
        return False
    return True


def _spotify_running() -> bool:
    import psutil

    for process in psutil.process_iter(["name"]):
        try:
            if (process.info.get("name") or "").casefold() == "spotify.exe":
                return True
        except (psutil.Error, OSError):
            continue
    return False


async def _spotify_session_exists() -> bool:
    from jarvis.spotify_desktop import _spotify_source
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

    manager = await asyncio.wait_for(
        GlobalSystemMediaTransportControlsSessionManager.request_async(), timeout=8,
    )
    # Read identities only; do not read song metadata or invoke media controls.
    return any(_spotify_source(session.source_app_user_model_id)
               for session in manager.get_sessions())


def _spotify_media_session_available() -> bool:
    from winrt import runtime

    runtime.init_apartment(runtime.ApartmentType.MULTI_THREADED)
    try:
        return asyncio.run(_spotify_session_exists())
    finally:
        runtime.uninit_apartment()


def main() -> int:
    bits = struct.calcsize("P") * 8
    print("JARVIS desktop controls diagnostic")
    print(f"Python: {platform.python_version()} ({bits}-bit)")
    if platform.system() != "Windows":
        print("Desktop checks require Windows 10 or 11. Run this helper on the Windows PC.")
        return 2

    # Match the application's MTA workers before the first lazy COM import.
    sys.coinit_flags = 0
    ready = bits == 64
    if not ready:
        print("Runtime: use the 64-bit Windows release or 64-bit Python 3.12.")
    checks = (
        ("Native Windows UI Automation", _native_uia_available,
         "not available; extract the complete current Windows release"),
        ("Google Chrome installation", _chrome_installed,
         "not detected; install desktop Google Chrome"),
        ("Spotify desktop process", _spotify_running,
         "not detected; open Spotify or SpotX"),
        ("Spotify Windows media session", _spotify_media_session_available,
         "not detected; sign in and play a song once in Spotify"),
    )
    for label, probe, guidance in checks:
        try:
            available = probe()
        except Exception as error:
            ready = False
            print(f"{label}: check failed ({_safe_error(error)}).")
        else:
            if available:
                print(f"{label}: available.")
            else:
                ready = False
                print(f"{label}: {guidance}.")
    print("Checks finished. Availability does not prove this client's controls are accessible.")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
