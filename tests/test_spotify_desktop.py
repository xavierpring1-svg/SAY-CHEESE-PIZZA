import asyncio
from types import SimpleNamespace

import pytest

from jarvis.spotify_desktop import (
    PlaybackState, SongPlayback, SongResult, SpotifyTransport, WindowsSpotifyUI, _requested_song,
    read_session_playback, read_windows_playback,
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


class TransportSession:
    def __init__(self, accepted=True, seek_enabled=True):
        self.calls = []
        self.accepted = accepted
        self.seek_enabled = seek_enabled

    async def try_skip_next_async(self):
        self.calls.append("next")
        return self.accepted

    async def try_skip_previous_async(self):
        self.calls.append("previous")
        return self.accepted

    async def try_change_playback_position_async(self, ticks):
        self.calls.append(("seek", ticks))
        return self.accepted

    async def try_play_async(self):
        self.calls.append("play")
        return self.accepted

    def get_playback_info(self):
        return SimpleNamespace(controls=SimpleNamespace(is_playback_position_enabled=self.seek_enabled))


def transport(states, **kwargs):
    session, clock = TransportSession(), Clock()
    iterator, last = iter(states), None

    async def read(expected_session):
        assert expected_session is session
        nonlocal last
        last = next(iterator, last)
        return last

    controller = SpotifyTransport(session, read, clock=clock, sleep=clock.sleep,
                                  timeout=1, **kwargs)
    return controller, session, clock


def test_next_waits_for_track_change_in_the_targeted_spotify_session():
    old = PlaybackState("Spotify.exe", "Old Song", "Artist", True, 30)
    new = PlaybackState("Spotify.exe", "New Song", "Artist", True, 0)
    controller, session, clock = transport([old, None, old, new])
    assert asyncio.run(controller.control("next")) == "Skipped to New Song by Artist."
    assert session.calls == ["next"]
    assert clock.now > 0


def test_previous_can_restart_the_current_song_as_spotify_normally_does():
    controller, session, _ = transport([
        PlaybackState("Spotify.exe", "Song", "Artist", True, 30),
        PlaybackState("Spotify.exe", "Song", "Artist", True, 0.3),
    ])
    assert asyncio.run(controller.control("previous")) == "Restarted Song by Artist."
    assert session.calls == ["previous"]


def test_previous_track_change_can_be_verified_while_paused():
    controller, session, _ = transport([
        PlaybackState("Spotify.exe", "Second", "Artist", False),
        PlaybackState("Spotify.exe", "First", "Artist", False),
    ])
    assert asyncio.run(controller.control("previous")) == "Returned to First by Artist (paused)."
    assert session.calls == ["previous"]


@pytest.mark.parametrize("action", ["next", "previous", "replay"])
def test_rejected_transport_operation_never_claims_success(action):
    controller, session, _ = transport([PlaybackState("Spotify.exe", "Song", "Artist", True, 30)])
    session.accepted = False
    with pytest.raises(RuntimeError, match="declined"):
        asyncio.run(controller.control(action))
    assert len(session.calls) == 1


@pytest.mark.parametrize("action", ["next", "previous", "replay"])
def test_accepted_command_with_unchanged_state_is_not_reported_as_success(action):
    controller, session, clock = transport([PlaybackState("Spotify.exe", "Song", "Artist", True, 30)])
    with pytest.raises(RuntimeError, match="couldn't confirm"):
        asyncio.run(controller.control(action))
    assert clock.now == pytest.approx(1)
    assert session.calls


def test_replay_seeks_the_timeline_start_and_confirms_same_song_is_playing():
    old = PlaybackState("Spotify.exe", "Song", "Artist", False, 45, 5)
    controller, session, _ = transport([
        old, old, PlaybackState("Spotify.exe", "Song", "Artist", True, 5.2, 5),
    ])
    assert asyncio.run(controller.control("replay")) == "Replaying Song by Artist, boss."
    assert session.calls == [("seek", 50_000_000), "play"]


@pytest.mark.parametrize("state", [
    PlaybackState("Spotify.exe", "Wrong Song", "Artist", True, 0),
    PlaybackState("Spotify.exe", "Song", "Wrong Artist", True, 0),
    PlaybackState("Spotify.exe", "Song", "Artist", False, 0),
    PlaybackState("not-spotify.exe", "Song", "Artist", True, 0),
])
def test_replay_requires_same_spotify_song_at_start_and_playing(state):
    controller, _, _ = transport([PlaybackState("Spotify.exe", "Song", "Artist", True, 30), state])
    with pytest.raises(RuntimeError, match="couldn't confirm"):
        asyncio.run(controller.control("replay"))


@pytest.mark.parametrize("action", ["next", "previous", "replay"])
def test_initial_untrusted_session_prevents_transport_commands(action):
    controller, session, _ = transport([PlaybackState("not-spotify.exe", "Song", "Artist", True, 30)])
    with pytest.raises(RuntimeError, match="couldn't read"):
        asyncio.run(controller.control(action))
    assert not session.calls


@pytest.mark.parametrize("action", ["next", "previous", "replay"])
def test_cancelled_transport_never_touches_spotify(action):
    controller, session, _ = transport([], cancelled=lambda: True)
    with pytest.raises(RuntimeError, match="cancelled"):
        asyncio.run(controller.control(action))
    assert not session.calls


def test_replay_does_not_replace_seek_with_previous_track_if_seek_is_unavailable():
    controller, session, _ = transport([PlaybackState("Spotify.exe", "Song", "Artist", True, 30)])
    session.seek_enabled = False
    with pytest.raises(RuntimeError, match="doesn't allow replay"):
        asyncio.run(controller.control("replay"))
    assert not session.calls

    controller, session, _ = transport([PlaybackState("Spotify.exe", "Song", "Artist", True)])
    with pytest.raises(RuntimeError, match="seek position"):
        asyncio.run(controller.control("replay"))
    assert not session.calls


def test_session_reader_converts_winrt_timedelta_positions_to_seconds(monkeypatch):
    import sys
    from datetime import timedelta
    from types import ModuleType

    playing = object()
    module = ModuleType("winrt.windows.media.control")
    module.GlobalSystemMediaTransportControlsSessionPlaybackStatus = SimpleNamespace(PLAYING=playing)
    monkeypatch.setitem(sys.modules, "winrt.windows.media.control", module)

    async def properties():
        return SimpleNamespace(title="Song", artist="Artist")

    session = SimpleNamespace(
        source_app_user_model_id="Spotify.exe",
        try_get_media_properties_async=properties,
        get_playback_info=lambda: SimpleNamespace(playback_status=playing),
        get_timeline_properties=lambda: SimpleNamespace(position=timedelta(seconds=45.5),
                                                        start_time=timedelta(seconds=5)),
    )
    assert asyncio.run(read_session_playback(session)) == PlaybackState(
        "Spotify.exe", "Song", "Artist", True, 45.5, 5)


@pytest.mark.parametrize("dependency", ["comtypes", "_ctypes", "jarvis.uia"])
def test_native_uia_dependency_import_error_is_identified(monkeypatch, dependency):
    import builtins
    import jarvis.spotify_desktop as module

    original_import = builtins.__import__
    error = ModuleNotFoundError(f"No module named '{dependency}'", name=dependency)

    def import_module(name, *args, **kwargs):
        if name == "uia":
            raise error
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(builtins, "__import__", import_module)
    with pytest.raises(RuntimeError, match=dependency) as failure:
        WindowsSpotifyUI()
    assert "needs the pywinauto" not in str(failure.value)
    assert failure.value.__cause__ is error


def test_native_uia_import_failure_preserves_actual_dependency_message(monkeypatch):
    import builtins
    import jarvis.spotify_desktop as module

    original_import = builtins.__import__
    error = ImportError("DLL load failed while importing _ctypes: The specified module could not be found.")

    def import_module(name, *args, **kwargs):
        if name == "uia":
            raise error
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(builtins, "__import__", import_module)
    with pytest.raises(RuntimeError, match="DLL load failed while importing _ctypes") as failure:
        WindowsSpotifyUI()
    assert failure.value.__cause__ is error


def test_native_uia_initialization_failure_is_identified(monkeypatch):
    import sys
    import jarvis.spotify_desktop as module
    from types import ModuleType

    def desktop(**kwargs):
        raise OSError("UI Automation COM interface unavailable")

    uia = ModuleType("jarvis.uia")
    uia.Desktop = desktop
    monkeypatch.setitem(sys.modules, "jarvis.uia", uia)
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="couldn't initialize: UI Automation COM interface unavailable"):
        WindowsSpotifyUI()


def track_row(title="Hello", artist="Adele", album="25", *, button=None):
    name = Element(title, "Text", class_name="main-trackList-rowTitle")
    performer = Element(artist, "Hyperlink")
    column = Element(children=[name, performer])
    row = Element(children=[column, Element(children=[Element(album, "Hyperlink")])],
                  control_type="DataItem", class_name="main-trackList-trackListRow")
    if button is not None:
        button._parent = row
        row.children.append(button)
    return row, name, performer


def test_track_row_without_play_button_is_matched_and_targeted_natively(monkeypatch):
    foreground(monkeypatch)
    row, _, _ = track_row()
    window = Element(children=[row])
    ui = ui_for(window)
    song = ui.find_song("Hello by Adele")
    assert song is not None
    assert (song.title, song.artist) == ("Hello", "Adele")
    assert song.button is None and song.row is row
    ui.invoke_song(song)
    assert row.invocations == 1


def test_track_row_with_play_button_hidden_until_hover_still_has_targeted_action(monkeypatch):
    foreground(monkeypatch)
    button = Element("Play Hello by Adele", "Button")
    button.is_visible = lambda: False
    row, _, _ = track_row(button=button)
    window = Element(children=[row])
    ui = ui_for(window)
    song = ui.find_song("Hello by Adele")
    assert song.row is row
    ui.invoke_song(song)
    assert row.invocations == 1
    assert not button.invocations


def test_title_artist_cell_is_supported_without_title_css_class(monkeypatch):
    row, title, _ = track_row()
    title.element_info.class_name = ""
    window = Element(children=[row])
    song = ui_for(window).find_song("Hello by Adele")
    assert song is not None and song.row is row


@pytest.mark.parametrize("query", ["25", "Adele", "Hello by 25", "Hello by Other Artist"])
def test_row_artist_or_album_cells_are_not_guessed_as_requested_song(query):
    row, _, _ = track_row()
    window = Element(children=[row])
    assert ui_for(window).find_song(query) is None
    assert not row.invocations


def test_unclassified_result_card_is_not_activated_as_a_track():
    card, _, _ = track_row()
    card.element_info.class_name = "album-result"
    window = Element(children=[card])
    assert ui_for(window).find_song("Hello by Adele") is None
    assert not card.invocations


def test_none_uia_automation_id_does_not_discard_valid_track_row():
    button = Element("Play Hello by Adele", "Button")
    row, _, _ = track_row(button=button)
    row.element_info.automation_id = None
    window = Element(children=[row])
    song = ui_for(window).find_song("Hello by Adele")
    assert song is not None and song.button is button


@pytest.mark.parametrize("changed", ["title", "artist"])
def test_recycled_track_row_is_revalidated_before_native_action(monkeypatch, changed):
    foreground(monkeypatch)
    row, title, artist = track_row()
    ui = ui_for(Element(children=[row]))
    song = ui.find_song("Hello by Adele")
    (title if changed == "title" else artist).name = "Different"
    with pytest.raises(RuntimeError, match="selected song or artist changed"):
        ui.invoke_song(song)
    assert not row.invocations


def test_track_row_focus_loss_prevents_action(monkeypatch):
    foreground(monkeypatch, process=999)
    row, _, _ = track_row()
    ui = ui_for(Element(children=[row]))
    song = ui.find_song("Hello by Adele")
    with pytest.raises(RuntimeError, match="take focus"):
        ui.invoke_song(song)
    assert not row.invocations


def test_track_row_without_supported_native_pattern_reports_precise_failure(monkeypatch):
    foreground(monkeypatch)
    row, _, _ = track_row()
    ui = ui_for(Element(children=[row]))
    song = ui.find_song("Hello by Adele")

    def unsupported():
        raise RuntimeError("No supported UIA action")

    row.invoke = unsupported
    with pytest.raises(RuntimeError, match="doesn't expose a supported playback action"):
        ui.invoke_song(song)


def test_row_default_action_that_only_selects_never_claims_song_playback(monkeypatch):
    foreground(monkeypatch)
    row, _, _ = track_row()
    ui = ui_for(Element(children=[row]))
    ui.open_search = lambda query: None
    clock = Clock()

    async def read():
        return PlaybackState("Spotify.exe", "Previous Song", "Other Artist", True)

    player = SongPlayback(ui, read, clock=clock, sleep=clock.sleep,
                          search_timeout=1, playback_timeout=1)
    with pytest.raises(RuntimeError, match="couldn't confirm it is playing"):
        asyncio.run(player.play_song("Hello by Adele"))
    assert row.invocations == 1
    assert clock.now == pytest.approx(1)
