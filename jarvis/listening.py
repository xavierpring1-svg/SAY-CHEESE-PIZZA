"""Small, bounded microphone buffers; no audio is stored on disk."""
from __future__ import annotations

import audioop
from collections import deque

import numpy as np


class AudioInput:
    def __init__(self, sample_rate):
        self.sample_rate = int(sample_rate)
        self.state = None

    def convert(self, pcm, gain=1.0):
        if self.sample_rate != 16000:
            pcm, self.state = audioop.ratecv(pcm, 2, 1, self.sample_rate, 16000, self.state)
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        return np.clip(samples * max(1.0, min(4.0, float(gain))), -1, 1)


class Utterances:
    def __init__(self, silence=0.65, maximum=20.0):
        self.silence = silence
        self.maximum = maximum
        self.reset()

    def reset(self):
        self.preroll = deque(maxlen=12)
        self.parts = []
        self.duration = 0.0
        self.quiet = 0.0
        self.voiced = 0.0
        self.noise = 0.002

    def feed(self, samples):
        if len(samples) == 0:
            return None
        duration = len(samples) / 16000
        rms = float(np.sqrt(np.mean(samples * samples)))
        voiced = rms > max(0.004, min(0.03, self.noise * 3.5))
        if not self.parts:
            self.preroll.append(samples.copy())
            if not voiced:
                self.noise = 0.97 * self.noise + 0.03 * min(rms, 0.01)
                return None
            self.parts = list(self.preroll)
            self.preroll.clear()
            self.duration = sum(len(part) for part in self.parts) / 16000
        else:
            self.parts.append(samples.copy())
            self.duration += duration
        if voiced:
            self.voiced += duration
            self.quiet = 0.0
        else:
            self.quiet += duration
        if self.quiet < self.silence and self.duration < self.maximum:
            return None
        clip = np.concatenate(self.parts) if self.voiced >= 0.15 else None
        self.parts = []
        self.duration = self.voiced = self.quiet = 0.0
        return clip


def normalized_clip(samples):
    samples = np.asarray(samples, dtype=np.float32)
    if not len(samples):
        return samples
    peak = float(np.max(np.abs(samples)))
    # Improve quiet input without amplifying near-silent background into speech.
    if 0.008 <= peak < 0.7:
        samples = samples * min(4.0, 0.7 / peak)
    return np.clip(samples, -1.0, 1.0)


def microphone_choice(devices, default_index):
    """Avoid recording the PC's speakers when a physical default is available."""
    def usable(index):
        if not isinstance(index, int) or not 0 <= index < len(devices):
            return False
        name = devices[index].get("name", "").casefold()
        return (devices[index].get("max_input_channels", 0) > 0
                and not any(term in name for term in ("stereo mix", "what u hear", "loopback", "output capture")))
    if usable(default_index):
        return default_index
    for index in range(len(devices)):
        if usable(index):
            return index
    raise RuntimeError("No microphone input was found. Connect a microphone and select it in Settings.")
