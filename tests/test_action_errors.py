from types import SimpleNamespace

import pytest

from jarvis.assistant import Assistant
from jarvis.core import Store


@pytest.mark.parametrize("action,client", [
    ("chrome_search", "Chrome"), ("chrome_type", "Chrome"), ("chrome_submit", "Chrome"),
    ("search_web", "Chrome"), ("spotify_play_song", "Spotify"), ("spotify", "Spotify"),
])
def test_native_errors_have_useful_diagnostics_without_payloads(action, client):
    failure = OSError("private request headers and typed text must stay private")
    failure.winerror = -2147024891
    result = Assistant.action_error(action, failure)
    assert result.startswith(client)
    assert "0x80070005" in result
    assert "Check Desktop Controls.cmd" in result
    assert "private" not in result


def test_supported_action_errors_keep_their_user_guidance():
    assert Assistant.action_error("spotify_play_song", RuntimeError("Spotify is not signed in.")) == "Spotify is not signed in."
    assert Assistant.action_error("chrome_type", ValueError("Use one line.")) == "Use one line."


def test_command_worker_continues_after_desktop_import_failure(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.update_settings({"ai_provider": "Local commands"})
    worker = Assistant(store, SimpleNamespace(discover=lambda: None), SimpleNamespace(say=lambda text: None))
    replies = []
    worker.response.connect(replies.append)
    execute = worker.execute
    def fail_search(action, argument):
        if action == "chrome_search":
            raise ImportError("do not print arbitrary module error payload")
        return execute(action, argument)
    monkeypatch.setattr(worker, "execute", fail_search)
    worker.queue.put(("command", "search Chrome for weather"))
    worker.queue.put(("command", "add task Worker still responds"))
    worker.queue.put(None)
    worker._run_commands()
    assert len(replies) == 2
    assert "Chrome" in replies[0] and "ImportError" in replies[0]
    assert "arbitrary" not in replies[0]
    assert store.tasks[0]["text"] == "Worker still responds"
