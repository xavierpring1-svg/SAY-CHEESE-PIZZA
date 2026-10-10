"""Mock Windows APIs: routing and truthful results, without desktop access."""
import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

import jarvis.windows as windows


class Volume:
    def __init__(self, volume=0.5, muted=False, ignore_volume=False, ignore_mute=False):
        self.volume, self.muted = volume, muted
        self.ignore_volume, self.ignore_mute = ignore_volume, ignore_mute
        self.calls = []

    def GetMasterVolume(self):
        return self.volume

    def SetMasterVolume(self, value, context):
        self.calls.append(("volume", value))
        if not self.ignore_volume:
            self.volume = value

    def GetMute(self):
        return self.muted

    def SetMute(self, value, context):
        self.calls.append(("mute", value))
        if not self.ignore_mute:
            self.muted = bool(value)


def audio(monkeypatch, controls):
    com_calls = []
    comtypes = ModuleType("comtypes")
    comtypes.COINIT_MULTITHREADED = 0
    comtypes.CoInitializeEx = lambda mode: com_calls.append("init")
    comtypes.CoUninitialize = lambda: com_calls.append("uninit")
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setattr(windows, "IS_WINDOWS", True)
    monkeypatch.setattr(windows, "_spotify_audio_controls", lambda: controls)
    return windows.Spotify(), com_calls


def test_spotify_volume_changes_each_app_session_and_unmutes_them(monkeypatch):
    first, second = Volume(0.9, muted=True), Volume(0.1)
    spotify, com_calls = audio(monkeypatch, [first, second])
    assert spotify.set_volume("40") == "Spotify volume set to 40 percent."
    assert first.volume == second.volume == 0.4
    assert not first.muted and not second.muted
    assert com_calls == ["init", "uninit"]


def test_relative_volume_is_clamped_and_preserves_mute_when_lowering(monkeypatch):
    volume = Volume(0.04, muted=True)
    spotify, _ = audio(monkeypatch, [volume])
    assert spotify.adjust_volume("volume down") == "Spotify volume set to 0 percent."
    assert volume.muted
    assert spotify.adjust_volume("volume up") == "Spotify volume set to 10 percent."
    assert not volume.muted
    volume.volume = 0.99
    assert spotify.adjust_volume("volume up") == "Spotify volume set to 100 percent."


def test_mute_and_unmute_are_explicit_for_all_spotify_sessions(monkeypatch):
    first, second = Volume(), Volume()
    spotify, _ = audio(monkeypatch, [first, second])
    assert spotify.adjust_volume("mute") == "Spotify muted."
    assert first.muted and second.muted
    assert spotify.adjust_volume("unmute") == "Spotify unmuted."
    assert not first.muted and not second.muted
    assert first.volume == second.volume == 0.5


def test_volume_readback_failure_is_reported_and_com_is_released(monkeypatch):
    volume = Volume(ignore_volume=True)
    spotify, com_calls = audio(monkeypatch, [volume])
    with pytest.raises(RuntimeError, match="didn't confirm Spotify's volume"):
        spotify.set_volume(10)
    assert com_calls == ["init", "uninit"]


def test_mute_readback_failure_is_reported_and_com_is_released(monkeypatch):
    spotify, com_calls = audio(monkeypatch, [Volume(ignore_mute=True)])
    with pytest.raises(RuntimeError, match="didn't confirm Spotify's mute"):
        spotify.adjust_volume("mute")
    assert com_calls == ["init", "uninit"]


def test_missing_spotify_sessions_do_not_adjust_system_sound(monkeypatch):
    spotify, com_calls = audio(monkeypatch, [])
    with pytest.raises(RuntimeError, match="no active Windows audio session"):
        spotify.set_volume(40)
    assert com_calls == ["init", "uninit"]


@pytest.mark.parametrize("value", [-1, 101, "invalid", None])
def test_invalid_volume_does_not_touch_windows_audio(monkeypatch, value):
    volume = Volume()
    spotify, com_calls = audio(monkeypatch, [volume])
    with pytest.raises(ValueError, match="0 to 100"):
        spotify.set_volume(value)
    assert not volume.calls and not com_calls


def test_linux_audio_request_gives_useful_windows_requirement(monkeypatch):
    monkeypatch.setattr(windows, "IS_WINDOWS", False)
    with pytest.raises(RuntimeError, match="requires Windows"):
        windows.Spotify().set_volume(40)


def test_session_enumeration_targets_only_spotify_across_render_devices(monkeypatch):
    selections = []
    volumes = [Volume() for _ in range(4)]
    sessions = [
        SimpleNamespace(Process=SimpleNamespace(name=lambda: "Spotify.exe"), State=1,
                        SimpleAudioVolume=volumes[0]),
        SimpleNamespace(Process=SimpleNamespace(name=lambda: "chrome.exe"), State=1,
                        SimpleAudioVolume=volumes[1]),
        SimpleNamespace(Process=SimpleNamespace(name=lambda: "not-spotify.exe"), State=1,
                        SimpleAudioVolume=volumes[2]),
        SimpleNamespace(Process=SimpleNamespace(name=lambda: "SPOTIFY.EXE"), State=0,
                        SimpleAudioVolume=volumes[3]),
        SimpleNamespace(Process=SimpleNamespace(name=lambda: "Spotify.exe"), State=2,
                        SimpleAudioVolume=Volume()),
        SimpleNamespace(Process=None, State=1, SimpleAudioVolume=Volume()),
    ]

    def device(items):
        enumerator = SimpleNamespace(GetCount=lambda: len(items),
                                     GetSession=lambda index: SimpleNamespace(QueryInterface=lambda kind: items[index]))
        manager = SimpleNamespace(GetSessionEnumerator=lambda: enumerator)
        return SimpleNamespace(AudioSessionManager=manager)

    def devices(**kwargs):
        selections.append(kwargs)
        return [device(sessions[:3]), device(sessions[3:])]

    pycaw = ModuleType("pycaw.pycaw")
    pycaw.AudioUtilities = SimpleNamespace(GetAllDevices=devices)
    utils = ModuleType("pycaw.utils")
    utils.AudioSession = lambda raw: raw
    policy = ModuleType("pycaw.api.audiopolicy")
    policy.IAudioSessionControl2 = object()
    constants = ModuleType("pycaw.constants")
    constants.EDataFlow = SimpleNamespace(eRender=SimpleNamespace(value=0))
    constants.DEVICE_STATE = SimpleNamespace(ACTIVE=SimpleNamespace(value=1))
    for name, module in [("pycaw.pycaw", pycaw), ("pycaw.utils", utils),
                         ("pycaw.api.audiopolicy", policy), ("pycaw.constants", constants)]:
        monkeypatch.setitem(sys.modules, name, module)
    assert windows._spotify_audio_controls() == [volumes[0], volumes[3]]
    assert selections == [{"data_flow": 0, "device_state": 1}]
    assert not volumes[1].calls and not volumes[2].calls


def test_windows_media_session_identity_is_exact_not_a_substring(monkeypatch):
    sources = ["not-spotify.exe", "chrome.exe", "SpotifyAB.SpotifyMusic_store!Spotify"]
    sessions = [SimpleNamespace(source_app_user_model_id=source) for source in sources]
    control = ModuleType("winrt.windows.media.control")

    async def request():
        return SimpleNamespace(get_sessions=lambda: sessions)

    control.GlobalSystemMediaTransportControlsSessionManager = SimpleNamespace(request_async=request)
    monkeypatch.setitem(sys.modules, "winrt.windows.media.control", control)
    assert asyncio.run(windows.Spotify()._session()) is sessions[-1]
