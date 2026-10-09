from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "JarvisDesktop"

DEFAULTS = {
    "name": "Boss", "voice": "", "speech_engine": "neural", "speech_rate": -1, "speech_volume": 90,
    "clap_threshold": 0.16, "clap_enabled": True, "wake_enabled": True,
    "spotify_on_wake": True, "start_sleeping": False, "microphone": -1,
    "spotify_uri": "", "ai_provider": "Built-in AI (local)",
    "ai_model": "llama3.2", "ollama_url": "http://127.0.0.1:11434",
    "recognition_model": "compact", "enhanced_transcription": True,
    "microphone_gain": 1.0, "voice_confidence": 0.5,
    "conversation_setup": True,
}


class Store:
    def __init__(self, directory=DATA):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "settings.json"
        self.lock = threading.RLock()
        self.data = {"settings": DEFAULTS.copy(), "tasks": [], "apps": {}}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    settings = loaded.get("settings", {})
                    if not isinstance(settings, dict):
                        raise TypeError("Invalid settings data")
                    if "conversation_setup" not in settings and settings.get("ai_provider", "Local commands") == "Local commands":
                        settings = dict(settings, ai_provider="Built-in AI (local)")
                    self.data["settings"].update(settings)
                    self.data["tasks"] = loaded.get("tasks", [])
                    self.data["apps"] = loaded.get("apps", {})
            except (ValueError, OSError, TypeError):
                # Preserve damaged files for recovery instead of overwriting them.
                backup = self.directory / f"settings-recovery-{int(time.time())}.json"
                self.path.rename(backup)

    @property
    def settings(self):
        with self.lock:
            return self.data["settings"].copy()

    @property
    def tasks(self):
        with self.lock:
            return [task.copy() for task in self.data["tasks"]]

    def save(self):
        with self.lock:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)

    def update_settings(self, values):
        with self.lock:
            self.data["settings"].update(values)
            self.save()

    def add_task(self, text):
        text = text.strip()
        if not text:
            raise ValueError("Tell me what you want to add.")
        task = {"id": uuid.uuid4().hex, "text": text[:2000], "done": False,
                "created": time.time()}
        with self.lock:
            self.data["tasks"].append(task)
            self.save()
        return task

    def toggle_task(self, task_id, done):
        with self.lock:
            for task in self.data["tasks"]:
                if task["id"] == task_id:
                    task["done"] = bool(done)
            self.save()

    def remove_task(self, task_id):
        with self.lock:
            self.data["tasks"] = [t for t in self.data["tasks"] if t["id"] != task_id]
            self.save()


_SPOTIFY = r"(?:spotify|spot\s+if\s*y|spot\s+ify|spot\s*x)"
_CHROME = r"(?:(?:google\s*)?chrome)"
_QUOTES = {'"': '"', "'": "'", "“": "”", "‘": "’"}
_SMALL_NUMBERS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20)))
_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_ORDINAL_WORDS = dict(zip(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth".split(),
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety".split()))


def _spoken_number(text):
    """Parse explicit English number words, never guess homophones or evaluate code."""
    text = re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    if text in _SMALL_NUMBERS:
        return _SMALL_NUMBERS[text]
    words = text.split()
    if words and words[0] in _TENS:
        if len(words) == 1:
            return _TENS[words[0]]
        if len(words) == 2 and 1 <= _SMALL_NUMBERS.get(words[1], -1) <= 9:
            return _TENS[words[0]] + _SMALL_NUMBERS[words[1]]
    if len(words) >= 2 and words[1] == "hundred":
        hundreds = 1 if words[0] == "a" else _SMALL_NUMBERS.get(words[0], -1)
        if 1 <= hundreds <= 9:
            remainder = words[2:]
            if remainder and remainder[0] == "and":
                remainder = remainder[1:]
                if not remainder:
                    return None
            tail = _spoken_number(" ".join(remainder)) if remainder else 0
            if tail is not None and 0 <= tail < 100:
                return hundreds * 100 + tail
    return None


def _literal_argument(text):
    """Remove a matching quote pair and sentence punctuation outside it only."""
    text = text.strip()
    if text and text[0] in _QUOTES:
        closing = re.escape(_QUOTES[text[0]])
        match = re.fullmatch(re.escape(text[0]) + r"(.*)" + closing + r"\s*[.!?]*", text)
        if match:
            return match.group(1).strip(), True
    return text, False


def _task_number(text):
    words = text.lower().replace("-", " ").split()
    if words and words[-1] in _ORDINAL_WORDS:
        words[-1] = _ORDINAL_WORDS[words[-1]]
    return _spoken_number(" ".join(words))


def _command_prefix(text):
    polite = (r"^(?:please\b[,\s]+|kindly\b[,\s]+|"
              r"(?:can|could|would|will)\s+you\b[,\s]+|"
              r"i(?:'d| would)\s+like\s+you\s+to\b[,\s]+|"
              r"i\s+want\s+you\s+to\b[,\s]+|"
              r"do\s+me\s+a\s+favou?r\s+and\b[,\s]+)")
    while True:
        updated = re.sub(polite, "", text, count=1, flags=re.I)
        if updated == text:
            break
        text = updated
    # The optional "do" is structural only before a supported command verb.
    return re.sub(r"^do\s+(?=(?:add|create|remind|open|launch|start|search|google|type|write|play|pause|resume|set|complete|delete|remove|sleep|say|repeat|greet)\b)",
                  "", text, count=1, flags=re.I)


def _app_name(argument):
    argument, quoted = _literal_argument(argument)
    if not quoted:
        argument = argument.rstrip(".!?").strip()
    alias = re.sub(r"\s+", " ", argument.lower())
    if re.fullmatch(_SPOTIFY, alias):
        return "spotify"
    if alias in {"googlechrome", "google chrome"}:
        return "google chrome"
    if alias in {"chrome", "music", "browser", "internet"}:
        return alias
    return argument


def parse_command(text):
    """Recognize command structure while preserving literal task/song/search text."""
    # Do not remove Jarvis from Jarvison, possessives, or a command's argument.
    text = re.sub(r"^\s*(?:(?:hey|hi|hello)\s+)?(?:jarvis|jar\s+vus|jar\s+v\s+is)(?![\w'’])[,\s:.!?]*",
                  "", text, count=1, flags=re.I).strip()
    command = _command_prefix(text)
    normalized = command.lower().rstrip(".!?").strip()

    # Numeric arguments are normalized separately from literal parameters.
    numeric = [
        (r"(?:(?:set|change|adjust|turn)\s+)?(?:the\s+)?volume(?:\s+to)?\s+(.+?)(?:\s*(?:percent|per cent|%))?", "volume"),
        (r"(?:complete|finish|done with)\s+(?:the\s+)?task(?:\s+number)?\s+(.+)", "complete_task"),
        (r"(?:complete|finish)\s+(?:the\s+)?(.+?)\s+task", "complete_task"),
        (r"mark\s+(?:the\s+)?task(?:\s+number)?\s+(.+?)\s+(?:as\s+)?(?:complete|done|finished)", "complete_task"),
        (r"mark\s+(?:the\s+)?(.+?)\s+task\s+(?:as\s+)?(?:complete|done|finished)", "complete_task"),
        (r"(?:delete|remove)\s+(?:the\s+)?task(?:\s+number)?\s+(.+)", "remove_task"),
        (r"(?:delete|remove)\s+(?:the\s+)?(.+?)\s+task", "remove_task"),
    ]
    for pattern, action in numeric:
        match = re.fullmatch(pattern, normalized)
        if match:
            number = (_spoken_number if action == "volume" else _task_number)(match.group(1))
            if number is not None:
                return action, str(number)

    # These complete music requests contain no literal song name. Supporting
    # fused ASR tokens here does not turn words like "playground" into actions.
    if re.fullmatch(rf"(?:play\s*|start(?:\s+playing)?\s+|turn\s+on\s+|put\s+on\s+)(?:music|my music|some music|the music|{_SPOTIFY})(?:\s+(?:on|in|using)\s*{_SPOTIFY})?", normalized):
        return "spotify", "play"

    bar = rf"(?:the\s+)?(?:{_CHROME}\s+)?(?:search|address)\s*bar"
    patterns = [
        (r"(?:say (?:hello|hi) to|greet)\s+(.+)", "greet"),
        (r"(?:say|repeat)\s+(.+)", "say"),
        (r"create\s+(?:a\s+)?task\s+called\s+(.+)", "add_task"),
        (r"(?:add|create)\s+(?:a\s+)?task\b(?:\s*:\s*|\s+(?!:))(.+)", "add_task"),
        (r"new task(?:\s*:\s*|\s+(?!:))(.+)", "add_task"),
        (r"remind me to\s+(.+)", "add_task"),
        (r"add\s+(.+?)\s+to\s+(?:my\s+)?(?:tasks|task list)[.!?]*", "add_task"),
        (rf"(?:search(?:\s+(?:in|on))?\s+{_CHROME}(?:\s+for)?|{_CHROME}\s+search(?:\s+for)?)\s+(.+)", "chrome_search"),
        (rf"search(?:\s+for)?\s+(.+?)\s+(?:in|on|using)\s+{_CHROME}[.!?]*", "chrome_search"),
        (rf"(?:type|write)\s+(.+?)\s+(?:in|into|on)\s+(?:{bar}|{_CHROME})[.!?]*", "chrome_type"),
        (rf"(?:type|write)(?:\s+(?:in|into|on))?\s+(?:{bar}|{_CHROME})\s+(.+)", "chrome_type"),
        (rf"search(?:\s+(?:on|in))?\s+{_SPOTIFY}(?:\s+for)?\s+(.+)", "spotify_search"),
        (rf"search(?:\s+for)?\s+(.+?)\s+(?:on|in|using)\s+{_SPOTIFY}[.!?]*", "spotify_search"),
        (r"(?:search(?: the web)? for|google|look up)\s+(.+)", "search_web"),
        (r"(?:play|put on|start playing)\s+(.+)", "spotify_play_song"),
        (r"(?:open|launch|start)\s+(.+)", "open_app"),
    ]
    for pattern, action in patterns:
        match = re.fullmatch(pattern, command, re.I)
        if not match:
            continue
        argument = match.group(1).strip()
        if action == "open_app":
            argument = _app_name(argument)
            if argument in {"spotify", "music"}:
                return "spotify", "play"
        else:
            if action == "spotify_play_song":
                argument = re.sub(rf"\s+(?:on|in|using)\s*{_SPOTIFY}[.!?]*$", "", argument, flags=re.I).strip()
                called = re.fullmatch(r"(?:(?:the|a)\s+)?(?:song|track)\s+called\s+(.+)", argument, re.I)
                if called:
                    argument = called.group(1)
                else:
                    quoted_song = re.fullmatch(r"the\s+(?:song|track)\s+(.+)", argument, re.I)
                    if quoted_song and _literal_argument(quoted_song.group(1))[1]:
                        argument = quoted_song.group(1)
            argument, quoted = _literal_argument(argument)
            if action == "spotify_play_song" and not quoted:
                plain = argument.lower().rstrip(".!?").strip()
                if (re.fullmatch(_SPOTIFY, plain)
                        or plain in {"music", "my music", "some music", "the music"}):
                    return "spotify", "play"
        if argument:
            return action, argument
        return "conversation", text

    if normalized in {"search that", "search it", "submit search", "search in chrome", "chrome enter", "press enter in chrome"}:
        return "chrome_submit", ""
    if normalized in {"sleep", "go to sleep", "sleep mode", "standby", "stand by"}:
        return "sleep", ""
    if normalized in {"wake up", "wake", "hey", "hello", ""}:
        return "wake", ""
    if re.fullmatch(r"(?:what(?:'s| is)? |tell me |the )?(?:the )?(?:time|date)(?: is it| today)?", normalized):
        return "clock", normalized
    if normalized in {"system status", "system stats", "cpu", "gpu", "cpu usage", "gpu usage"}:
        return "stats", ""
    if normalized in {"tasks", "my tasks", "list tasks", "show tasks", "show my tasks", "show me my tasks"}:
        return "list_tasks", ""
    if normalized in {"help", "what can you do", "commands"}:
        return "help", ""
    if re.fullmatch(rf"(?:pause|stop)(?:\s+(?:the\s+)?(?:music|{_SPOTIFY}))?", normalized):
        return "spotify", "pause"
    if re.fullmatch(rf"(?:play|resume)(?:\s+(?:the\s+)?(?:music|{_SPOTIFY}))?", normalized):
        return "spotify", "play"
    if normalized in {"next", "next song", "next track", "skip", "skip song", "skip track"}:
        return "spotify", "next"
    if normalized in {"previous", "previous song", "previous track", "go back"}:
        return "spotify", "previous"
    if normalized in {"mute", "unmute", "volume up", "volume down"}:
        return "media_key", normalized
    if normalized in {"turn volume up", "turn the volume up", "increase volume", "raise volume"}:
        return "media_key", "volume up"
    if normalized in {"turn volume down", "turn the volume down", "decrease volume", "lower volume", "reduce volume"}:
        return "media_key", "volume down"
    return "conversation", text


class ClapDetector:
    """Detect two separated, brief, sharp transients; reject sustained loud sound."""
    def __init__(self, threshold=0.16):
        self.threshold = threshold
        self.noise = 0.005
        self.last_clap = None
        self.cooldown_until = 0.0
        self.armed = True

    def feed(self, samples, now=None):
        import numpy as np
        now = time.monotonic() if now is None else now
        if len(samples) < 8:
            return False
        samples = np.asarray(samples, dtype=np.float32)
        peak = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(samples * samples)))
        sharpness = float(np.sqrt(np.mean(np.diff(samples) ** 2))) / max(rms, 1e-6)
        if peak < self.threshold * 0.5:
            self.armed = True
            self.noise = 0.98 * self.noise + 0.02 * rms
        threshold = max(self.threshold, self.noise * 7)
        if (now < self.cooldown_until or not self.armed or peak < threshold
                or peak / max(rms, 1e-6) < 2.0 or sharpness < 0.6):
            return False
        self.armed = False
        if self.last_clap is not None:
            gap = now - self.last_clap
            if 0.15 <= gap <= 0.85:
                self.last_clap = None
                self.cooldown_until = now + 2.5
                return True
            if gap < 0.15:
                return False
        self.last_clap = now
        return False
