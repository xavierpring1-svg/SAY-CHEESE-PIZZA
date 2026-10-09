# Validation report

Tested on 9 October 2026 in the cloud's Linux environment, using Python 3.12.14,
PySide6 6.9.3, pytest 8.4.2, and Qt's offscreen platform.

127 tests passed for version 1.1.0. They exercise command parsing; durable task creation, completion,
and deletion; preservation of damaged settings; double-clap timing, echo rejection,
sustained-tone rejection, and cooldown; sleep/wake and speech-feedback gating;
UI task/settings integration; double-clap greeting and requested Spotify startup;
threaded command delivery to the GUI; AI tool-call routing; and safe model extraction.

New checks cover quoted song-name routing, Spotify UI song/artist matching and stale
result rejection, Windows media metadata and PLAYING confirmation, optional metadata,
timeouts and cancellation, literal Unicode Chrome dictation and search submission,
UIA browser ancestry and foreground checks, delayed native input processing, changed
pending text refusal, COM reference cleanup, and repeated wake phrases preserving
Chrome focus. Speech tests cover British Ryan voice selection, cancellable synthesis
and MCI playback, Windows fallback, temporary audio cleanup, and online retry cooldown.
Windows adapters and service requests in these checks use mocks; they do not run
against the user's Chrome or SpotX installation.

Spotify session tests use a fake Windows media session, including a playback refusal.
The Windows session API, COM initialisation, and volume API signatures were checked
against the exact bundled packages. These checks do not validate live Spotify playback.
No API key was supplied; conversational routing was tested with a simulated provider.

The real Qt dashboard was rendered and visually inspected. The native launcher is a
Windows x64 GUI PE executable with standard Windows DLL imports. The release includes
the CPython runtime, Qt Windows platform plugin, PortAudio, Vosk, and WinRT projections.
Runtime and published wheel checksums were verified against NuGet/PyPI metadata.
The updated download page was checked at desktop and mobile widths. The portable
builder now trims Qt using PE dependency closure, checks ZIP integrity and the GitHub
size limit, and records hashes of bundled source files alongside dependency hashes.

Not exercised here: Windows launch on a physical PC; microphone recording; recognition
of real spoken audio; live clap sensitivity; online British voice service availability;
Windows MCI/SAPI speech output; Chrome UI Automation; SpotX playback;
real GPU counters; or live Ollama/OpenAI requests. The official voice-model host is
blocked in this cloud runtime, so the Windows app downloads the model at first launch.
The required cloud network domain has been saved for user review, but is not applied.

Run Debug JARVIS.cmd if the Windows launch fails. Follow README.md to connect Spotify,
check the microphone, test British speech, and enable optional conversation.
