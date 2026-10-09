# JARVIS for Windows

**[Download JARVIS 1.2 for Windows 10/11](https://github.com/xavierpring1-svg/SAY-CHEESE-PIZZA/raw/refs/heads/main/downloads/JARVIS-Windows.zip?v=1.2.0)**

Extract the whole ZIP and open **JARVIS.exe**. Run **Create Desktop Shortcut.cmd**
to put it on your desktop. No Python installation or AI API key is needed.
Use this download link, rather than GitHub's source-code Download ZIP button.

**Upgrading:** choose **Quit JARVIS** in the old app first. Extract 1.2 into a new
folder and recreate your shortcut. Your saved tasks and settings stay in AppData.

## What's changed

- A redesigned dashboard with an animated cyan reactor, real microphone waveform,
  utilisation charts, readable conversation history, and editable recognized words.
- British male neural speech, clearer spoken prose, interruption, and a Windows
  audio-start fix. Recognition stays available while a reply is being prepared.
- Separate wake detection and offline Whisper transcription, bounded silence
  detection, input gain, microphone selection, sample-rate conversion, and audio warnings.
- Inline commands aren't interrupted by a wake greeting. An existing user utterance
  finishes before a queued greeting or reply starts speaking.
- Natural command wording, spoken numbers, greetings by name, and follow-up prompts.
- Built-in local conversation AI, with automatic first-use setup and visible progress.

## First launch

Windows 10/11, **64-bit Intel/AMD**, with a microphone and speakers/headset.

1. Extract **the entire ZIP**, then double-click **JARVIS.exe**.
2. Let voice setup finish. It downloads the official Vosk wake model (40 MB) and
   Whisper English transcription model (118 MB). Microphone audio remains on your PC.
3. Built-in conversation separately downloads a 19 MB CPU runtime and the official
   Qwen conversation model (about 1.1 GB). Allow roughly **3 GB of free disk space**
   and **2 GB of available memory**. Download speed and CPU affect setup/reply time.
   Core typed commands work while setup runs; natural conversation starts when the
   dashboard says it is ready. If setup fails, use **Settings → Enable natural conversation**
   to retry. You can choose **Local commands** to use desktop commands without AI.
4. Allow desktop microphone access in Windows Settings. Open Spotify, sign in,
   and play a track once so its Windows media session becomes available.
5. Run **Create Desktop Shortcut.cmd** and keep the extracted folder in place.

## Talk to JARVIS

Say **Hey Jarvis**, then your request in one sentence. Or click **Listen** and speak
when the app says **Listening**. Clap twice, roughly 0.2–0.8 seconds apart, to show
JARVIS, hear **Good morning, boss**, and request Spotify playback.

| Say or type | What happens |
| --- | --- |
| Hey Jarvis, say hello to Sarah | Says a greeting using Sarah's name |
| Can you say good morning, everyone | Speaks the requested words |
| Could you open Chrome | Opens a discovered app |
| Play Hello by Adele | Selects a matching Spotify song and verifies playback |
| Pause music / next song / previous track | Controls Spotify's media session |
| Set the volume to forty percent | Sets system volume to 40% |
| Add task buy a birthday cake | Saves a task in the UI |
| Add a task | Asks for the task text, then accepts your follow-up |
| Complete the first task | Completes task 1 |
| Search Chrome for weather tomorrow | Types and submits a Chrome search |
| Type in the search bar pizza near me | Writes literal text in Chrome's address bar |
| Search that | Searches the unchanged pending Chrome text |
| What time is it / system status | Speaks local time or available utilisation |
| Go to sleep | Hides to the system tray and keeps wake detection armed |

With conversation ready, you can also ask open-ended questions and discuss ideas.
The local model can request the implemented desktop actions; it can still make mistakes.
JARVIS cannot perform every possible PC action or reproduce all fictional movie abilities.

Follow-up listening stays open for 45 seconds after a command or reply. Speak after
JARVIS finishes, or press **Listen / Stop reply** to interrupt. The app briefly waits
for its audio to settle before opening the microphone. Closing the window enters sleep;
**Quit JARVIS** stops listening and closes its local AI server.

## If the words are wrong

Watch the live microphone meter and **Heard** text. Use **Edit words** to correct and
send what you meant. Low-confidence basic recognition asks you to repeat instead of
executing an uncertain command.

- In Settings, select your actual headset/microphone, then restart. Avoid Stereo Mix
  or speaker-loopback devices. The app avoids those when choosing a default.
- If the meter barely moves, increase **Microphone gain** gradually. If you see a clipping
  warning, lower gain or move farther from the microphone.
- Use a headset while Spotify plays. Music and room noise can cause transcription
  errors or false clap/wake detections. Tune clap threshold for your room.
- Keep **Enhanced offline transcription (Whisper)** enabled. If its download fails,
  basic Vosk recognition remains available; restart to retry enhanced setup.
- Compact Vosk is the default for fast wake detection. The 128 MB Vosk model is an
  optional alternative; a larger model doesn't guarantee better results for every voice.
- Names, accents, quiet speech, and songs can still be misheard. This release was
  tested with recorded speech clips, not your microphone; local testing is necessary.

## Speech and privacy

The default voice is **Ryan, British English**. Microsoft's online speech service
receives the **text of spoken replies**, and needs internet. Temporary response audio
is deleted afterward. It isn't an exact copy of the film actor's voice.

Choose **Settings → Speech output → Windows voice · offline** to keep speech offline.
Install English (United Kingdom) speech through **Windows voice settings** if you want
an installed British fallback voice. Speech speed and volume are adjustable.

After model setup, recognition and built-in conversation run locally. The conversation
server binds only to `127.0.0.1`, uses a random session token, and exits on Quit.
Downloads use official HTTPS sources; the CPU runtime and conversation model verify
publisher-provided hashes. Vosk/Whisper archives also check integrity, size, and safe paths;
where no publisher checksum exists, their saved hashes are identified as locally observed.

Optional **Ollama (local)** uses your separately installed model. Optional **OpenAI**
needs your API key and incurs provider charges; it receives text requests, history,
and action results. The key stays in memory and is never saved to settings or logs.

## Spotify, Chrome, and applications

A Premium Web API is not used. Named-song playback uses the Spotify desktop client's
English accessibility controls and confirms the selected song is playing through Windows
media metadata. SpotX layout changes, adverts, missing metadata, and account restrictions
can prevent playback. JARVIS reports failure when it cannot verify playback.
**Search Spotify for Queen** only opens results.

Chrome dictation identifies the browser's actual address bar and enters punctuation
literally. **Search that** requires the same bar to remain focused and unchanged.
Searches use Chrome's configured search engine. It stops if another window or a web form
gets focus. Install desktop Google Chrome to use these commands.

Applications are discovered from Start Menu shortcuts, Windows registrations, and Store
app IDs. Add portable apps through **Applications → Register an app shortcut**.
Ambiguous names need a more specific app name. Administrative apps may show Windows'
normal elevation prompt.

Tasks, settings, and models live in `%LOCALAPPDATA%\JarvisDesktop`. GPU metrics use
NVIDIA's driver utility or Windows engine counters; unsupported drivers show **N/A**.

## Troubleshooting and source

- **Startup fails:** run **Debug JARVIS.cmd**. The native launcher is unsigned.
- **No microphone:** Windows privacy settings must permit desktop microphone access.
- **Voice setup:** allow HTTPS to `alphacephei.com`, `github.com`, `api.github.com`, and
  `release-assets.githubusercontent.com`.
- **Conversation setup:** allow `huggingface.co` and its model CDN hosts. Retry from
  Settings after checking your connection, free disk space, and memory.
- **No natural speech:** test the voice and allow `speech.platform.bing.com`, or select
  offline Windows speech. A failed online request falls back without muting the mic
  throughout synthesis, and uses a retry cooldown.
- **Missing Microsoft runtime:** install Microsoft's x64 Visual C++ 2015–2022 Redistributable
  from https://aka.ms/vs/17/release/vc_redist.x64.exe.

See [VALIDATION.md](VALIDATION.md) for tests and unverified Windows behavior.
The public download and SHA256 are in `downloads/`. Source is in `main.py` and `jarvis/`.
`package-manifest.json` in the ZIP records verified dependency hashes and bundled source
hashes. Develop with Python **3.12**: install `requirements-dev.txt`, then run `python main.py`.
Run `python -m pytest -q`; Linux UI rendering uses `QT_QPA_PLATFORM=offscreen`.

Independent fan-inspired project. Dependency licenses are retained in runtime metadata;
llama.cpp is MIT, Qwen is Apache 2.0, and Whisper/sherpa-onnx retain their upstream licenses.
The previous pizza project remains in `pizza-backup-20261009`, with its old Pages source
in `pizza-pages-backup-20261009`.
