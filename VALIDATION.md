# Validation report

Tested on 9 October 2026 in the cloud's Linux environment, using Python 3.12.14,
PySide6 6.9.3, pytest 8.4.2, and Qt's offscreen platform.

25 tests passed. They exercise command parsing; durable task creation, completion,
and deletion; preservation of damaged settings; double-clap timing, echo rejection,
sustained-tone rejection, and cooldown; sleep/wake and speech-feedback gating;
UI task/settings integration; double-clap greeting and requested Spotify startup;
threaded command delivery to the GUI; AI tool-call routing; and safe model extraction.

Spotify session tests use a fake Windows media session, including a playback refusal.
The Windows session API, COM initialisation, and volume API signatures were checked
against the exact bundled packages. These checks do not validate live Spotify playback.
No API key was supplied; conversational routing was tested with a simulated provider.

The real Qt dashboard was rendered and visually inspected. The native launcher is a
Windows x64 GUI PE executable with standard Windows DLL imports. The release includes
the CPython runtime, Qt Windows platform plugin, PortAudio, Vosk, and WinRT projections.
Runtime and published wheel checksums were verified against NuGet/PyPI metadata.

Not exercised here: Windows launch on a physical PC; microphone recording; recognition
of real spoken audio; live clap sensitivity; Windows speech output; SpotX playback;
real GPU counters; or live Ollama/OpenAI requests. The official voice-model host is
blocked in this cloud runtime, so the Windows app downloads the model at first launch.
The required cloud network domain has been saved for user review, but is not applied.

Run Debug JARVIS.cmd if the Windows launch fails. Follow README.md to connect Spotify,
check the microphone, select a British voice, and enable optional conversation.
