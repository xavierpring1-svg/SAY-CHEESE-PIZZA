import asyncio
from types import SimpleNamespace

import pytest

from jarvis.spotify_desktop import (
    PlaybackState, SongPlayback, SongResult, WindowsSpotifyUI, _requested_song,
    read_windows_playback,
)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, duration):
        self.now += duration


class FakeUI:
    def __init__(self, song):
        self.song = song
        self.searches = []
        self.clicks = []

    def open_search(self, query):
        self.searches.append(query)

    def find_song(self, query):
        return self.song

    def invoke_song(self, song):
        self.clicks.append(song)


def automation(song, states, **kwargs):
    ui, clock = FakeUI(song), Clock()
    states = iter(states)
    last = None

    async def read():
        nonlocal last
        last = next(states, last)
        return last

    player = SongPlayback(ui, read, clock=clock, sleep=clock.sleep,
                          search_timeout=1, playback_timeout=1, **kwargs)
    return player, ui, clock


def test_song_selection_waits_for_actual_spotify_playback():
    song = SongResult("Bohemian Rhapsody", "Queen")
    player, ui, _ = automation(song, [
        PlaybackState("Spotify.exe", "Old Song", "Other Artist", True),
        PlaybackState("Spotify.exe", song.title, song.artist, False),
        PlaybackState("Spotify.exe", song.title, song.artist, True),
    ])
    assert asyncio.run(player.play_song("Bohemian Rhapsody by Queen")) == "Playing Bohemian Rhapsody by Queen, boss."
    assert ui.searches == ["Bohemian Rhapsody by Queen"]
    assert ui.clicks == [song]


@pytest.mark.parametrize("state", [
    None,
    PlaybackState("Spotify.exe", "Old Song", "Queen", True),
    PlaybackState("Spotify.exe", "Bohemian Rhapsody", "Cover Band", True),
    PlaybackState("Spotify.exe", "Bohemian Rhapsody", "Queen", False),
    PlaybackState("not-spotify.exe", "Bohemian Rhapsody", "Queen", True),
    PlaybackState("chrome.exe", "Bohemian Rhapsody", "Queen", True),
])
def test_missing_paused_wrong_song_artist_or_source_never_claims_success(state):
    song = SongResult("Bohemian Rhapsody", "Queen")
    player, ui, clock = automation(song, [state])
    with pytest.raises(RuntimeError, match="couldn't confirm"):
        asyncio.run(player.play_song("Bohemian Rhapsody"))
    assert ui.clicks == [song]
    assert clock.now == pytest.approx(1)


def test_unsupported_layout_wait_is_bounded_and_never_clicks():
    player, ui, clock = automation(None, [])
    with pytest.raises(RuntimeError, match="accessible matching song"):
        asyncio.run(player.play_song("A Song"))
    assert not ui.clicks
    assert clock.now == pytest.approx(1)


def test_mismatched_search_result_is_refused_before_any_action():
    player, ui, _ = automation(SongResult("An Unrelated Song", "Someone"), [])
    with pytest.raises(RuntimeError, match="Refusing"):
        asyncio.run(player.play_song("The Requested Song"))
    assert not ui.clicks


def test_cancellation_before_launch_and_before_click():
    player, ui, _ = automation(SongResult("My Song"), [], cancelled=lambda: True)
    with pytest.raises(RuntimeError, match="cancelled"):
        asyncio.run(player.play_song("My Song"))
    assert not ui.searches
    assert not ui.clicks

    checks = iter([False, False, True])
    player, ui, _ = automation(SongResult("My Song"), [], cancelled=lambda: next(checks))
    with pytest.raises(RuntimeError, match="cancelled"):
        asyncio.run(player.play_song("My Song"))
    assert ui.searches == ["My Song"]
    assert not ui.clicks


@pytest.mark.parametrize("query", ["", "  ", "???", "hello\nworld", "x\x00y", "a" * 301])
def test_invalid_queries_do_not_open_apps(query):
    player, ui, _ = automation(None, [])
    with pytest.raises(ValueError):
        asyncio.run(player.play_song(query))
    assert not ui.searches


def test_unicode_and_punctuation_are_normalised_for_media_verification():
    song = SongResult("Señorita", "Shawn Mendes")
    player, _, _ = automation(song, [PlaybackState(
        "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "SEÑORITA", "Shawn Mendes", True)])
    assert "Playing SEÑORITA" in asyncio.run(player.play_song("senorita by shawn mendes"))
    assert _requested_song("Sweet Child O' Mine", "Sweet Child O’ Mine")
    assert not _requested_song("Stay", "Stay With Me")


def test_deep_link_query_is_literal_unicode_data(monkeypatch):
    import os
    uris = []
    monkeypatch.setattr(os, "startfile", uris.append, raising=False)
    ui = object.__new__(WindowsSpotifyUI)
    ui.open_search('Señorita & "Home"/{ESC}')
    assert uris == ["spotify:search:Se%C3%B1orita%20%26%20%22Home%22%2F%7BESC%7D"]


class Element:
    def __init__(self, name="", control_type="Group", children=(), class_name=""):
        self.name, self.children = name, list(children)
        self._parent = None
        self.element_info = SimpleNamespace(control_type=control_type, class_name=class_name,
                                            automation_id="", process_id=123)
        for child in self.children:
            child._parent = self
        self.invocations = 0

    def descendants(self, control_type=None):
        result = []
        for child in self.children:
            if control_type is None or child.element_info.control_type == control_type:
                result.append(child)
            result.extend(child.descendants(control_type=control_type))
        return result

    def parent(self):
        return self._parent

    def window_text(self):
        return self.name

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def set_focus(self):
        pass

    def invoke(self):
        self.invocations += 1


def ui_for(window):
    ui = object.__new__(WindowsSpotifyUI)
    ui.window = window
    ui._find_window = lambda: window
    return ui


def test_ui_selects_song_not_album_with_same_title():
    album_button = Element("Play Home by Artist", "Button")
    song_button = Element("Play Home by Artist", "Button")
    window = Element(children=[
        Element(children=[Element("Album", "Text"), album_button]),
        Element(children=[Element("Songs", "Text"), song_button]),
    ])
    result = ui_for(window).find_song("Home by Artist")
    assert result.title == "Home"
    assert result.artist == "Artist"
    assert result.button is song_button
    assert not album_button.invocations


def test_plain_play_button_cannot_be_guessed_from_an_entire_results_list():
    first_play, second_play = Element("Play", "Button"), Element("Play", "Button")
    window = Element(children=[Element(children=[
        Element("Songs", "Text"),
        Element(children=[Element("Wrong Song", "Text"), first_play]),
        Element(children=[Element("Wanted Song", "Text"), second_play]),
    ])])
    assert ui_for(window).find_song("Wanted Song") is None


def test_top_result_song_plain_play_is_supported():
    play = Element("Play", "Button")
    window = Element(children=[Element(children=[
        Element("Top result", "Text"), Element("Song", "Text"),
        Element("Wanted Song", "Text"), play,
    ])])
    song = ui_for(window).find_song("Wanted Song")
    assert song.title == "Wanted Song"
    assert song.button is play


def test_top_result_song_plain_play_supports_explicit_artist():
    play = Element("Play", "Button")
    window = Element(children=[Element(children=[
        Element("Top result", "Text"), Element("Song", "Text"),
        Element("Wanted Song", "Text"), Element("The Artist", "Hyperlink"), play,
    ])])
    song = ui_for(window).find_song("Wanted Song by The Artist")
    assert song.title == "Wanted Song"
    assert song.artist == "The Artist"
    assert song.button is play


def test_song_label_prefix_does_not_confuse_a_title_beginning_with_song():
    assert WindowsSpotifyUI._label_song("Play Song 2 by Blur", "Song 2") == ("Song 2", "Blur")
    assert WindowsSpotifyUI._label_song("Play song Home by Artist", "Home") == ("Home", "Artist")


def test_title_only_play_label_resolves_requested_artist_from_its_song_scope(monkeypatch):
    foreground(monkeypatch)
    play = Element("Play Hello", "Button")
    window = Element(children=[Element(children=[
        Element("Song", "Text"), Element("Hello", "Text"),
        Element("Adele", "Hyperlink"), play,
    ])])
    ui = ui_for(window)
    song = ui.find_song("Hello by Adele")
    assert (song.title, song.artist) == ("Hello", "Adele")
    ui.invoke_song(song)
    assert play.invocations == 1


def test_title_only_play_label_does_not_guess_the_requested_artist():
    play = Element("Play Hello", "Button")
    window = Element(children=[Element(children=[
        Element("Song", "Text"), Element("Hello", "Text"),
        Element("Cover Band", "Hyperlink"), play,
    ])])
    assert ui_for(window).find_song("Hello by Adele") is None
    assert play.invocations == 0


def test_title_only_play_label_revalidates_artist_before_invocation(monkeypatch):
    foreground(monkeypatch)
    play, artist = Element("Play Hello", "Button"), Element("Adele", "Hyperlink")
    window = Element(children=[Element(children=[
        Element("Song", "Text"), Element("Hello", "Text"), artist, play,
    ])])
    ui = ui_for(window)
    song = ui.find_song("Hello by Adele")
    artist.name = "Cover Band"
    with pytest.raises(RuntimeError, match="selected artist changed"):
        ui.invoke_song(song)
    assert play.invocations == 0


def test_media_properties_none_is_a_retryable_transition(monkeypatch):
    import sys
    from types import ModuleType

    playing = object()
    properties = iter([None, SimpleNamespace(title="Hello", artist="Adele")])
    playback_reads = []

    class Session:
        source_app_user_model_id = "Spotify.exe"

        async def try_get_media_properties_async(self):
            return next(properties)

        def get_playback_info(self):
            playback_reads.append(True)
            return SimpleNamespace(playback_status=playing)

    class Manager:
        @staticmethod
        async def request_async():
            return SimpleNamespace(get_sessions=lambda: [Session()])

    for name in ["winrt", "winrt.windows", "winrt.windows.media"]:
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    control = ModuleType("winrt.windows.media.control")
    control.GlobalSystemMediaTransportControlsSessionManager = Manager
    control.GlobalSystemMediaTransportControlsSessionPlaybackStatus = SimpleNamespace(PLAYING=playing)
    monkeypatch.setitem(sys.modules, "winrt.windows.media.control", control)
    assert asyncio.run(read_windows_playback()) is None
    assert not playback_reads
    assert asyncio.run(read_windows_playback()) == PlaybackState("Spotify.exe", "Hello", "Adele", True)
    assert playback_reads == [True]


def test_track_row_accessible_marker_is_supported_without_section_heading():
    play = Element("Play Song With By Inside by The Artist", "Button")
    row = Element(children=[play], class_name="main-trackList-trackListRow")
    window = Element(children=[row])
    song = ui_for(window).find_song("Song With By Inside by The Artist")
    assert song.title == "Song With By Inside"
    assert song.artist == "The Artist"


def foreground(monkeypatch, process=123):
    import jarvis.spotify_desktop as module

    def fill_process(handle, pointer):
        pointer._obj.value = process

    user32 = SimpleNamespace(GetForegroundWindow=lambda: 1, GetWindowThreadProcessId=fill_process)
    monkeypatch.setattr(module.ctypes, "windll", SimpleNamespace(user32=user32), raising=False)


def test_focus_loss_refuses_to_invoke_any_control(monkeypatch):
    foreground(monkeypatch, process=999)
    play = Element("Play Home by Artist", "Button")
    window = Element(children=[Element(children=[Element("Song", "Text"), play])])
    with pytest.raises(RuntimeError, match="take focus"):
        ui_for(window).invoke_song(SongResult("Home", "Artist", button=play))
    assert not play.invocations


def test_stale_result_refuses_play_before_invocation(monkeypatch):
    foreground(monkeypatch)
    play = Element("Play Different Song by Artist", "Button")
    window = Element(children=[Element(children=[Element("Song", "Text"), play])])
    with pytest.raises(RuntimeError, match="selected song changed"):
        ui_for(window).invoke_song(SongResult("Home", "Artist", button=play))
    assert not play.invocations


def test_play_is_invoked_once_on_selected_window_control(monkeypatch):
    foreground(monkeypatch)
    play = Element("Play Home by Artist", "Button")
    window = Element(children=[Element(children=[Element("Song", "Text"), play])])
    ui_for(window).invoke_song(SongResult("Home", "Artist", button=play))
    assert play.invocations == 1
