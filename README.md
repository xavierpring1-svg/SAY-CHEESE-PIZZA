# JARVIS for Windows

## Download the desktop app

**[Download JARVIS for Windows 10/11 (80 MB ZIP)](https://github.com/xavierpring1-svg/SAY-CHEESE-PIZZA/raw/refs/heads/main/downloads/JARVIS-Windows.zip)**

Extract the whole ZIP, open **JARVIS.exe**, then run **Create Desktop Shortcut.cmd**.
Do not use GitHub's green **Code → Download ZIP** button for the desktop app; use the
link above, which includes the bundled Windows runtime.

[Download page](https://xavierpring1-svg.github.io/SAY-CHEESE-PIZZA/)
· [SHA256 checksum](downloads/JARVIS-Windows.sha256)
· [Validation details](VALIDATION.md)


A personal desktop assistant with a cyan reactor dashboard, offline speech recognition,
double-clap activation, speech replies, persistent tasks, application launching, Spotify
desktop controls, and live time, date, CPU, memory, and GPU telemetry.

## Start in three steps

1. Extract **the entire JARVIS-Windows.zip** into a permanent folder on your PC.
2. Open **JARVIS.exe**. At first launch it downloads the official Vosk English model
   (about 40 MB). Allow desktop apps to use the microphone in Windows privacy settings.
3. Run **Create Desktop Shortcut.cmd** to put JARVIS on your desktop. Keep the folder
   in place because the shortcut points to it. No Python installation is needed.

Windows 10/11, 64-bit Intel/AMD. This release was assembled and its UI/logic tested
in a Linux cloud machine. Windows-specific hardware and Spotify integration still
require testing on your PC. The launcher is unsigned. If startup fails, run
**Debug JARVIS.cmd** to see the error instead of a hidden window.

## Wake, sleep, and voice

- Say **Hey Jarvis**, then a command. Or clap twice, roughly 0.2–0.8 seconds apart.
- A double clap brings up the window and says **Good morning, boss.**
- Wake activation opens Spotify and requests playback if enabled in Settings.
- Click **Sleep mode** or say **go to sleep**. The app stays in the Windows system tray
  with its microphone listener running. Say the wake phrase or clap twice to bring it back.
- Double-click the tray icon to recover manually. Closing the window enters sleep;
  **Quit JARVIS** exits and stops listening.
- After a wake phrase or the Listen button, the conversation window remains open for
  25 seconds after your last command or speech reply. Say Hey Jarvis again to resume.
- Typed commands work even without a microphone or voice model.
- Use a headset to keep music from reaching the microphone. Adjust clap sensitivity in
  Settings for your microphone and room; false detections are possible in loud environments.
- The offline model is US English; accent and microphone quality affect transcription.

Speech uses installed Windows voices. It prefers British English when available.
In **Settings → Windows voice settings**, install English (United Kingdom) speech,
then restart JARVIS and select a voice. The voice has a composed assistant style;
it does not reproduce the actor's exact film voice. Replies pause recognition to avoid
hearing JARVIS's own speech, so speak after the reply finishes.

## Spotify and SpotX

Open Spotify, sign in, and play a track once so it exposes a Windows media session.
JARVIS then targets the Spotify session for play, pause, previous, and next, rather
than sending global play/pause keys to every player. A Premium playback API is not used.
SpotX is a modified client; its compatibility with Windows media sessions must be
checked locally. JARVIS does not modify Spotify or bypass account restrictions.

Examples: **play Spotify**, **pause music**, **next song**, **previous track**,
**volume 40**, **mute**, **unmute**. Optional wake playlist/track URI in Settings:
`spotify:playlist:YOUR_PLAYLIST_ID`.

**play [song or artist]** opens Spotify's search results; selecting a specific result
is done in Spotify. Automatic search-result playback is not claimed.

## Desktop commands and tasks

| Say or type | Result |
| --- | --- |
| Hey Jarvis, open Chrome | Launch a discovered application |
| open calculator | Open Calculator |
| add task buy groceries | Save a task and display it in My tasks |
| show my tasks | Read the saved list |
| complete task 1 | Complete task number 1 |
| remove task 2 | Remove task number 2 |
| what time is it | Speak local time and date |
| system status | Speak available utilisation statistics |
| search the web for pizza recipes | Open a browser search |
| go to sleep | Hide to the tray and keep wake detection armed |

Applications are discovered from Start Menu shortcuts, Windows app registrations, and
Store app IDs. Unregistered portable apps can be added in **Applications → Register an
app shortcut**. Ambiguous names need a more specific app name. Windows may require its
normal elevation prompt for administrative apps.

Tasks and settings live in `%LOCALAPPDATA%\JarvisDesktop`. The microphone choice is
applied after a restart. GPU metrics use NVIDIA's driver utility when present, or Windows
GPU engine counters; unsupported drivers display **N/A**, rather than a fabricated value.

## Conversational AI

Core commands work without an AI account. For open-ended conversation and natural
language action requests, choose a provider in Settings:

- **Ollama (local)**: click Install local conversational AI, or install Ollama from
  https://ollama.com/download/windows and run `ollama pull llama3.2`. This downloads
  about 2 GB and needs roughly 8 GB RAM. Choose **Ollama (local)**, model **llama3.2**,
  local address **http://127.0.0.1:11434**, and Save. Some models have limited tool support.
- **OpenAI**: enter your own API key, choose a compatible chat model (default
  `gpt-4.1-mini`), and Save. API usage is billed by the provider. The key stays in memory
  and must be re-entered after restarting. It is never written to settings or logs.
  Text requests, conversation history, and action results are sent to the provider.

The AI can call the implemented app, task, search, media, volume, clock, and telemetry
actions. It cannot perform every possible PC action or execute unrestricted shell
commands. It reports errors when an operation cannot be completed.

## Troubleshooting

- **No microphone**: Windows Settings → Privacy & security → Microphone → enable
  desktop-app access. Select the right microphone in JARVIS Settings and restart.
- **Model download fails**: allow HTTPS to `alphacephei.com`, then use Retry voice setup.
  Model files remain local after download, so recognition works offline afterward.
- **Spotify opened but did not play**: play one track manually, then issue play Spotify.
  Make sure its media session is available and its current account permits playback.
- **No speech**: select an installed voice, check Speech volume, and test it in Settings.
- **AI connection fails**: check the chosen model, API access, or that Ollama is running.
- **Missing VC++ runtime**: install Microsoft's x64 Visual C++ 2015–2022 Redistributable
  from https://aka.ms/vs/17/release/vc_redist.x64.exe and restart the app.

## Validation and source

The accompanying source is in `main.py` and `jarvis/`. The release bundles official
Python 3.12.10 from the Python Software Foundation NuGet package and Windows wheels
from PyPI. `package-manifest.json` records package versions and verified upstream hashes.
The first-run model download retains TLS verification and checks ZIP integrity and paths.

Development: install Python 3.12, run `python -m pip install -r requirements.txt`, then
`python main.py`. Tests: install pytest, run `python -m pytest -q`. Linux UI smoke:
`QT_QPA_PLATFORM=offscreen python main.py --demo --screenshot dashboard.png`.

This is an independent fan-inspired assistant, not an official Marvel product.
Bundled Python, Qt/PySide, Vosk, and other dependencies retain their upstream licenses
in the runtime and package metadata. The Vosk small English model is Apache 2.0.

## Repository replacement

The previous pizza project is preserved in `pizza-backup-20261009`. Its previous
GitHub Pages deployment is preserved in `pizza-pages-backup-20261009`.
The repository name is retained so existing links continue to resolve.
