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
    "spotify_uri": "", "ai_provider": "Local commands",
    "ai_model": "llama3.2", "ollama_url": "http://127.0.0.1:11434",
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
                    self.data["settings"].update(loaded.get("settings", {}))
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


def parse_command(text):
    """Turn speech or typed input into an explicit desktop operation."""
    text = re.sub(r"^\s*(?:hey\s+)?(?:jarvis|jar vus|jar v is)[,\s]*", "", text, flags=re.I).strip()
    normalized = text.lower().rstrip(".!?")
    for pattern, action in [
        (r"(?:please\s+)?(?:add (?:a )?task|new task|remind me to)\s*(?:to\s+|:\s*)?(.+)", "add_task"),
        (r"(?:please\s+)?(?:search(?: in)? chrome for|search chrome|chrome search(?: for)?)\s+(.+)", "chrome_search"),
        (r"(?:please\s+)?(?:type(?: in)?(?: the)? chrome(?: search| address)? bar|type(?: in)?(?: the)?(?: search| address) bar|write(?: in)?(?: the)?(?: chrome)?(?: search| address) bar|type in chrome)\s+(.+)", "chrome_type"),
        (r"(?:please\s+)?(?:open|launch|start)\s+(.+)", "open_app"),
        (r"(?:search(?: the web)? for|google)\s+(.+)", "search_web"),
        (r"(?:please\s+)?search spotify for\s+(.+)", "spotify_search"),
        (r"(?:please\s+)?play\s+(.+)", "spotify_play_song"),
        (r"(?:set\s+)?(?:the\s+)?volume(?:\s+to)?\s+(\d{1,3})(?:\s*(?:percent|%))?", "volume"),
        (r"(?:complete|finish|done with) task\s+(\d+)", "complete_task"),
        (r"(?:delete|remove) task\s+(\d+)", "remove_task"),
    ]:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            argument = match.group(1).strip()
            if action == "open_app" and argument.lower() in {"spotify", "music"}:
                return "spotify", "play"
            if action == "spotify_play_song" and argument.lower() in {"spotify", "music", "my music"}:
                return "spotify", "play"
            if action == "spotify_play_song":
                argument = re.sub(r"\s+on spotify$", "", argument, flags=re.I).strip()
            if action in {"spotify_play_song", "spotify_search", "chrome_type", "chrome_search"}:
                # Preserve casing and punctuation inside matching spoken/typed quotes.
                quotes = {'"': '"', "'": "'", "“": "”", "‘": "’"}
                if len(argument) >= 2 and quotes.get(argument[0]) == argument[-1]:
                    argument = argument[1:-1].strip()
                if not argument:
                    return "conversation", text
            return action, argument
    if normalized in {"search that", "search it", "submit search", "search in chrome", "chrome enter"}:
        return "chrome_submit", ""
    if normalized in {"sleep", "go to sleep", "sleep mode", "standby", "stand by"}:
        return "sleep", ""
    if normalized in {"wake up", "wake", "hey", "hello", ""}:
        return "wake", ""
    if re.fullmatch(r"(?:what(?:'s| is)? |tell me |the )?(?:the )?(?:time|date)(?: is it| today)?", normalized):
        return "clock", normalized
    if normalized in {"system status", "system stats", "cpu", "gpu", "cpu usage", "gpu usage"}:
        return "stats", ""
    if normalized in {"tasks", "my tasks", "list tasks", "show tasks", "show my tasks"}:
        return "list_tasks", ""
    if normalized in {"help", "what can you do", "commands"}:
        return "help", ""
    if normalized in {"pause", "pause music", "pause spotify", "stop music"}:
        return "spotify", "pause"
    if normalized in {"play", "resume", "resume music", "resume spotify", "play spotify", "play music"}:
        return "spotify", "play"
    if normalized in {"next", "next song", "next track", "skip", "skip song"}:
        return "spotify", "next"
    if normalized in {"previous", "previous song", "previous track", "go back"}:
        return "spotify", "previous"
    if normalized in {"mute", "unmute", "volume up", "volume down"}:
        return "media_key", normalized
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
