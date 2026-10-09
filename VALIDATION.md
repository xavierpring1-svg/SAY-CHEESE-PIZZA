# Validation report — JARVIS 1.2

Validated on 9 October 2026 in Linux with Python 3.12, PySide 6.9.3,
pytest 8.4.2, Qt offscreen rendering, Vosk 0.3.45 and sherpa-onnx 1.13.8.

All 355 automated tests passed.

The automated suite covers natural command parsing, literal names/task/search/song
text, spoken numbers, persistent tasks/settings upgrades, clap timing, speech/wake
feedback gating, Windows media/control adapters, Chrome focus and input handling,
UI state delivery, reply interruption, and guarded model/archive extraction.

New speech checks cover Windows playback startup/position/completion, SAPI WAV output,
neural timeouts/fallback, readable spoken prose, microphone availability during
synthesis, and greetings waiting for an existing user utterance. Listening checks
cover 16 kHz conversion from 8/16/44.1/48 kHz, bounded silence segmentation, gain limits,
microphone selection, low-confidence repetition, inline wake commands, and greetings
by name. A microphone failure/retry check verifies fresh decoder queues, successful
command recognition after reconnecting, and cancellation of stale decoding work.
Conversation checks cover official runtime/model metadata and checksum
validation, resume/cancellation, local-only server/token lifecycle, and simulated
OpenAI-compatible action routing. External services in unit tests are mocked.

## Recorded-audio verification

Actual Vosk and Whisper engines were run against known recorded/synthesized WAVs.
Three FFmpeg Flite voices supplied 21 synthetic wake/command utterances. Compact Vosk
matched 10/21 full transcripts; 128 MB Vosk matched 9/21; Whisper Tiny matched 10/21,
with specific Chrome/song-name improvements. Bigger Whisper Base performed worse
on this set, so it is not the default. These clips do not prove universal microphone
accuracy or human accent performance.

The dedicated wake recognizer plus final utterance processing detected all 3 tested
standalone “Hey Jarvis” voices. The actual Whisper/Listener pipeline rejected all 6
“Hey Charles”/“Hey Travis” negatives. Constrained wake grammar alone produced those
false positives, so unrestricted transcription corroboration matters. Similar names
and background audio may still trigger mistakes.

Eight actual timing checks across 16/48 kHz, leading silence, and repeated utterances
passed after preserving Vosk's absolute sample timeline across resets. Recognition
was also run against Vosk's official recorded test WAV. No microphone audio is saved
by the app; test WAVs/results remain in the cloud's external validation cache.

## Packaging and UI

The redesigned Qt dashboard was rendered and visually inspected at 1280×850 and
1020×740. Settings and listening/preparing/speaking/setup states were checked.
The download page was checked at desktop and mobile widths.

The portable Windows package includes official CPython 3.12.10, verified PyPI wheels,
a native x64 launcher, Qt's Windows platform plugin, audio libraries, Vosk, Sherpa,
and WinRT projections. The builder checks official NuGet SHA512 and PyPI SHA256,
trims unused Qt/development files while retaining required DLLs/licenses, verifies ZIP
integrity and GitHub's 100 MiB limit, and records bundled source hashes.

Windows Sherpa binary imports and its exact Whisper API were checked. The official
llama.cpp CPU runtime archive was downloaded and checked against GitHub's published
SHA256; its server DLL closure and required Microsoft DLLs were verified. MIT/OpenMP
licenses are retained. The app downloads this runtime separately on first use.

## Still requires Windows testing

Not exercised on a physical PC: actual Windows launch, microphone input and room-noise
sensitivity, Windows MCI/SAPI audio playback, Chrome accessibility, SpotX playback,
GPU counters, and optional live AI providers. The Microsoft online speech service was
unreachable from this cloud. Hugging Face is blocked here, so the full Qwen model
was not downloaded and its real conversation/tool quality has not been tested.
The local conversation HTTP schema and lifecycle were tested with simulated responses.

Use Debug JARVIS.cmd if startup fails, and follow README.md
for microphone selection, model setup, speech fallback, and supported commands.
