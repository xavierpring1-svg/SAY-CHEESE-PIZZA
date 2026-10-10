from __future__ import annotations

import asyncio
import ctypes
import difflib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0
if IS_WINDOWS:
    # UI Automation, WinRT media sessions, and Core Audio share MTA workers.
    # comtypes/pywinauto consult this flag at their first lazy import.
    sys.coinit_flags = 0


def powershell(script, timeout=20, input_text=None):
    if not IS_WINDOWS:
        raise RuntimeError("This action requires Windows 10 or 11.")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        input=input_text, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError("Windows could not complete the requested action.")
    return result.stdout.strip()


class Apps:
    def __init__(self, store):
        self.store = store
        self.entries = {"notepad": "notepad.exe", "calculator": "calc.exe",
                        "file explorer": "explorer.exe", "task manager": "taskmgr.exe"}
        self.entries.update(store.data.get("apps", {}))
        self.lock = threading.RLock()

    def discover(self):
        if not IS_WINDOWS:
            return
        entries = {}
        roots = [Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
                 Path(os.getenv("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs"]
        for root in roots:
            if root.exists():
                for file in root.rglob("*.lnk"):
                    entries[file.stem.lower()] = str(file)
        try:
            import winreg
            for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as key:
                        index = 0
                        while True:
                            try:
                                name = winreg.EnumKey(key, index)
                                index += 1
                                with winreg.OpenKey(key, name) as appkey:
                                    path = winreg.QueryValue(appkey, None).strip('"')
                                if Path(path).exists():
                                    entries[Path(name).stem.lower()] = path
                            except OSError:
                                break
                except OSError:
                    pass
            raw = powershell("[Console]::OutputEncoding=[Text.Encoding]::UTF8; @(Get-StartApps | Select-Object Name,AppID) | ConvertTo-Json -Compress")
            for app in json.loads(raw or "[]"):
                if "!" in app["AppID"]:
                    entries[app["Name"].lower()] = "uwp:" + app["AppID"]
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            pass
        with self.lock:
            self.entries.update(entries)
            self.entries.update(self.store.data.get("apps", {}))

    def open(self, name):
        aliases = {"browser": "browser", "internet": "browser", "chrome": "google chrome",
                   "edge": "microsoft edge", "explorer": "file explorer", "files": "file explorer",
                   "settings": "settings", "word": "word", "excel": "excel"}
        name = aliases.get(name.lower().strip(), name.lower().strip())
        if name == "browser":
            webbrowser.open("https://www.google.com")
            return "Opening your browser, boss."
        if not IS_WINDOWS:
            raise RuntimeError("App launching is available in the Windows release.")
        if name == "settings":
            os.startfile("ms-settings:")
            return "Opening Windows settings."
        if name == "spotify":
            os.startfile("spotify:")
            return "Opening Spotify."
        with self.lock:
            entries = self.entries.copy()
        matches = [key for key in entries if name in key]
        key = name if name in entries else matches[0] if len(matches) == 1 else None
        if key is None:
            close = difflib.get_close_matches(name, entries, n=3, cutoff=0.45)
            detail = " Try: " + ", ".join(close) + "." if close else " Add it in Settings → App shortcuts."
            raise RuntimeError(f"I couldn't uniquely find {name}.{detail}")
        target = entries[key]
        if target.startswith("uwp:"):
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + target[4:]])
        elif Path(target).suffix.lower() == ".lnk":
            os.startfile(target)
        else:
            os.startfile(target)
        return f"Opening {key}, boss."


class Spotify:
    """Control the Spotify Windows media session, without a subscription API."""
    async def _session(self):
        from .spotify_desktop import _spotify_source
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        for session in manager.get_sessions():
            if _spotify_source(session.source_app_user_model_id):
                return session
        return None

    async def _control(self, action, uri="", *, cancelled=None):
        if action not in {"play", "pause", "next", "previous", "replay"}:
            raise ValueError("Use play, pause, next, previous, or replay for Spotify.")
        if cancelled and cancelled():
            raise RuntimeError("Spotify playback request cancelled.")
        if action == "play":
            if uri:
                os.startfile(uri)
            else:
                os.startfile("spotify:")
        session = None
        for _ in range(16 if action == "play" else 1):
            session = await self._session()
            if session:
                break
            await asyncio.sleep(0.5)
        if not session:
            raise RuntimeError("Spotify isn't exposing a media session. Open Spotify, sign in, and play a song once, then try again.")
        if action in {"next", "previous", "replay"}:
            from .spotify_desktop import SpotifyTransport
            return await SpotifyTransport(session, cancelled=cancelled).control(action)
        operation = session.try_play_async if action == "play" else session.try_pause_async
        if not await operation():
            raise RuntimeError("Spotify declined that playback command. Check its current playback state.")
        labels = {"play": "Playing Spotify, boss.", "pause": "Spotify paused."}
        return labels[action]

    def control(self, action, uri="", *, cancelled=None):
        if not IS_WINDOWS:
            raise RuntimeError("Spotify desktop controls require Windows.")
        from winrt.runtime import init_apartment, uninit_apartment, ApartmentType
        init_apartment(ApartmentType.MULTI_THREADED)
        try:
            return asyncio.run(self._control(action, uri, cancelled=cancelled))
        finally:
            uninit_apartment()

    def search(self, query):
        if not IS_WINDOWS:
            raise RuntimeError("Spotify search requires the Windows desktop client.")
        os.startfile("spotify:search:" + urllib.parse.quote(query))
        return f"I've opened Spotify results for {query}. Select the track or playlist you want."

    def play(self, query, *, cancelled=None):
        from .spotify_desktop import play_song
        return play_song(query, cancelled=cancelled)

    def set_volume(self, percent):
        """Set Spotify's Windows mixer sessions, including nondefault outputs."""
        try:
            value = int(percent)
        except (TypeError, ValueError):
            raise ValueError("Use a Spotify volume from 0 to 100 percent.") from None
        if not 0 <= value <= 100:
            raise ValueError("Use a Spotify volume from 0 to 100 percent.")
        return _spotify_audio("set", value)

    def adjust_volume(self, action):
        if action not in {"volume up", "volume down", "mute", "unmute"}:
            raise ValueError("Use volume up, volume down, mute, or unmute for Spotify audio.")
        return _spotify_audio(action)


def _spotify_audio_controls():
    """Enumerate active render devices; Spotify can use a separate output."""
    import psutil
    from pycaw.pycaw import AudioUtilities
    from pycaw.utils import AudioSession
    from pycaw.api.audiopolicy import IAudioSessionControl2
    from pycaw.constants import DEVICE_STATE, EDataFlow

    controls = []
    for device in AudioUtilities.GetAllDevices(data_flow=EDataFlow.eRender.value,
                                               device_state=DEVICE_STATE.ACTIVE.value):
        enumerator = device.AudioSessionManager.GetSessionEnumerator()
        for index in range(enumerator.GetCount()):
            raw = enumerator.GetSession(index)
            if raw is None:
                continue
            session = AudioSession(raw.QueryInterface(IAudioSessionControl2))
            try:
                process = session.Process
                if (session.State != 2 and process is not None
                        and process.name().casefold() == "spotify.exe"):
                    controls.append(session.SimpleAudioVolume)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return controls


def _spotify_audio(action, percent=None):
    if not IS_WINDOWS:
        raise RuntimeError("Spotify app volume requires Windows and its desktop client.")
    import comtypes

    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    try:
        controls = _spotify_audio_controls()
        if not controls:
            raise RuntimeError("Spotify has no active Windows audio session. Play a song in Spotify, then try again.")
        if action in {"mute", "unmute"}:
            muted = action == "mute"
            for control in controls:
                control.SetMute(int(muted), None)
            if any(bool(control.GetMute()) != muted for control in controls):
                raise RuntimeError("Windows didn't confirm Spotify's mute setting. Check the app volume mixer.")
            return "Spotify muted." if muted else "Spotify unmuted."
        targets = []
        for control in controls:
            if action == "set":
                target = percent / 100
            else:
                delta = 0.1 if action == "volume up" else -0.1
                target = max(0.0, min(1.0, control.GetMasterVolume() + delta))
            control.SetMasterVolume(target, None)
            targets.append(target)
        if any(abs(control.GetMasterVolume() - target) > 0.005
               for control, target in zip(controls, targets)):
            raise RuntimeError("Windows didn't confirm Spotify's volume setting. Check the app volume mixer.")
        # A positive set/increase also restores a previously muted app session.
        # Lowering the volume preserves the user's mute state.
        if action in {"set", "volume up"}:
            for control, target in zip(controls, targets):
                if target > 0:
                    control.SetMute(0, None)
                    if control.GetMute():
                        raise RuntimeError("Spotify's volume changed, but Windows couldn't unmute its audio session.")
        if max(targets) - min(targets) < 0.005:
            return f"Spotify volume set to {round(targets[0] * 100)} percent."
        return "Spotify volume increased." if action == "volume up" else "Spotify volume decreased."
    except (ImportError, OSError) as error:
        raise RuntimeError("Windows couldn't access Spotify's app volume. Restart Spotify and try again.") from error
    finally:
        comtypes.CoUninitialize()


def media_key(action):
    if not IS_WINDOWS:
        raise RuntimeError("System media controls require Windows.")
    if action in {"mute", "unmute"}:
        import comtypes
        from pycaw.pycaw import AudioUtilities
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            AudioUtilities.GetSpeakers().EndpointVolume.SetMute(1 if action == "mute" else 0, None)
        finally:
            comtypes.CoUninitialize()
        return "System audio muted." if action == "mute" else "System audio unmuted."
    code = {"mute": 0xAD, "unmute": 0xAD, "volume down": 0xAE, "volume up": 0xAF}[action]
    ctypes.windll.user32.keybd_event(code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(code, 0, 2, 0)
    return "System volume updated."


def set_volume(percent):
    if not IS_WINDOWS:
        raise RuntimeError("Volume adjustment requires Windows.")
    import comtypes
    from pycaw.pycaw import AudioUtilities
    value = max(0, min(100, int(percent)))
    comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    try:
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        endpoint.SetMasterVolumeLevelScalar(value / 100, None)
    finally:
        comtypes.CoUninitialize()
    return f"Volume set to {value} percent."


def gpu_usage():
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,name", "--format=csv,noheader,nounits"],
                                    capture_output=True, text=True, timeout=3, creationflags=NO_WINDOW)
            if result.returncode == 0:
                value, name = result.stdout.strip().splitlines()[0].split(",", 1)
                return float(value), name.strip()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if IS_WINDOWS:
        try:
            result = powershell("$ErrorActionPreference='Stop'; $v=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | Group-Object {$_.Name -replace '^pid_\\d+_',''} | ForEach-Object {($_.Group | Measure-Object UtilizationPercentage -Sum).Sum} | Measure-Object -Maximum; if($null -ne $v.Maximum){[string]$v.Maximum}", timeout=6)
            if result:
                return min(100, float(result)), "Windows GPU engine"
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            pass
    return None, "GPU telemetry unavailable"
