import json
from types import SimpleNamespace

import pytest

from jarvis.assistant import Assistant
from jarvis.core import Store, parse_command


@pytest.mark.parametrize("text,expected", [
    ("Hey Jarvis, search up anything on the tab", ("chrome_submit", "")),
    ("please search up what I typed", ("chrome_submit", "")),
    ("search up what's on the tab", ("chrome_submit", "")),
    ("search up what I typed in Chrome", ("chrome_submit", "")),
    ("search up that on Google Chrome", ("chrome_submit", "")),
    ("search up the text on the tab using Chrome", ("chrome_submit", "")),
    ('search up "what I typed" in Chrome', ("chrome_search", "what I typed")),
    ('search up "Fish & Chips?"', ("chrome_search", "Fish & Chips?")),
    ("search up \"What's Up?\" in Chrome", ("chrome_search", "What's Up?")),
    ("skip this song on SpotX", ("spotify", "next")),
    ("next track on Spotify", ("spotify", "next")),
    ("replay song", ("spotify", "replay")),
    ("restart the current song", ("spotify", "replay")),
    ("restart the song on SpotX", ("spotify", "replay")),
    ("repeat this track", ("spotify", "replay")),
    ("SpotX volume forty percent", ("spotify_volume", "40")),
    ("set Spotify volume to seventy five percent", ("spotify_volume", "75")),
    ("set volume to fifty on SpotX", ("spotify_volume", "50")),
    ("volume of SpotX to 25%", ("spotify_volume", "25")),
    ("mute SpotX", ("spotify_audio", "mute")),
    ("unmute music", ("spotify_audio", "unmute")),
    ("turn Spotify volume up", ("spotify_audio", "volume up")),
    ("lower SpotX volume", ("spotify_audio", "volume down")),
    ("volume up on SpotX", ("spotify_audio", "volume up")),
    ("tell me about the Moon", ("knowledge", "the Moon")),
    ("tell me information on Ada Lovelace", ("knowledge", "Ada Lovelace")),
    ("research quantum mechanics", ("knowledge", "quantum mechanics")),
    ('say "replay song"', ("say", "replay song")),
    ('play "Replay" on SpotX', ("spotify_play_song", "Replay")),
])
def test_new_command_phrases_preserve_intent(text, expected):
    assert parse_command(text) == expected


def assistant(tmp_path):
    return Assistant(Store(tmp_path), None, SimpleNamespace(say=lambda text: None))


def test_new_commands_reach_spotify_and_chrome_not_system_audio(tmp_path, monkeypatch):
    worker = assistant(tmp_path)
    calls = []
    monkeypatch.setattr(worker.spotify, "control", lambda action: calls.append(("transport", action)) or "OK")
    monkeypatch.setattr(worker.spotify, "set_volume", lambda volume: calls.append(("spotify_volume", volume)) or "OK")
    monkeypatch.setattr(worker.spotify, "adjust_volume", lambda action: calls.append(("spotify_audio", action)) or "OK")
    monkeypatch.setattr(worker.chrome, "search", lambda query: calls.append(("chrome", query)) or "OK")
    monkeypatch.setattr("jarvis.assistant.set_volume", lambda value: pytest.fail("music volume must not change system sound"))
    for text in ["replay song", "SpotX volume 40%", "mute SpotX", "google pizza near me"]:
        assert worker.execute(*parse_command(text)) == "OK"
    assert calls == [("transport", "replay"), ("spotify_volume", "40"),
                     ("spotify_audio", "mute"), ("chrome", "pizza near me")]


def test_knowledge_uses_real_lookup_contract(tmp_path, monkeypatch):
    worker = assistant(tmp_path)
    monkeypatch.setattr("jarvis.assistant.lookup", lambda topic: f"{topic}: sourced summary")
    assert worker.execute(*parse_command("tell me about the Moon")) == "the Moon: sourced summary"


def test_local_model_can_request_new_tools_and_receive_results(tmp_path, monkeypatch):
    import io
    worker = assistant(tmp_path)
    worker.brain = SimpleNamespace(ready=True, endpoint="http://127.0.0.1:12345/v1/chat/completions", token="test-session")
    requests = []
    replies = iter([
        {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "lookup", "function": {"name": "desktop_action", "arguments": json.dumps({"action": "knowledge", "argument": "Moon"})}},
        ]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "The Moon orbits Earth. Source: Wikipedia."}}]},
    ])
    def opened(request, timeout):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps(next(replies)).encode())
    monkeypatch.setattr("urllib.request.OpenerDirector.open", lambda self, request, timeout: opened(request, timeout))
    monkeypatch.setattr("jarvis.assistant.lookup", lambda topic: "Moon: Earth's natural satellite. Source: https://en.wikipedia.org/wiki/Moon")
    assert "orbits Earth" in worker.converse("Tell me something about the Moon")
    actions = requests[0]["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
    assert {"knowledge", "spotify_volume", "spotify_audio"} <= set(actions)
    assert requests[1]["messages"][-1]["role"] == "tool"
    assert "https://en.wikipedia.org/wiki/Moon" in requests[1]["messages"][-1]["content"]
