"""Select a song in Spotify's Windows UI and verify its media-session state.

No Web API, account credentials, private Spotify endpoints, or global keyboard
shortcuts are used. An inaccessible/changed client layout fails explicitly.
The Windows adapter needs validation on the user's installed Spotify client.
"""
from __future__ import annotations

import asyncio
import ctypes
import os
import platform
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(character for character in value if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


def _spotify_source(source: str) -> bool:
    source = source.casefold().replace("\\", "/")
    return (source in {"spotify", "spotify.exe"}
            or source.endswith("/spotify.exe")
            or source.startswith("spotifyab.spotifymusic_")
            or source.startswith("spotify.spotify_"))


def _requested_song(query: str, title: str, artist: str = "") -> bool:
    """Match a title, optionally followed by the artist, without guessing."""
    requested, track, performer = map(_normalise, (query, title, artist))
    if not track:
        return False
    choices = {track}
    if performer:
        choices.update({f"{track} {performer}", f"{track} by {performer}"})
    return requested in choices


@dataclass(frozen=True)
class SongResult:
    title: str
    artist: str = ""
    button: Any = field(default=None, repr=False, compare=False)
    row: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class PlaybackState:
    source: str
    title: str
    artist: str
    playing: bool
    position: float | None = None
    start: float = 0.0


async def read_session_playback(session) -> PlaybackState | None:
    """Read metadata and seek position from one already identified session."""
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus

    properties = await session.try_get_media_properties_async()
    if properties is None:
        return None
    info = session.get_playback_info()
    if info is None:
        return None
    position, start = None, 0.0
    try:
        timeline = session.get_timeline_properties()
        position = timeline.position.total_seconds()
        start = timeline.start_time.total_seconds()
    except (AttributeError, OSError, RuntimeError):
        # Metadata still supports song and skip verification when this client
        # does not publish its timeline. Replay requires a readable position.
        pass
    return PlaybackState(
        session.source_app_user_model_id, properties.title or "", properties.artist or "",
        info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING,
        position, start,
    )


async def read_windows_playback() -> PlaybackState | None:
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    for session in manager.get_sessions():
        source = session.source_app_user_model_id
        if not _spotify_source(source):
            continue
        state = await read_session_playback(session)
        # WinRT returns None while the client is switching tracks or starting.
        # Let the bounded verification loop retry that transitional state.
        if state is None:
            continue
        return state
    return None


class SpotifyTransport:
    """Skip/replay a specific Spotify session, then observe the result."""

    def __init__(self, session, read_playback=None, *,
                 cancelled: Callable[[], bool] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 timeout: float = 6):
        self.session = session
        self.read_playback = read_playback or read_session_playback
        self.cancelled = cancelled or (lambda: False)
        self.clock, self.sleep, self.timeout = clock, sleep, timeout

    def _check_cancelled(self):
        if self.cancelled():
            raise RuntimeError("Spotify playback request cancelled.")

    async def _read(self, deadline):
        self._check_cancelled()
        try:
            return await asyncio.wait_for(self.read_playback(self.session),
                                          timeout=min(1.5, max(0.01, deadline - self.clock())))
        except (OSError, RuntimeError, asyncio.TimeoutError):
            return None

    async def _operate(self, operation):
        self._check_cancelled()
        try:
            return await asyncio.wait_for(operation(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise RuntimeError("Spotify didn't respond to the playback command. Check Spotify and try again.") from None

    @staticmethod
    def _same_track(first, second):
        return (_normalise(first.title) == _normalise(second.title)
                and _normalise(first.artist) == _normalise(second.artist))

    @staticmethod
    def _valid(state):
        return bool(state and _spotify_source(state.source) and state.title.strip())

    async def control(self, action: str) -> str:
        if action not in {"next", "previous", "replay"}:
            raise ValueError("Use next, previous, or replay for Spotify playback.")
        deadline = self.clock() + self.timeout
        initial = None
        while self.clock() < deadline:
            initial = await self._read(deadline)
            if self._valid(initial):
                break
            await self.sleep(min(0.2, max(0, deadline - self.clock())))
        if not self._valid(initial):
            raise RuntimeError("I couldn't read Spotify's current track. Play a song in Spotify and try again.")
        self._check_cancelled()
        if action == "replay":
            if initial.position is None:
                raise RuntimeError("Spotify isn't exposing a seek position, so I can't safely replay this track.")
            info = self.session.get_playback_info()
            controls = getattr(info, "controls", None)
            if controls is not None and not controls.is_playback_position_enabled:
                raise RuntimeError("Spotify doesn't allow replay of the current item. Wait for any advert to finish.")
            # WinRT positions use 100 ns ticks, relative to the session's
            # timeline; previous-track is never used as a replay shortcut.
            if not await self._operate(lambda: self.session.try_change_playback_position_async(
                    round(initial.start * 10_000_000))):
                raise RuntimeError("Spotify declined the replay command. Check the current song or advert.")
            self._check_cancelled()
            if not await self._operate(self.session.try_play_async):
                raise RuntimeError("Spotify sought to the beginning but declined playback. Check Spotify.")
        else:
            operation = (self.session.try_skip_next_async if action == "next"
                         else self.session.try_skip_previous_async)
            if not await self._operate(operation):
                raise RuntimeError("Spotify declined that playback command. Check its current playback state.")
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            state = await self._read(deadline)
            if self._valid(state) and state.source.casefold() == initial.source.casefold():
                same = self._same_track(initial, state)
                at_start = (state.position is not None
                            and state.start <= state.position <= state.start + 2)
                restarted = (at_start and initial.position is not None
                             and initial.position > initial.start + 2)
                artist = f" by {state.artist}" if state.artist else ""
                if action == "replay" and same and at_start and state.playing:
                    return f"Replaying {state.title}{artist}, boss."
                if action != "replay" and (not same or restarted):
                    if same:
                        verb = "Restarted" if action == "previous" else "Skipped to"
                    else:
                        verb = "Skipped to" if action == "next" else "Returned to"
                    paused = " (paused)" if not state.playing else ""
                    return f"{verb} {state.title}{artist}{paused}."
            await self.sleep(min(0.2, max(0, deadline - self.clock())))
        raise RuntimeError("Spotify accepted the command, but I couldn't confirm the playback change. Check Spotify and try again.")


class WindowsSpotifyUI:
    """Conservative UIA adapter; never clicks an unclassified play control."""

    _OTHER_KINDS = {"album", "albums", "playlist", "playlists", "artist", "artists",
                    "podcast", "podcasts", "episode", "episodes", "audiobook", "audiobooks"}

    def __init__(self):
        if platform.system() != "Windows":
            raise RuntimeError("Song-name playback requires the Windows Spotify desktop client.")
        try:
            from .uia import Desktop
            self.desktop = Desktop(backend="uia")
        except ImportError as error:
            detail = " ".join(str(error).split())[:220]
            raise RuntimeError(f"Spotify's Windows automation couldn't load a required component: {detail}. Re-extract the complete JARVIS folder and run it from there.") from error
        except (OSError, RuntimeError) as error:
            detail = " ".join(str(error).split())[:220]
            raise RuntimeError(f"Spotify's Windows automation couldn't initialize: {detail}.") from error
        self.window = None

    @staticmethod
    def _marker(element):
        info = element.element_info
        return ((getattr(info, "class_name", "") or "") + " "
                + (getattr(info, "automation_id", "") or "")).casefold()

    @classmethod
    def _track_row(cls, element):
        marker = cls._marker(element)
        return "tracklistrow" in marker or "track-list-row" in marker

    def open_search(self, query: str):
        # A deep link encodes Unicode as data and cannot type into another app.
        try:
            os.startfile("spotify:search:" + urllib.parse.quote(query, safe=""))
        except OSError:
            raise RuntimeError("Windows couldn't open Spotify. Install its desktop client and sign in, then try again.") from None

    @staticmethod
    def _trusted_window(window) -> bool:
        try:
            import psutil
            return (window.is_visible()
                    and psutil.Process(window.element_info.process_id).name().casefold() == "spotify.exe")
        except Exception:
            return False

    def _find_window(self):
        if self.window is not None and self._trusted_window(self.window):
            return self.window
        for window in self.desktop.windows():
            if self._trusted_window(window):
                self.window = window
                return window
        return None

    def _song_scope(self, button):
        """Use an accessible Songs section or a Song top-result card."""
        scope = button
        for _ in range(5):
            try:
                scope = scope.parent()
                if scope is None or scope == self.window:
                    return None
                # Spotify's track rows have a stable semantic class when exposed.
                if self._track_row(scope):
                    return scope
                descendants = scope.descendants()
                # A whole screen containing both album and song results is not
                # evidence that this particular button belongs to a song.
                if len(descendants) > 100:
                    continue
                labels = {element.window_text().strip().casefold()
                          for element in descendants
                          if element.element_info.control_type in {"Text", "Hyperlink"}}
                if labels & self._OTHER_KINDS:
                    return None
                if labels & {"song", "songs"}:
                    return scope
            except Exception:
                return None
        return None

    @staticmethod
    def _label_song(label: str, query: str = "") -> tuple[str, str] | None:
        label = label.strip()
        match = re.match(r"^play\s+(.+)$", label, re.I)
        if not match:
            return None
        payload = match.group(1).strip()
        if re.match(r"^(?:album|playlist|artist|podcast|episode|audiobook)\b", payload, re.I):
            return None
        separators = list(re.finditer(r"\s+by\s+", payload, re.I))
        if separators:
            position = separators[-1]
            title, artist = payload[:position.start()].strip(), payload[position.end():].strip()
        else:
            title, artist = payload, ""
        # "Song" can be either a control-label prefix or part of the title.
        # Remove it only when the requested title disambiguates those cases.
        if (query and not _requested_song(query, title, artist)
                and title.casefold().startswith("song ")
                and _requested_song(query, title[5:], artist)):
            title = title[5:]
        return title, artist

    @staticmethod
    def _single_play_scope(scope) -> bool:
        """A plain Play button cannot be associated with a whole result list."""
        play_controls = [element for element in scope.descendants(control_type="Button")
                         if re.match(r"^play(?:\s|$)", element.window_text().strip(), re.I)]
        return len(play_controls) == 1

    @staticmethod
    def _row_column(row, element):
        """Keep the artist in the title's column, excluding the album column."""
        current = element
        for _ in range(20):
            parent = current.parent()
            if parent is None:
                return None
            if parent == row:
                return current
            current = parent
        return None

    @staticmethod
    def _row_texts(scope):
        result = []
        for element in scope.descendants():
            if element.element_info.control_type not in {"Text", "Hyperlink"}:
                continue
            value = element.window_text().strip()
            if value and _normalise(value) not in {_normalise(text) for text, _ in result}:
                result.append((value, element))
        return result

    def _row_song(self, row, query):
        if not self._track_row(row) or not row.is_visible() or not row.is_enabled():
            return None
        texts = self._row_texts(row)
        # Chromium exposes Spotify's DOM class through UIA ClassName. Prefer
        # the semantic title; never treat an album or artist link as a title.
        titles = [(text, element) for text, element in texts
                  if "tracklist-rowtitle" in self._marker(element)]
        if not titles:
            for text, element in texts:
                column = self._row_column(row, element)
                if column is None or column == element:
                    continue
                column_texts = self._row_texts(column)
                # A title/artist cell has both, whereas the separate album
                # cell exposes one name. Its first text is the song title.
                if len(column_texts) >= 2 and column_texts[0][1] == element:
                    titles.append((text, element))
        for title, element in titles:
            column = self._row_column(row, element)
            artist_texts = self._row_texts(column) if column is not None and column != element else []
            artists = [text for text, _ in artist_texts if _normalise(text) != _normalise(title)
                       and not re.fullmatch(r"\d+(?::\d{2})?", text)]
            for artist in artists:
                if _requested_song(query, title, artist):
                    return SongResult(title, artist, row=row)
            if _requested_song(query, title):
                return SongResult(title, row=row)
        return None

    def find_song(self, query: str) -> SongResult | None:
        window = self._find_window()
        if window is None:
            return None
        try:
            buttons = window.descendants(control_type="Button")
        except Exception:
            return None
        for button in buttons:
            try:
                label = button.window_text().strip()
                if not re.match(r"^play(?:\s|$)", label, re.I):
                    continue
                if not button.is_visible() or not button.is_enabled():
                    continue
                scope = self._song_scope(button)
                if scope is None:
                    continue
                parsed = self._label_song(label, query)
                if parsed and _requested_song(query, *parsed):
                    return SongResult(*parsed, button=button)
                if parsed and not parsed[1]:
                    # A track's Play label often contains just its title. Use
                    # the artist only when that same song scope exposes it.
                    for element in scope.descendants():
                        if element.element_info.control_type not in {"Text", "Hyperlink"}:
                            continue
                        artist = element.window_text().strip()
                        if _requested_song(query, parsed[0], artist):
                            return SongResult(parsed[0], artist, button=button)
                if label.casefold() != "play" or not self._single_play_scope(scope):
                    continue
                # Some Song top-result cards expose a plain Play button.
                texts = [element.window_text().strip() for element in scope.descendants()
                         if element.element_info.control_type in {"Text", "Hyperlink"}]
                for title in texts:
                    if _normalise(title) in {"song", "songs", "top result"}:
                        continue
                    if _requested_song(query, title):
                        return SongResult(title, button=button)
                    for artist in texts:
                        if artist != title and _requested_song(query, title, artist):
                            return SongResult(title, artist, button=button)
            except Exception:
                continue
        # Track rows can have a Play control only while hovered. A native UIA
        # default action targets the classified row itself, without typing or
        # clicking an unrelated window. Metadata still has to confirm playback.
        try:
            for row in window.descendants():
                try:
                    song = self._row_song(row, query)
                    if song is not None:
                        return song
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def invoke_song(self, song: SongResult):
        window = self._find_window()
        target = song.button if song.button is not None else song.row
        if window is None or target is None:
            raise RuntimeError("Spotify's song control is no longer available. Try the request again.")
        try:
            window.set_focus()
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
            foreground = user32.GetForegroundWindow()
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(foreground, ctypes.byref(process_id))
            if process_id.value != window.element_info.process_id:
                raise RuntimeError("Spotify couldn't take focus. Bring Spotify to the front and try again.")
            # Verify that the captured element still belongs to this Spotify
            # window. Invoke targets that exact element; no mouse/keyboard
            # fallback can hit an unrelated foreground application.
            current = target
            found_window = False
            for _ in range(20):
                if current == window:
                    found_window = True
                    break
                current = current.parent()
                if current is None:
                    break
            if not found_window or not target.is_visible() or not target.is_enabled():
                raise RuntimeError("Spotify's search results changed before selection. Try the request again.")
            if song.row is not None:
                query = song.title + (" by " + song.artist if song.artist else "")
                fresh = self._row_song(song.row, query)
                if (fresh is None or _normalise(fresh.title) != _normalise(song.title)
                        or (song.artist and _normalise(fresh.artist) != _normalise(song.artist))):
                    raise RuntimeError("Spotify's selected song or artist changed before playback. Try the request again.")
                try:
                    song.row.invoke()
                except Exception as error:
                    raise RuntimeError("Spotify's matching song row doesn't expose a supported playback action. Select this song in Spotify manually.") from error
                return
            label = song.button.window_text().strip()
            if not re.match(r"^play(?:\s|$)", label, re.I):
                raise RuntimeError("Spotify no longer offers Play for that result. Try the request again.")
            scope = self._song_scope(song.button)
            if scope is None:
                raise RuntimeError("Spotify's search results changed before selection. Try the request again.")
            texts = {element.window_text().strip() for element in scope.descendants()
                     if element.element_info.control_type in {"Text", "Hyperlink"}}
            query = song.title + (" by " + song.artist if song.artist else "")
            parsed = self._label_song(label, query)
            if parsed:
                if (_normalise(parsed[0]) != _normalise(song.title)
                        or (song.artist and parsed[1]
                            and _normalise(parsed[1]) != _normalise(song.artist))):
                    raise RuntimeError("Spotify's selected song changed before playback. Try the request again.")
                if (song.artist and not parsed[1]
                        and not any(_normalise(text) == _normalise(song.artist) for text in texts)):
                    raise RuntimeError("Spotify's selected artist changed before playback. Try the request again.")
            else:
                if not self._single_play_scope(scope):
                    raise RuntimeError("Spotify's search results changed before selection. Try the request again.")
                if not any(_normalise(text) == _normalise(song.title) for text in texts):
                    raise RuntimeError("Spotify's selected song changed before playback. Try the request again.")
                if song.artist and not any(_normalise(text) == _normalise(song.artist) for text in texts):
                    raise RuntimeError("Spotify's selected artist changed before playback. Try the request again.")
            song.button.invoke()
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError("Spotify doesn't expose an accessible Play action for this result. Select the song in Spotify manually.") from None


class SongPlayback:
    """Injectable orchestration, with bounded waits and verified success."""

    def __init__(self, ui, read_playback: Callable[[], Awaitable[PlaybackState | None]], *,
                 cancelled: Callable[[], bool] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 search_timeout: float = 10, playback_timeout: float = 10):
        self.ui, self.read_playback = ui, read_playback
        self.cancelled = cancelled or (lambda: False)
        self.clock, self.sleep = clock, sleep
        self.search_timeout, self.playback_timeout = search_timeout, playback_timeout

    def _check_cancelled(self):
        if self.cancelled():
            raise RuntimeError("Spotify song request cancelled.")

    async def play_song(self, query: str) -> str:
        query = query.strip()
        if not query or not _normalise(query):
            raise ValueError("Tell me the song name you want to play.")
        if len(query) > 300 or any(unicodedata.category(character) == "Cc" for character in query):
            raise ValueError("Use a song name under 300 characters without line breaks or control characters.")
        self._check_cancelled()
        self.ui.open_search(query)
        deadline = self.clock() + self.search_timeout
        song = None
        while self.clock() < deadline:
            self._check_cancelled()
            song = self.ui.find_song(query)
            if song is not None:
                if not _requested_song(query, song.title, song.artist):
                    raise RuntimeError("Spotify returned a different song. Refusing to select that result.")
                break
            await self.sleep(min(0.25, max(0, deadline - self.clock())))
        if song is None:
            raise RuntimeError("I opened Spotify results, but couldn't identify an accessible matching song control. Sign in and select the track manually; this Spotify layout may not support automatic selection.")
        self._check_cancelled()
        self.ui.invoke_song(song)
        deadline = self.clock() + self.playback_timeout
        while self.clock() < deadline:
            self._check_cancelled()
            try:
                state = await asyncio.wait_for(self.read_playback(), timeout=min(1.5, max(0.01, deadline - self.clock())))
            except (OSError, RuntimeError, asyncio.TimeoutError):
                state = None
            if (state and _spotify_source(state.source) and state.playing
                    and _normalise(state.title) == _normalise(song.title)
                    and (not song.artist or _normalise(state.artist) == _normalise(song.artist))):
                artist = f" by {state.artist}" if state.artist else ""
                return f"Playing {state.title}{artist}, boss."
            await self.sleep(min(0.25, max(0, deadline - self.clock())))
        raise RuntimeError("I selected the song in Spotify, but couldn't confirm it is playing. Check Spotify's playback, adverts, or connection and try again.")


def play_song(query: str, *, cancelled: Callable[[], bool] | None = None) -> str:
    """Windows entry point; owns the COM apartment used by UIA and WinRT."""
    if platform.system() != "Windows":
        raise RuntimeError("Song-name playback requires Windows and the Spotify desktop client.")
    from winrt.runtime import ApartmentType, init_apartment, uninit_apartment
    init_apartment(ApartmentType.MULTI_THREADED)
    try:
        ui = WindowsSpotifyUI()
        return asyncio.run(SongPlayback(ui, read_windows_playback, cancelled=cancelled).play_song(query))
    finally:
        uninit_apartment()
